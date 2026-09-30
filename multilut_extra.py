#!/usr/bin/env python3
"""Helpers de sistema do MultiLUT Controller (sem GTK).

Reúne o que integra o aplicativo com o ambiente do usuário: opção de
inicialização do Steam (VDF), diagnóstico da instalação e backup do
aplicativo (exportar/importar configuração completa).
"""

from __future__ import annotations

import json
import re
import shutil
import time
import zipfile
from pathlib import Path

import multilut_core as core


# ------------------------------------------------------------ opção do Steam
def find_localconfig_files(roots: list[Path] | None = None) -> list[Path]:
    """Arquivos localconfig.vdf do Steam que guardam LaunchOptions.

    As opções por jogo ficam em userdata/<id>/config/localconfig.vdf;
    instalações antigas podem ter config/localconfig.vdf na raiz do Steam.
    """
    files: list[Path] = []
    for root in roots if roots is not None else core.steam_roots():
        userdata = root / "userdata"
        if userdata.is_dir():
            for entry in sorted(userdata.iterdir()):
                candidate = entry / "config/localconfig.vdf"
                try:
                    if candidate.is_file():
                        files.append(candidate)
                except OSError:
                    continue
        legacy = root / "config/localconfig.vdf"
        try:
            if legacy.is_file() and legacy not in files:
                files.append(legacy)
        except OSError:
            continue
    return files


def _vdf_tokens(text: str) -> list[str]:
    """Tokens de um arquivo VDF: chaves, valores, '{' e '}'.

    Comentários com // são descartados; aspas são removidas dos valores.
    """
    text = re.sub(r"//[^\r\n]*", "", text)
    tokens: list[str] = []
    for raw in re.finditer(r'"((?:\\.|[^"\\])*)"|([{}])', text):
        if raw.group(1) is not None:
            tokens.append(raw.group(1).replace('\\"', '"'))
        else:
            tokens.append(raw.group(2))
    return tokens


def parse_launch_options(text: str, app_id: str = core.STEAM_APP_ID) -> str | None:
    """Extrai LaunchOptions do jogo (appid) de um arquivo VDF.

    O VDF do Steam aninha como ... "apps" { "<appid>" { "LaunchOptions" "..." } }.
    A busca percorre o arquivo inteiro e, ao encontrar o objeto do appid,
    varre aquele objeto em profundidade zero. Retorna None quando o jogo
    não tem LaunchOptions no arquivo.
    """
    tokens = _vdf_tokens(text)
    length = len(tokens)
    index = 0
    while index < length - 1:
        if tokens[index] == app_id and tokens[index + 1] == "{":
            depth = 0
            cursor = index + 2
            while cursor < length:
                token = tokens[cursor]
                if token == "}":
                    if depth == 0:
                        return None  # fim do objeto do app sem LaunchOptions
                    depth -= 1
                elif token == "{":
                    depth += 1
                elif (
                    token == "LaunchOptions"
                    and depth == 0
                    and cursor + 1 < length
                    and tokens[cursor + 1] not in ("{", "}")
                ):
                    return tokens[cursor + 1]
                cursor += 1
            return None
        index += 1
    return None


LAUNCH_OPTION_REQUIREMENTS = {
    "%command%": "executa o jogo com o ambiente do Steam",
    "ENABLE_VKBASALT=1": "ativa a camada vkBasalt no Vulkan",
    "-condebug": "grava o console.log (usado pelo piloto automático por mapa)",
}


def launch_option_report() -> tuple[str, str]:
    """Estado da opção de inicialização do Insurgency no Steam.

    Retorna (estado, detalhe) com estado em "ok", "warn", "fail" ou "info".
    """
    files = find_localconfig_files()
    if not files:
        return "info", "Steam não localizado; configure a opção manualmente."
    found: str | None = None
    for path in files:
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        options = parse_launch_options(text)
        if options is not None:
            found = options.strip()
            break
    if not found:
        return "fail", "Insurgency sem opção de inicialização no Steam."
    missing = [need for need in LAUNCH_OPTION_REQUIREMENTS if need not in found]
    if missing:
        return "warn", (
            "Opção parcial: falta " + " e ".join(missing) + "."
        )
    return "ok", "Launch option ativa com vkBasalt habilitado."


def launch_option_files() -> list[Path]:
    return find_localconfig_files()


# ------------------------------------------------- escrita da opção (Steam fechado)
def steam_running() -> bool:
    """True se houver processo do Steam ativo (ele regravaria localconfig.vdf)."""
    import subprocess

    for name in ("steam", "steam.exe"):
        try:
            probe = subprocess.run(
                ["pgrep", "-x", name], capture_output=True, check=False
            )
        except (OSError, ValueError):
            continue
        if probe.returncode == 0:
            return True
    return False


