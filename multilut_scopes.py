#!/usr/bin/env python3
"""Ampliação das lunetas do Insurgency (2014) via theaters nativos.

O Insurgency define armas e acessórios em arquivos "theater" (KeyValues)
em insurgency/scripts/theaters. Um theater customizado apontado por
mp_theater_override substitui o padrão quando você hospeda a partida —
é o mecanismo oficial do jogo: nenhum VPK é alterado e desfazer é só
remover o arquivo gerado.

A ampliação efetiva de cada luneta vem de fov_wpn_scope, dentro do bloco
optics_fov_override do upgrade da óptica: quanto MENOR o FOV, maior o
zoom. O jogo rotula a luneta de FOV 10 como "7x" (base nominal 70), e a
conversão para uma ampliação alvo é:

    novo_fov = fov_atual * (ampliacao_atual / ampliacao_alvo)

Dados extraídos do dump 2.4.2.4 do jogo (base_weapon_upgrades /
default_weapon_upgrades.theater).
"""

from __future__ import annotations

from pathlib import Path
import os
import re
import subprocess

from multilut_core import MultiLUTError, _atomic_write


NOMINAL_BASE = 7.0                # luneta 7x tem fov_wpn_scope = 10 (70/10)
MAX_TARGET = 12.0                 # limite pedido pelo usuário
MIN_TARGET = 1.0
QUICK_TARGETS = (3.0, 5.0, 10.0, 12.0)  # opções rápidas de ampliação
THEATER_NAME = "multilut_zoom"
AUTOEXEC_BEGIN = "// >>> MultiLUT Controller - lunetas ampliadas >>>"
AUTOEXEC_END = "// <<< MultiLUT Controller - lunetas ampliadas <<<"
AUTOEXEC_LINE = f'mp_theater_override "{THEATER_NAME}"'

# Ativação por cfg/listenserver.cfg: o Insurgency executa esse arquivo ao
# iniciar QUALQUER partida hospedada localmente (o modo solo também — é um
# servidor local) ANTES de escolher o theater. Em instalações limpas o
# arquivo nem existe — o console do jogo mostra "exec: couldn't exec
# listenserver.cfg" — então criá-lo é seguro e é a ativação mais confiável:
# vale já na próxima partida, sem depender do Steam, do autoexec.cfg ou de
# comandos manuais no console.
LISTENSERVER_LINE = f'mp_theater_override "{THEATER_NAME}"'

STEAM_APP_ID = "222880"           # Insurgency na Steam
LAUNCH_OPTION = f"+mp_theater_override {THEATER_NAME}"

STEAM_ROOTS = (
    "~/.local/share/Steam",
    "~/.steam/steam",
    "~/.steam/root",
    "~/.steam/debian-installation",
    "~/.var/app/com.valvesoftware.Steam/.local/share/Steam",
)

# Subpastas típicas de um jogo Source; servem para reconhecer a instalação
# mesmo quando o conteúdo está empacotado em VPK (sem scripts/ solto no disco).
GAME_DIR_MARKERS = ("scripts", "maps", "cfg", "materials", "models", "sound")

# (id, rótulo, fov_wpn_scope, fov_wpn_ironsight, fov_wpn_focus, ampliação nominal)
SCOPED_OPTICS: tuple[tuple[str, str, float, float, float, float], ...] = (
    ("optic_scope_7x", "Luneta 7x (Mosin, FAL, SKS)", 10.0, 37.0, 43.0, 7.0),
    ("optic_scope_mk4", "Luneta MK4 (M40A1, M14, M16A4)", 10.0, 46.0, 50.0, 7.0),
    ("optic_po4x24", "PO 4x24 (AKM, FAL, Galil, Mosin)", 12.0, 39.0, 39.0, 4.0),
    ("optic_elcan", "Elcan (armas Security)", 14.0, 56.0, 64.0, 4.0),
    ("optic_2xaimpoint", "Aimpoint 2x (todos os fuzis)", 16.0, 39.0, 39.0, 2.0),
)
OPTIC_BY_ID = {item[0]: item for item in SCOPED_OPTICS}
DEFAULT_OPTICS = ("optic_scope_7x", "optic_scope_mk4")

