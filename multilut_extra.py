#!/usr/bin/env python3
"""Helpers de sistema do MultiLUT Controller (sem GTK).

Reúne o que integra o aplicativo com o ambiente do usuário: opção de
inicialização do Steam (VDF), diagnóstico da instalação e backup do
aplicativo (exportar/importar configuração completa).
"""

from __future__ import annotations

import json
import os
import platform
import re
import shutil
import socket
import subprocess
import tempfile
import time
import zipfile
from datetime import datetime
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
    daemon = query_daemon()
    if daemon is not None:
        last = daemon.get("last_map") or {}
        detail = "gerenciado pelo daemon (funciona sem a janela aberta)"
        if last.get("profile_name"):
            detail += f"; último mapa: {last.get('token', '?')} -> {last['profile_name']}"
        return "ok", detail
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

    daemon = query_daemon()
    if daemon is not None:
        detail = (
            f"ativo (pid {daemon.get('pid', '?')}); troca de perfil por mapa "
            "funciona com a janela fechada"
        )
        items.append({"title": "Daemon (piloto sem janela)", "state": "ok", "detail": detail})
    elif daemon_unit_installed():
        items.append(
            {
                "title": "Daemon (piloto sem janela)",
                "state": "info",
                "detail": "serviço instalado, parado; inicie com multilut-ctl daemon start",
            }
        )
    else:
        items.append(
            {
                "title": "Daemon (piloto sem janela)",
                "state": "info",
                "detail": "opcional; instale com multilut-ctl daemon install "
                "para o piloto funcionar sem a janela aberta",
            }
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


# ------------------------------------------------------------ daemon (piloto sem janela)
DAEMON_UNIT_NAME = "multilut-daemon.service"
DAEMON_UNIT_TEMPLATE = """[Unit]
Description=MultiLUT Controller - piloto automatico por mapa (sem janela)
Documentation=https://github.com/felipesantiago-coder/multilut-controller
After=graphical-session.target

[Service]
Type=simple
ExecStart=/usr/bin/python3 @APP_DIR@/multilut_daemon.py
Restart=on-failure
RestartSec=3

[Install]
WantedBy=default.target
"""


def daemon_runtime_dir() -> Path:
    """Diretório do socket de controle (XDG_RUNTIME_DIR ou /tmp por usuário)."""
    runtime = os.environ.get("XDG_RUNTIME_DIR", "").strip()
    base = Path(runtime) if runtime else Path(tempfile.gettempdir())
    return base / f"multilut-controller-{os.getuid()}"


def daemon_socket_path() -> Path:
    return daemon_runtime_dir() / "daemon.sock"


def daemon_status_path() -> Path:
    return core.app_state_dir() / "daemon.json"


def write_daemon_status(data: dict) -> None:
    """Grava o estado do daemon para leitura por GUI/CLI quando o socket não responde."""
    path = daemon_status_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        mode = path.stat().st_mode & 0o777 if path.exists() else 0o600
        core._atomic_write(path, json.dumps(data, ensure_ascii=False, indent=2) + "\n", mode)
    except OSError:
        pass


def read_daemon_status() -> dict | None:
    path = daemon_status_path()
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeError):
        return None
    return data if isinstance(data, dict) else None


def query_daemon(timeout: float = 1.5) -> dict | None:
    """Consulta o daemon vivo pelo socket; None quando não está rodando."""
    path = daemon_socket_path()
    if not path.exists():
        return None
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
            client.settimeout(timeout)
            client.connect(str(path))
            client.sendall(b'{"cmd": "status"}\n')
            reply = b""
            while b"\n" not in reply:
                chunk = client.recv(4096)
                if not chunk:
                    break
                reply += chunk
    except OSError:
        return None
    try:
        data = json.loads(reply.decode("utf-8", errors="ignore").strip())
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


def daemon_running() -> bool:
    return query_daemon() is not None


def daemon_status() -> dict:
    """Estado para CLI/GUI: socket ao vivo, senão último estado gravado."""
    live = query_daemon()
    if live is not None:
        return {"alive": True, **live}
    stored = read_daemon_status() or {}
    return {"alive": False, **stored}


def daemon_systemctl(action: str) -> tuple[bool, str]:
    """systemctl --user <ação> no serviço do daemon; (False, motivo) sem systemd."""
    try:
        out = subprocess.run(
            ["systemctl", "--user", action, DAEMON_UNIT_NAME],
            capture_output=True,
            text=True,
            timeout=20.0,
        )
    except FileNotFoundError:
        return False, "systemctl não disponível neste sistema."
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, f"systemctl falhou: {exc}"
    detail = (out.stdout or out.stderr or "").strip().splitlines()
    return out.returncode == 0, detail[-1] if detail else ""