def _key_block_span(text: str, key: str) -> tuple[int, int] | None:
    """Localiza o bloco VDF de uma chave: devolve (índice do '{', índice do '}')."""
    needle = f'"{key}"'
    search_from = 0
    while True:
        idx = text.find(needle, search_from)
        if idx == -1:
            return None
        search_from = idx + len(needle)
        rest = text[search_from:]
        stripped = rest.lstrip()
        if not stripped.startswith("{"):
            continue
        brace = search_from + (len(rest) - len(stripped))
        break
    depth = 0
    in_quote = False
    i = brace
    while i < len(text):
        char = text[i]
        if in_quote:
            if char == "\\":
                i += 2
                continue
            if char == '"':
                in_quote = False
        elif char == '"':
            in_quote = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return brace, i
        i += 1
    return None


def patch_launch_options_text(
    text: str,
    tokens: tuple[str, ...] | None = None,
    app_id: str = core.STEAM_APP_ID,
) -> tuple[str, bool]:
    """Garante os tokens na LaunchOptions do jogo no texto de um VDF.

    Acrescenta apenas o que falta (idempotente), cria a chave LaunchOptions
    dentro do bloco do jogo quando ela não existe e cria o próprio bloco do
    jogo dentro de "apps" quando necessário. Devolve (novo_texto, mudou).
    """
    if tokens is None:
        tokens = tuple(LAUNCH_OPTION_REQUIREMENTS)
    span = _key_block_span(text, app_id)
    if span is None:
        apps_span = _key_block_span(text, "apps")
        if apps_span is None:
            return text, False  # VDF sem "apps": não inventamos a hierarquia
        brace = apps_span[0]
        joined = " ".join(tokens)
        insertion = (
            f'\n\t\t\t\t"{app_id}"\n'
            f'\t\t\t\t{{\n'
            f'\t\t\t\t\t"LaunchOptions"\t\t"{joined}"\n'
            f"\t\t\t\t}}"
        )
        return text[: brace + 1] + insertion + text[brace + 1 :], True

    start, end = span
    block = text[start : end + 1]
    match = re.search(r'"LaunchOptions"\s+"([^"]*)"', block)
    if not match:
        joined = " ".join(tokens)
        insertion = f'\n\t\t"LaunchOptions"\t\t"{joined}"'
        new_block = block[:1] + insertion + block[1:]
        return text[:start] + new_block + text[end + 1 :], True

    value = match.group(1)
    missing = [token for token in tokens if token not in value]
    if not missing:
        return text, False
    new_value = f"{value} {' '.join(missing)}".strip()
    replacement = f'"LaunchOptions"\t\t"{new_value}"'
    new_block = block.replace(match.group(0), replacement, 1)
    return text[:start] + new_block + text[end + 1 :], True


def ensure_launch_options(
    tokens: tuple[str, ...] | None = None,
    roots: list[Path] | None = None,
) -> dict:
    """Corrige a opção de inicialização do jogo nos localconfig.vdf do Steam.

    Exige o Steam fechado (ele regravaria a configuração em memória). Cria um
    backup .multilut.bak do arquivo original antes da primeira gravação e
    devolve um resumo com os arquivos alterados, já corretos e ignorados.
    """
    if steam_running():
        raise core.MultiLUTError(
            "o Steam está aberto e regravaria a configuração — "
            "feche o Steam e tente corrigir novamente"
        )
    files = find_localconfig_files(roots)
    summary: dict = {"changed": [], "already_ok": [], "skipped": []}
    for path in files:
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
            mode = path.stat().st_mode & 0o777
        except OSError:
            summary["skipped"].append(str(path))
            continue
        try:
            new_text, changed = patch_launch_options_text(text, tokens)
        except (OSError, ValueError):
            summary["skipped"].append(str(path))
            continue
        if not changed:
            summary["already_ok"].append(str(path))
            continue
        backup = path.with_name(path.name + ".multilut.bak")
        if not backup.exists():
            try:
                backup.write_text(text, encoding="utf-8")
            except OSError:
                pass
        try:
            core._atomic_write(path, new_text, mode)
        except OSError as exc:
            raise core.MultiLUTError(f"não foi possível gravar {path}: {exc}") from exc
        summary["changed"].append(str(path))
    if files and not summary["changed"] and not summary["already_ok"]:
        raise core.MultiLUTError(
            "nenhum localconfig.vdf pôde ser corrigido; configure a opção "
            "manualmente nas propriedades do jogo na Steam"
        )
    return summary