# No dump oficial, algumas ópticas definem fov_wpn_scope DENTRO de sub-blocos
# por arma ("weapon_mosin" etc.) dentro de optics_fov_override. No merge do
# theater esses valores por arma vencem o de nível superior — o override só
# no topo não muda nada para elas (bug da 1ª versão: 7x e MK4 sem efeito).
# Só 7x e MK4 definem fov_wpn_scope por arma; nas demais os sub-blocos
# trazem apenas ironsight/focus e o valor de nível superior vale.
OPTIC_WEAPON_FOVS: dict[str, tuple[tuple[str, float], ...]] = {
    "optic_scope_7x": (
        ("weapon_mosin", 10.0),
        ("weapon_fal", 10.0),
        ("weapon_l1a1", 10.0),
        ("weapon_sks", 10.0),
    ),
    "optic_scope_mk4": (
        ("weapon_m40a1", 10.0),
        ("weapon_m14", 10.0),
        ("weapon_m16a4", 10.0),
    ),
}

# Encadeamento idêntico ao default.theater do jogo: o override precisa
# carregar as mesmas bases para não perder player/gear/armas.
THEATER_BASE_CHAIN: tuple[str, ...] = (
    "base_player.theater",
    "base_common_ammo.theater",
    "default_gear.theater",
    "default_weapon.theater",
    "default_weapon_upgrades.theater",
    "default_base.theater",
)


def normalize_scope_config(raw: dict | None) -> dict:
    """Valida e limita as configurações das lunetas, retornando dados seguros."""
    result = {
        "target": MAX_TARGET,
        "optics": list(DEFAULT_OPTICS),
        "autoexec": True,
        "launch_option": True,
        "game_dir": None,
    }
    if not isinstance(raw, dict):
        return result
    try:
        target = float(raw.get("target"))
    except (TypeError, ValueError):
        target = result["target"]
    if target != target or target in (float("inf"), float("-inf")):
        target = result["target"]
    result["target"] = max(MIN_TARGET, min(MAX_TARGET, target))
    optics = raw.get("optics")
    if isinstance(optics, (list, tuple)):
        valid = [item for item in optics if item in OPTIC_BY_ID]
        if valid:
            result["optics"] = valid
    result["autoexec"] = bool(raw.get("autoexec", True))
    result["launch_option"] = bool(raw.get("launch_option", True))
    game_dir = raw.get("game_dir")
    if isinstance(game_dir, str) and game_dir.strip():
        result["game_dir"] = game_dir.strip()
    return result


def compute_scope_fov(current_fov: float, current_mag: float, target_mag: float) -> float:
    """FOV que produz a ampliação alvo a partir do FOV/ampliação atuais."""
    try:
        fov = float(current_fov)
        mag = float(current_mag)
        target = float(target_mag)
    except (TypeError, ValueError):
        raise MultiLUTError("Valores de FOV ou ampliação inválidos.") from None
    if fov <= 0 or mag <= 0:
        raise MultiLUTError("FOV e ampliação atuais precisam ser positivos.")
    if not MIN_TARGET <= target <= MAX_TARGET:
        raise MultiLUTError(
            f"A ampliação alvo precisa estar entre {MIN_TARGET:.0f}x e {MAX_TARGET:.0f}x."
        )
    return round(fov * (mag / target), 2)