def daemon_unit_installed(unit_dir: Path | None = None) -> bool:
    return daemon_unit_path(unit_dir).is_file()


def daemon_unit_path(unit_dir: Path | None = None) -> Path:
    root = unit_dir or (Path.home() / ".config/systemd/user")
    return root / DAEMON_UNIT_NAME


def daemon_install_unit(app_dir: Path | None = None, unit_dir: Path | None = None) -> Path:
    """Instala o serviço de usuário apontando para o diretório real do app."""
    app_dir = app_dir or core.app_repo_dir()
    unit_path = daemon_unit_path(unit_dir)
    unit_path.parent.mkdir(parents=True, exist_ok=True)
    content = DAEMON_UNIT_TEMPLATE.replace("@APP_DIR@", str(app_dir))
    core._atomic_write(unit_path, content, 0o644)
    daemon_systemctl("daemon-reload")
    return unit_path


def daemon_uninstall_unit(unit_dir: Path | None = None) -> bool:
    unit_path = daemon_unit_path(unit_dir)
    if not unit_path.is_file():
        return False
    daemon_systemctl("stop")
    daemon_systemctl("disable")
    try:
        unit_path.unlink()
    except OSError:
        pass
    daemon_systemctl("daemon-reload")
    return True


def daemon_start() -> tuple[bool, str]:
    """Inicia o daemon: via systemd quando o serviço existe, senão avulso."""
    if daemon_running():
        return True, "O daemon já está em execução."
    if daemon_unit_installed():
        ok, detail = daemon_systemctl("start")
        if not ok:
            return False, detail or "systemctl não iniciou o serviço."
    else:
        app_dir = core.app_repo_dir()
        script = app_dir / "multilut_daemon.py"
        if not script.is_file():
            return False, f"multilut_daemon.py não encontrado em {app_dir}."
        try:
            subprocess.Popen(
                ["/usr/bin/python3" if Path("/usr/bin/python3").is_file() else "python3",
                 str(script)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
        except OSError as exc:
            return False, f"Não foi possível iniciar o daemon: {exc}"
    for _ in range(20):  # até ~2 s para o socket aparecer
        if daemon_running():
            return True, "Daemon iniciado (piloto ativo sem janela)."
        time.sleep(0.1)
    return False, "O daemon não respondeu após o início."


def daemon_stop() -> tuple[bool, str]:
    """Para o daemon: manda stop pelo socket e, se houver serviço, para pelo systemd."""
    stopped = False
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
            client.settimeout(2.0)
            client.connect(str(daemon_socket_path()))
            client.sendall(b'{"cmd": "stop"}\n')
            client.recv(4096)
            stopped = True
    except OSError:
        pass
    if daemon_unit_installed():
        daemon_systemctl("stop")
    for _ in range(20):
        if not daemon_running():
            return True, "Daemon parado." if stopped else "Daemon parado (serviço do systemd)."
        time.sleep(0.1)
    return False, "O daemon continua respondendo; verifique systemctl --user status multilut-daemon."


# ------------------------------------------------------------ autostart na sessão
AUTOSTART_DESKTOP_TEMPLATE = """[Desktop Entry]
Type=Application
Name=MultiLUT Controller
Comment=Gerencie perfis MultiLUT do Insurgency no vkBasalt
Exec=@APP_DIR@/run.sh@MINIMIZED@
Icon=com.felipesantiago.MultiLUTController
Terminal=false
Categories=Game;Utility;GTK;
Keywords=vkBasalt;ReShade;LUT;Insurgency;Vulkan;
StartupNotify=true
StartupWMClass=com.felipesantiago.MultiLUTController
X-GNOME-Autostart-enabled=true
"""


def autostart_path() -> Path:
    """Entrada XDG de autostart da sessão (~/.config/autostart)."""
    return Path.home() / ".config/autostart/com.felipesantiago.MultiLUTController.desktop"


def autostart_installed() -> bool:
    return autostart_path().is_file()


def autostart_install(app_dir: Path | None = None, minimized: bool = True) -> Path:
    """Instala a entrada de autostart; a janela pode abrir oculta (--minimized)."""
    app_dir = app_dir or core.app_repo_dir()
    flag = " --minimized" if minimized else ""
    target = autostart_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    content = AUTOSTART_DESKTOP_TEMPLATE.replace("@APP_DIR@", str(app_dir))
    content = content.replace("@MINIMIZED@", flag)
    core._atomic_write(target, content, 0o644)
    return target


def autostart_remove() -> bool:
    target = autostart_path()
    try:
        target.unlink()
        return True
    except FileNotFoundError:
        return False
    except OSError:
        return False


# ------------------------------------------------------------ relatório de diagnóstico
def _distro_pretty_name() -> str:
    for candidate in ("/etc/os-release", "/usr/lib/os-release"):
        try:
            for line in Path(candidate).read_text(encoding="utf-8").splitlines():
                if line.startswith("PRETTY_NAME="):
                    return line.split("=", 1)[1].strip().strip('"')
        except OSError:
            continue
    return "desconhecida"


def build_diagnostic_text(
    include_log_tail: bool = True,
    log_tail_lines: int = 60,
    history_limit: int = 20,
) -> str:
    """Relatório em texto pronto para colar em uma issue do projeto.

    Reúne versões, ambiente, itens do doctor, configuração relevante,
    histórico recente e (opcional) o final do console.log do jogo.
    """
    lines: list[str] = []
    lines.append(f"MultiLUT Controller v{core.APP_VERSION} — relatório de diagnóstico")
    lines.append(f"Gerado em {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append("")
    lines.append("== Ambiente ==")
    lines.append(f"Distribuição: {_distro_pretty_name()}")
    lines.append(f"Kernel: {platform.release()}")
    lines.append(f"Python: {platform.python_version()}")
    desktop = os.environ.get("XDG_CURRENT_DESKTOP", "").strip() or "desconhecido"
    session_type = os.environ.get("XDG_SESSION_TYPE", "").strip() or "?"
    lines.append(f"Sessão: {desktop} ({session_type})")
    head = core.local_git_head()
    lines.append(f"Instalação: {'git ' + head if head else 'sem git (cópia)'}")
    daemon = query_daemon()
    if daemon is not None:
        lines.append(
            f"Daemon: ativo (pid {daemon.get('pid', '?')}, "
            f"eventos: {daemon.get('events', 0)})"
        )
    else:
        lines.append("Daemon: inativo")
    lines.append("")

    lines.append("== Diagnóstico ==")
    labels = {"ok": "ok   ", "warn": "aviso", "fail": "FALHA", "info": "info "}
    try:
        items = diagnostic_report()
    except Exception as exc:  # noqa: BLE001 - relatório nunca levanta
        items = [{"title": "Diagnóstico", "state": "fail", "detail": str(exc)}]
    for item in items:
        state = str(item.get("state") or "?")
        lines.append(
            f"[{labels.get(state, state)}] {item.get('title')}: {item.get('detail')}"
        )
    lines.append("")

    lines.append("== Configuração relevante ==")
    config = core.load_config()
    interesting = (
        "shader_path",
        "game_dir",
        "auto_map_switch",
        "auto_apply_on_launch",
        "notify_changes",
        "global_shortcut",
        "autostart_minimized",
        "check_updates",
        "game_width",
        "game_height",
    )
    for key in interesting:
        if key in config:
            lines.append(f"{key}: {config[key]}")
    lines.append("")

    lines.append(f"== Histórico (últimos {history_limit}) ==")
    entries = core.read_history(limit=history_limit)
    if not entries:
        lines.append("(histórico vazio)")
    for entry in reversed(entries):
        lines.append(
            f"{entry.get('ts', '?')}  {entry.get('profile_id', '?')} — "
            f"{entry.get('profile_name', '?')}  [{entry.get('origin', '?')}]"
            + (f"  ({entry['detail']})" if entry.get("detail") else "")
        )
    lines.append("")

    lines.append(f"== console.log (últimas {log_tail_lines} linhas) ==")
    console = core.find_console_log() if include_log_tail else None
    if console is None:
        lines.append("(console.log ausente; adicione -condebug à opção do jogo)")
    else:
        try:
            with console.open("rb") as stream:
                stream.seek(0, os.SEEK_END)
                size = stream.tell()
                stream.seek(max(0, size - 131072))
                tail = stream.read().decode("utf-8", errors="ignore")
            tail_lines = tail.splitlines()[-log_tail_lines:]
            lines.extend(tail_lines if tail_lines else "(arquivo vazio)")
        except OSError as exc:
            lines.append(f"(não foi possível ler: {exc})")
    return "\n".join(lines) + "\n"


def export_diagnostic_report(target: Path) -> dict:
    """Exporta o relatório: texto puro (.txt) ou .zip com config e histórico."""
    target = Path(target).expanduser()
    target.parent.mkdir(parents=True, exist_ok=True)
    report = build_diagnostic_text()
    if target.suffix.lower() == ".zip":
        with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as bundle:
            bundle.writestr("relatorio-diagnostico.txt", report)
            members = 1
            config = core.load_config()
            if config:
                bundle.writestr(
                    "config.json", json.dumps(config, ensure_ascii=False, indent=2)
                )
                members += 1
            history = core.history_path()
            if history.is_file():
                bundle.write(history, "history.jsonl")
                members += 1
        return {"path": str(target), "zip": True, "members": members}
    target.write_text(report, encoding="utf-8")
    return {"path": str(target), "zip": False, "members": 1}


# ------------------------------------------------------------ central de ajuda
HELP_SHORTCUTS: tuple[tuple[str, str], ...] = (
    ("<Ctrl>F", "Foca a busca de perfis"),
    ("<Ctrl>Enter", "Aplica o perfil selecionado"),
    ("<Ctrl>Z", "Restaura o último backup do shader"),
    ("<Ctrl>?", "Abre esta central de ajuda"),
    ("<Ctrl><Alt>L", "Cicla para o próximo perfil em qualquer app (quando o "
        "atalho global está ativado na aba Perfis; o pedido aparece no portal "
        "do sistema na primeira vez)"),
)

HELP_GLOSSARY: tuple[tuple[str, str], ...] = (
    ("LUT", "Tabela de cores (Look-Up Table) que transforma as cores da tela; "
        "cada perfil do aplicativo usa uma LUT do atlas."),
    ("Atlas", "Textura MultiLut_Insurgency_Optimized.png com 32 fatias x 17 "
        "linhas de LUT; o shader escolhe a linha pelo perfil ativo."),
    ("Perfil", "Efeito pré-ajustado (perfis utilitários 0-16 e perfis por mapa "
        "17-24). O perfil ativo fica gravado no shader .fx."),
    ("vkBasalt", "Camada Vulkan de pós-processamento; precisa de "
        "ENABLE_VKBASALT=1 na opção de inicialização do jogo."),
    ("Opção de inicialização", "Comandos que o Steam adiciona ao abrir o jogo "
        "(%command% ENABLE_VKBASALT=1 -condebug); o app verifica e corrige "
        "pela aba Sistema."),
    ("-condebug", "Flag do jogo que grava o console.log na pasta do jogo; é o "
        "que permite ao piloto saber qual mapa carregou."),
    ("console.log", "Registro do console do jogo (pasta raiz da instalação); "
        "as linhas 'Map: <mapa>' revelam o mapa carregado."),
    ("Piloto automático", "Monitor do console.log que aplica o perfil do mapa "
        "assim que ele é carregado; funciona na janela aberta ou pelo daemon."),
    ("Daemon", "Piloto rodando como serviço de usuário (systemd), sem janela; "
        "a interface e a CLI apenas o controlam (multilut-ctl daemon)."),
    ("Backup do shader", "Cópia .multilut-backup do .fx criada a cada troca; "
        "Ctrl+Z restaura a anterior."),
)

HELP_TROUBLESHOOTING: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("O piloto não troca o LUT quando o mapa carrega", (
        "Confira se a opção 'Trocar perfil conforme o mapa' está ligada.",
        "Confira -condebug na opção de inicialização (aba Sistema corrigirá).",
        "Abra a aba Sistema: o item 'Piloto automático por mapa' precisa estar ok.",
        "Só mapas com perfil próprio disparam troca (Market, Ministry, Peak, "
        "Revolt, Siege, Tell, Uprising, Kandagal, Sinjar, Buhriz, Panj, "
        "Verticality, Heights, Dry Canal...); mapas sem perfil são ignorados.",
        "Com o daemon ativo, a janela não precisa estar aberta; veja "
        "'multilut-ctl daemon status'.",
    )),
    ("console.log não encontrado", (
        "Adicione -condebug à opção de inicialização do jogo (aba Sistema "
        "faz isso com o Steam fechado).",
        "Confirme a instalação do jogo detectada na aba Sistema.",
        "O arquivo só aparece depois do primeiro boot do jogo com a flag.",
    )),
    ("Shader não localizado ou incompatível", (
        "Use 'Instalar/atualizar pacote' na aba Perfis (copia o pacote v1.8).",
        "Confira o caminho em ~/.config/vkBasalt/reshade-shaders/Shaders/.",
        "Ctrl+Z restaura o último backup se uma troca recente deu errado.",
    )),
    ("Atlas com geometria inesperada", (
        "O atlas precisa ter exatamente 1024x544 (32 fatias x 17 linhas).",
        "Na aba Atlas use 'Restaurar pacote' para voltar ao PNG oficial.",
    )),
    ("Simulação de LUT indisponível", (
        "Instale os pacotes opcionais: sudo eopkg it numpy python-pillow.",
        "Depois reabra o aplicativo; os demais recursos não dependem disso.",
    )),
    ("Duas trocas acontecem em sequência (janela e daemon)", (
        "Isso não deve ocorrer: quando o daemon está ativo, a janela fica "
        "em modo observador. Se acontecer, pare o daemon "
        "(multilut-ctl daemon stop) e informe o caso em uma issue.",
    )),
)