# ------------------------------------------------------------ diagnóstico
def vkbasalt_config_status(
    path: Path | None = None,
) -> tuple[str, str]:
    """Confere se o vkBasalt.conf existe e inclui o MultiLUT nos efeitos."""
    target = core.default_vkbasalt_config_path() if path is None else path
    if not target.is_file():
        return "info", (
            "vkBasalt.conf ausente em ~/.config/vkBasalt — crie ao configurar "
            "o vkBasalt (o app instala o shader e o atlas)."
        )
    try:
        text = target.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return "fail", f"Não foi possível ler vkBasalt.conf: {exc}"
    match = re.search(r"^\s*effects\s*=\s*(.+)$", text, re.MULTILINE)
    effects = [
        item.strip() for item in match.group(1).split(",") if item.strip()
    ] if match else []
    if any("multilut" in effect.casefold() for effect in effects):
        return "ok", "effects inclui o MultiLUT: " + ", ".join(effects)
    if effects:
        return "warn", "effects não inclui o MultiLUT: " + ", ".join(effects)
    return "warn", "vkBasalt.conf existe, mas não define effects."


def vkbasalt_layer_status(
    roots: list[Path] | None = None,
) -> tuple[str, str]:
    """Verifica a presença do JSON de camada implícita do vkBasalt."""
    if roots is None:
        home = Path.home()
        roots = [
            Path("/usr/share/vulkan/implicit_layer.d"),
            Path("/usr/local/share/vulkan/implicit_layer.d"),
            Path("/etc/vulkan/implicit_layer.d"),
            home / ".local/share/vulkan/implicit_layer.d",
        ]
    for root in roots:
        try:
            if not root.is_dir():
                continue
            for entry in sorted(root.glob("*.json")):
                try:
                    text = entry.read_text(encoding="utf-8", errors="ignore")
                except OSError:
                    continue
                if "vkBasalt" in text or "VKBASALT" in text.upper():
                    return "ok", f"Camada Vulkan: {entry}"
        except OSError:
            continue
    return "fail", "vkBasalt não encontrado (instale o pacote da sua distro)."


def vulkan_runtime_status() -> tuple[str, str]:
    """Runtime Vulkan presente (loader ou vulkaninfo)."""
    if shutil.which("vulkaninfo") is not None:
        return "ok", "Runtime Vulkan disponível (vulkaninfo presente)."
    for pattern in ("/usr/lib*/libvulkan.so*", "/usr/lib/*/libvulkan.so*", "/usr/lib*/x86_64-linux-gnu/libvulkan.so*"):
        if glob_any(pattern):
            return "ok", "Loader Vulkan (libvulkan) presente."
    return "fail", "Loader Vulkan não localizado neste sistema."


def glob_any(pattern: str) -> bool:
    from glob import glob

    return bool(glob(pattern))


def preview_stack_status() -> tuple[str, str]:
    """Pillow/numpy opcionais usados pela simulação de LUT (item de preview)."""
    missing: list[str] = []
    try:
        import numpy  # noqa: F401
    except ImportError:
        missing.append("numpy")
    try:
        import PIL  # noqa: F401
    except ImportError:
        missing.append("Pillow")
    if missing:
        return "info", (
            "Simulação de LUT indisponível (ausente: "
            + ", ".join(missing)
            + "); no Solus: sudo eopkg it numpy python-pillow."
        )
    return "ok", "Pillow e numpy disponíveis para simulação de LUT."


def console_log_status() -> tuple[str, str]:
    console = core.find_console_log()
    if console is not None:
        return "ok", f"console.log acessível: {console}"
    return "info", "console.log ausente; adicione -condebug à opção do jogo."


def auto_map_pilot_status() -> tuple[str, str]:
    """Estado do piloto automático por mapa (troca de LUT via console.log)."""
    if not bool(core.load_config().get("auto_map_switch", False)):
        return "info", "Desligado; ligue a opção na aba Perfis para trocar o LUT pelo mapa."
    console = core.find_console_log()
    if console is None:
        return "warn", (
            "console.log não encontrado: o piloto não consegue identificar o mapa "
            "(confira -condebug e a instalação do jogo; o app precisa estar aberto)."
        )
    detail = f"console.log monitorado: {console}"
    try:
        age = max(0.0, time.time() - console.stat().st_mtime)
        if age < 600:
            detail += f" (atualizado há {int(age)} s)"
    except OSError:
        pass
    return "ok", detail