def build_theater(target_mag: float, optic_ids: list[str] | tuple[str, ...]) -> str:
    """Gera o conteúdo do theater com as lunetas ampliadas."""
    try:
        target = float(target_mag)
    except (TypeError, ValueError):
        raise MultiLUTError("Ampliação alvo inválida.") from None
    if not MIN_TARGET <= target <= MAX_TARGET:
        raise MultiLUTError(
            f"A ampliação alvo precisa estar entre {MIN_TARGET:.0f}x e {MAX_TARGET:.0f}x."
        )
    if not optic_ids:
        raise MultiLUTError("Selecione pelo menos uma luneta para ampliar.")
    unknown = [item for item in optic_ids if item not in OPTIC_BY_ID]
    if unknown:
        raise MultiLUTError("Luneta desconhecida: " + ", ".join(sorted(unknown)))

    lines: list[str] = [
        "// MultiLUT Controller - lunetas ampliadas (gerado automaticamente)",
        f"// Ampliacao alvo: {target:g}x nominal",
        "// Desfaca removendo este arquivo ou pelo botao Restaurar do aplicativo.",
        "",
    ]
    for base in THEATER_BASE_CHAIN:
        lines.append(f'"#base" "{base}"')
    lines += ["", '"theater"', "{", "\t\"weapon_upgrades\"", "\t{"]
    for optic_id in optic_ids:
        _name, _label, scope, ironsight, focus, mag = OPTIC_BY_ID[optic_id]
        new_scope = _format_fov(compute_scope_fov(scope, mag, target))
        lines += [
            f'\t\t"{optic_id}"',
            "\t\t{",
            "\t\t\t\"optics_fov_override\"",
            "\t\t\t{",
            f'\t\t\t\t"fov_wpn_scope"\t\t\t\t"{new_scope}"',
            f'\t\t\t\t"fov_wpn_ironsight"\t\t\t"{_format_fov(ironsight)}"',
            f'\t\t\t\t"fov_wpn_focus"\t\t\t\t"{_format_fov(focus)}"',
        ]
        # Armas com fov_wpn_scope próprio no dump: sem isto o jogo ignora
        # o valor de nível superior e a luneta fica sem ampliação extra.
        for weapon_id, weapon_fov in OPTIC_WEAPON_FOVS.get(optic_id, ()):
            weapon_zoom = _format_fov(compute_scope_fov(weapon_fov, mag, target))
            lines += [
                "",
                f'\t\t\t\t"{weapon_id}"',
                "\t\t\t\t{",
                f'\t\t\t\t\t"fov_wpn_scope"\t\t\t\t"{weapon_zoom}"',
                "\t\t\t\t}",
            ]
        lines += [
            "\t\t\t}",
            "\t\t}",
            "",
        ]
    lines += ["\t}", "}"]
    return "\n".join(lines) + "\n"


def _format_fov(value: float) -> str:
    if float(value).is_integer():
        return str(int(value))
    return f"{value:.2f}"


def theater_path(game_dir: Path | str) -> Path:
    return Path(game_dir) / "scripts" / "theaters" / f"{THEATER_NAME}.theater"


def looks_like_game_dir(path: Path | str) -> bool:
    """Reconhece a pasta do jogo por marcadores do Source, sem exigir scripts/.

    Aceita quando a pasta tem ao menos duas das subpastas típicas do jogo
    (maps, cfg, materials…) ou quando se chama "insurgency" — o nome padrão
    da pasta do jogo dentro de insurgency2.
    """
    candidate = Path(path)
    if not candidate.is_dir():
        return False
    markers = sum(1 for item in GAME_DIR_MARKERS if (candidate / item).is_dir())
    return markers >= 2 or candidate.name.casefold() == "insurgency"


def find_game_dir_above(path: Path | str, max_levels: int = 5) -> Path | None:
    """Se o caminho está DENTRO da pasta do jogo, devolve a pasta do jogo.

    Útil quando o usuário aponta para uma subpasta como
    insurgency/download/scripts — a pasta do jogo fica alguns níveis acima.
    """
    current = Path(path)
    for _ in range(max_levels):
        current = current.parent
        if looks_like_game_dir(current):
            return current
    return None