def diagnostic_report() -> list[dict]:
    """Checklist de diagnóstico: cada item é (titulo, estado, detalhe)."""
    items: list[dict] = []

    shader = core.default_shader_path()
    candidates = core.find_shader_candidates()
    if not candidates:
        items.append(
            {
                "title": "Shader MultiLUT",
                "state": "fail",
                "detail": "Não encontrado; use Instalar/atualizar pacote na aba Perfis.",
            }
        )
    else:
        valid, message = core.validate_shader(candidates[0])
        items.append(
            {
                "title": "Shader MultiLUT",
                "state": "ok" if valid else "fail",
                "detail": message,
            }
        )
        del shader

    state, detail = vkbasalt_layer_status()
    items.append({"title": "vkBasalt (camada Vulkan)", "state": state, "detail": detail})

    state, detail = vkbasalt_config_status()
    items.append({"title": "vkBasalt.conf (effects)", "state": state, "detail": detail})

    state, detail = vulkan_runtime_status()
    items.append({"title": "Runtime Vulkan", "state": state, "detail": detail})

    state, detail = launch_option_report()
    items.append(
        {"title": "Opção de inicialização do Steam", "state": state, "detail": detail}
    )

    state, detail = console_log_status()
    items.append(
        {"title": "console.log do jogo", "state": state, "detail": detail}
    )

    state, detail = auto_map_pilot_status()
    items.append(
        {"title": "Piloto automático por mapa", "state": state, "detail": detail}
    )

    state, detail = preview_stack_status()
    items.append({"title": "Simulação de LUT (Pillow/numpy)", "state": state, "detail": detail})

    roots = core.find_game_roots()
    if roots:
        detail = "; ".join(str(root) for root in roots[:3])
        if len(roots) > 3:
            detail += f" (+{len(roots) - 3})"
        items.append(
            {
                "title": f"Instalação do jogo ({len(roots)})",
                "state": "ok",
                "detail": detail,
            }
        )
    else:
        items.append(
            {
                "title": "Instalação do jogo",
                "state": "fail",
                "detail": "Nenhuma biblioteca Steam com Insurgency (2014) encontrada.",
            }
        )
    return items


# ------------------------------------------------------------ backup do aplicativo
BUNDLE_MEMBERS = ("config.json", "history.jsonl")


def export_config_bundle(target: Path) -> int:
    """Empacota config + histórico em um .zip portátil. Retorna nº de itens."""
    target = Path(target).expanduser()
    config = core.load_config()
    written = 0
    target.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as bundle:
        bundle.writestr("config.json", json.dumps(config, ensure_ascii=False, indent=2))
        written += 1
        history = core.history_path()
        if history.is_file():
            bundle.write(history, "history.jsonl")
            written += 1
    return written


def import_config_bundle(source: Path) -> dict:
    """Restaura config + histórico de um .zip gerado pelo export.

    Caminhos de máquina (shader_path/game_dir) vindos do arquivo só são
    mantidos se existirem neste sistema; caso contrário os locais ficam.
    """
    source = Path(source).expanduser()
    with zipfile.ZipFile(source) as bundle:
        names = set(bundle.namelist())
        if "config.json" not in names:
            raise core.MultiLUTError("O arquivo não contém config.json.")
        try:
            data = json.loads(bundle.read("config.json").decode("utf-8"))
        except (ValueError, UnicodeError) as exc:
            raise core.MultiLUTError(f"config.json inválido no backup: {exc}") from exc
        if not isinstance(data, dict):
            raise core.MultiLUTError("config.json do backup não é um objeto.")

        local_config = core.load_config()
        remembered_shader = data.get("shader_path")
        if not isinstance(remembered_shader, str) or not Path(remembered_shader).expanduser().is_file():
            if isinstance(local_config.get("shader_path"), str):
                data["shader_path"] = local_config["shader_path"]
            else:
                data.pop("shader_path", None)
        remembered_game = data.get("game_dir")
        if not isinstance(remembered_game, str) or not Path(remembered_game).expanduser().is_dir():
            if isinstance(local_config.get("game_dir"), str):
                data["game_dir"] = local_config["game_dir"]
            else:
                data.pop("game_dir", None)

        core.save_config(data)
        history_entries = 0
        if "history.jsonl" in names:
            try:
                raw = bundle.read("history.jsonl").decode("utf-8")
            except (OSError, UnicodeError) as exc:
                raise core.MultiLUTError(f"history.jsonl inválido: {exc}") from exc
            target_history = core.history_path()
            target_history.parent.mkdir(parents=True, exist_ok=True)
            mode = target_history.stat().st_mode & 0o777 if target_history.exists() else 0o600
            core._atomic_write(target_history, raw, mode)
            history_entries = len([line for line in raw.splitlines() if line.strip()])
        return {
            "config_keys": len(data),
            "history_entries": history_entries,
        }