def _validate_game_dir(game_dir: Path | str) -> Path:
    path = Path(game_dir)
    if not path.is_dir():
        raise MultiLUTError(f"A pasta do jogo não existe: {path}")
    if not looks_like_game_dir(path):
        raise MultiLUTError(
            "A pasta informada não parece ser a instalação do Insurgency: "
            "não encontrei as subpastas típicas do jogo (maps, cfg, scripts…)."
        )
    return path


def is_applied(game_dir: Path | str) -> bool:
    return theater_path(game_dir).is_file()


def applied_target(game_dir: Path | str) -> float | None:
    """Ampliação gravada no theater atual (None se não aplicado)."""
    path = theater_path(game_dir)
    if not path.is_file():
        return None
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    match = re.search(r"Ampliacao alvo:\s*([0-9.]+)x", text)
    if not match:
        return None
    try:
        return float(match.group(1))
    except ValueError:
        return None


def apply_zoom(game_dir: Path | str, target_mag: float,
               optic_ids: list[str] | tuple[str, ...]) -> Path:
    """Grava o theater com as lunetas ampliadas (gravação atômica)."""
    path = _validate_game_dir(game_dir)
    text = build_theater(target_mag, optic_ids)
    target = theater_path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    mode = target.stat().st_mode & 0o777 if target.exists() else 0o644
    _atomic_write(target, text, mode)
    return target


def revert_zoom(game_dir: Path | str) -> bool:
    """Remove o theater e as linhas de ativação. True se algo mudou."""
    path = _validate_game_dir(game_dir)
    changed = False
    target = theater_path(path)
    if target.is_file():
        try:
            target.unlink()
            changed = True
        except OSError as exc:
            raise MultiLUTError(f"Não foi possível remover o theater: {exc}") from exc
    if autoexec_zoom_enabled(path):
        set_autoexec_zoom(path, False)
        changed = True
    if listenserver_zoom_enabled(path):
        set_listenserver_zoom(path, False)
        changed = True
    return changed


def autoexec_path(game_dir: Path | str) -> Path:
    return Path(game_dir) / "cfg" / "autoexec.cfg"


def _read_autoexec(game_dir: Path | str) -> tuple[Path, str, int]:
    path = autoexec_path(game_dir)
    if not path.is_file():
        return path, "", 0o644
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
        mode = path.stat().st_mode & 0o777
    except OSError as exc:
        raise MultiLUTError(f"Não foi possível ler o autoexec.cfg: {exc}") from exc
    return path, text, mode


def autoexec_zoom_enabled(game_dir: Path | str) -> bool:
    _path, text, _mode = _read_autoexec(game_dir)
    return AUTOEXEC_BEGIN in text and AUTOEXEC_LINE in text


def _write_marked_block(path: Path, line: str, enabled: bool) -> bool:
    """Adiciona ou remove um bloco marcado com `line` no arquivo `path`.

    O restante do arquivo é preservado. Ao desativar, se o arquivo ficar
    vazio (era um arquivo criado por nós), ele é removido do disco.
    Devolve True se o arquivo mudou.
    """
    if path.is_file():
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
            mode = path.stat().st_mode & 0o777
        except OSError as exc:
            raise MultiLUTError(f"Não foi possível ler {path.name}: {exc}") from exc
    else:
        text, mode = "", 0o644
    pattern = re.compile(
        re.escape(AUTOEXEC_BEGIN) + r".*?" + re.escape(AUTOEXEC_END) + r"\n?",
        re.DOTALL,
    )
    cleaned = pattern.sub("", text).rstrip("\n")
    if enabled:
        block = f"{AUTOEXEC_BEGIN}\n{line}\n{AUTOEXEC_END}\n"
        new_text = (cleaned + "\n\n" + block) if cleaned else block
    else:
        new_text = cleaned + "\n" if cleaned else ""
    if new_text == text:
        return False
    if new_text:
        path.parent.mkdir(parents=True, exist_ok=True)
        _atomic_write(path, new_text, mode)
    else:
        try:
            path.unlink()
        except OSError:
            pass
    return True


def set_autoexec_zoom(game_dir: Path | str, enabled: bool) -> Path:
    """Adiciona ou remove o bloco marcado no autoexec.cfg do jogo."""
    path = autoexec_path(game_dir)
    _write_marked_block(path, AUTOEXEC_LINE, enabled)
    return path


# --- Ativação por partida local (cfg/listenserver.cfg) -----------------------

def listenserver_path(game_dir: Path | str) -> Path:
    return Path(game_dir) / "cfg" / "listenserver.cfg"


def listenserver_zoom_enabled(game_dir: Path | str) -> bool:
    """True se o listenserver.cfg já ativa o theater nas partidas locais."""
    path = listenserver_path(game_dir)
    if not path.is_file():
        return False
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False
    return AUTOEXEC_BEGIN in text and LISTENSERVER_LINE in text


def set_listenserver_zoom(game_dir: Path | str, enabled: bool) -> Path:
    """Ativa o theater nas partidas locais via cfg/listenserver.cfg.

    O jogo executa este arquivo no início de qualquer partida hospedada
    por você (o modo solo incluído) e ANTES de escolher o theater — é o
    gatilho que aparece no console como "Executing 'listenserver.cfg'".
    Diferente do autoexec.cfg, isso funciona em todas as instalações e
    dispensa reiniciar o jogo: a ativação vale na próxima partida.
    """
    path = listenserver_path(game_dir)
    _write_marked_block(path, LISTENSERVER_LINE, enabled)
    return path


# --- Opção de inicialização do Steam (+mp_theater_override) -----------------
#
# O autoexec.cfg do Insurgency (2014) é executado de forma pouco confiável
# (há relatos antigos e guias que mandam usar "-exec autoexec.cfg"), e o cvar
# mp_theater_override não é ARCHIVE, ou seja, não persiste no config.cfg.
# O caminho canônico e garantido é a opção de inicialização do jogo na Steam:
# +mp_theater_override multilut_zoom — vale para coop e PvP hospedados localmente.

_LAUNCH_PAIR = re.compile(r"\+mp_theater_override\s+\S+")


def steam_running() -> bool:
    """True se houver processo do Steam ativo (ele regravaria localconfig.vdf)."""
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


def localconfig_candidates(
    roots: list[Path | str] | None = None,
) -> list[Path]:
    """Arquivos localconfig.vdf do Steam (principal + userdata), sem duplicatas."""
    if roots is None:
        roots = []
        for pattern in STEAM_ROOTS:
            expanded = Path(os.path.expanduser(pattern))
            if expanded.is_dir():
                roots.append(expanded)
    files: list[Path] = []
    seen: set[Path] = set()
    for root in roots:
        root = Path(root)
        candidates = [root / "config" / "localconfig.vdf"]
        userdata = root / "userdata"
        if userdata.is_dir():
            candidates.extend(sorted(userdata.glob("*/config/localconfig.vdf")))
        for path in candidates:
            try:
                resolved = path.resolve()
            except OSError:
                resolved = path
            if resolved in seen:
                continue
            seen.add(resolved)
            files.append(path)
    return files


def _app_block_span(text: str, app_id: str) -> tuple[int, int] | None:
    """Localiza o bloco VDF do app: devolve (índice do '{', índice do '}')."""
    key = f'"{app_id}"'
    search_from = 0
    while True:
        idx = text.find(key, search_from)
        if idx == -1:
            return None
        search_from = idx + len(key)
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


def _patch_launch_options_text(text: str, enable: bool) -> tuple[str, bool]:
    """Adiciona/remove a opção de inicialização no texto do localconfig.vdf."""
    span = _app_block_span(text, STEAM_APP_ID)
    if span is None:
        return text, False
    start, end = span
    block = text[start:end + 1]
    match = re.search(r'"LaunchOptions"\s+"([^"]*)"', block)
    if match:
        value = match.group(1)
        if enable:
            if _LAUNCH_PAIR.search(value):
                new_value = _LAUNCH_PAIR.sub(LAUNCH_OPTION, value, count=1)
            else:
                new_value = f"{value} {LAUNCH_OPTION}".strip()
        else:
            new_value = _LAUNCH_PAIR.sub("", value).strip()
        if new_value == value:
            return text, False
        replacement = f'"LaunchOptions"\t\t"{new_value}"'
        new_block = block.replace(match.group(0), replacement, 1)
        return text[:start] + new_block + text[end + 1:], True
    if not enable:
        return text, False
    insertion = f'\n\t\t"LaunchOptions"\t\t"{LAUNCH_OPTION}"'
    new_block = block[:1] + insertion + block[1:]
    return text[:start] + new_block + text[end + 1:], True


def _launch_option_in_text(text: str) -> bool:
    span = _app_block_span(text, STEAM_APP_ID)
    if span is None:
        return False
    block = text[span[0]:span[1] + 1]
    match = re.search(r'"LaunchOptions"\s+"([^"]*)"', block)
    if not match:
        return False
    return bool(re.search(r"\+mp_theater_override\s+multilut_zoom\b", match.group(1)))


def launch_option_installed(roots: list[Path | str] | None = None) -> bool:
    """True se algum localconfig.vdf já inicia o jogo com o theater ampliado."""
    for path in localconfig_candidates(roots):
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if _launch_option_in_text(text):
            return True
    return False


def set_launch_option(
    enable: bool, roots: list[Path | str] | None = None
) -> list[Path]:
    """Grava ou remove a opção de inicialização do Insurgency na Steam.

    Retorna a lista de arquivos alterados. Exige o Steam fechado: com o
    Steam aberto a configuração fica em memória e seria regravada sem a opção.
    """
    if steam_running():
        raise MultiLUTError(
            "o Steam está aberto e regravaria a configuração — "
            "feche o Steam e clique em Ativar novamente"
        )
    candidates = localconfig_candidates(roots)
    if enable and not candidates:
        raise MultiLUTError(
            "não encontrei os arquivos de configuração do Steam (localconfig.vdf)"
        )
    changed_paths: list[Path] = []
    for path in candidates:
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
            mode = path.stat().st_mode & 0o777
        except OSError:
            continue
        new_text, changed = _patch_launch_options_text(text, enable)
        if not changed:
            continue
        backup = path.with_name(path.name + ".multilut.bak")
        if not backup.exists():
            try:
                backup.write_text(text, encoding="utf-8")
            except OSError:
                pass
        try:
            _atomic_write(path, new_text, mode)
        except OSError as exc:
            raise MultiLUTError(
                f"não foi possível gravar {path}: {exc}"
            ) from exc
        changed_paths.append(path)
    return changed_paths


def find_game_dirs(roots: list[Path | str] | None = None) -> list[Path]:
    """Procura instalações do Insurgency nas bibliotecas Steam conhecidas."""
    if roots is None:
        roots = []
        for pattern in STEAM_ROOTS:
            expanded = Path(os.path.expanduser(pattern))
            if expanded.is_dir():
                roots.append(expanded)
    libraries: list[Path] = []
    for root in roots:
        root = Path(root)
        if root not in libraries:
            libraries.append(root)
        vdf = root / "steamapps" / "libraryfolders.vdf"
        if vdf.is_file():
            try:
                text = vdf.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            for match in re.finditer(r'"path"\s+"([^"]+)"', text):
                lib = Path(match.group(1).replace("\\\\", "/"))
                if lib.is_dir() and lib not in libraries:
                    libraries.append(lib)
    found: list[Path] = []
    for lib in libraries:
        candidate = lib / "steamapps" / "common" / "insurgency2" / "insurgency"
        if looks_like_game_dir(candidate) and candidate not in found:
            found.append(candidate)
    return found
