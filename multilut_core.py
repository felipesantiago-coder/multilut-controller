#!/usr/bin/env python3
"""Safe file operations for MultiLUT Controller."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import hashlib
import json
import os
import struct
import re
import shutil
import subprocess
import tempfile
import unicodedata
import urllib.error
import urllib.request
from typing import Iterable


APP_ID = "com.felipesantiago.MultiLUTController"
APP_VERSION = "1.8.0"
RELEASES_API_URL = (
    "https://api.github.com/repos/felipesantiago-coder/multilut-controller/releases/latest"
)
STEAM_APP_ID = "222880"
PROFILE_PATTERN = re.compile(
    r"^(?P<indent>[ \t]*)#define[ \t]+ACTIVE_LUT_PROFILE[ \t]+"
    r"(?P<value>\d+)(?P<suffix>[ \t]*(?://[^\r\n]*)?)$",
    re.MULTILINE,
)


@dataclass(frozen=True)
class Profile:
    id: int
    name: str
    category: str
    summary: str
    best_for: str
    tone: str


PROFILES: tuple[Profile, ...] = (
    Profile(0, "Neutro / Referência", "Diagnóstico", "Desativa o tratamento para comparação direta.", "Verificar a imagem original e diagnosticar alterações.", "Neutro"),
    Profile(1, "Buhriz", "Mapa", "Protege céu e areia claros sem perder a sombra sob a ponte.", "Buhriz; terreno aberto e áreas sob estruturas.", "Claro controlado"),
    Profile(2, "Contact", "Mapa", "Controla paredes brancas e sol forte, preservando veículos e fachadas.", "Contact; ruas abertas e construções claras.", "Sol intenso"),
    Profile(3, "District", "Mapa", "Separa prédios, fumaça, ruas e detalhes urbanos distantes.", "District; combate urbano e observação de corredores.", "Urbano definido"),
    Profile(4, "Dry Canal", "Mapa", "Reduz haze quente e clipping sob iluminação extrema.", "Dry Canal; áreas abertas com forte dominante quente.", "Haze reduzido"),
    Profile(5, "Embassy", "Mapa", "Equilibra concreto claro, céu e sombras com neutralidade moderada.", "Embassy; fachadas, pátios e áreas institucionais.", "Urbano neutro"),
    Profile(6, "Heights", "Mapa", "Clareia sombras e médios, separando terreno e vegetação sem estourar a neve.", "Heights; neve, lama, árvores e construções.", "Neve clara protegida"),
    Profile(7, "Panj", "Mapa", "Recupera o ambiente escuro e vegetado preservando profundidade.", "Panj; vegetação densa e iluminação baixa.", "Sombras naturais"),
    Profile(8, "Sinjar", "Mapa", "Prioriza longa distância, relevo e textura da estrada.", "Sinjar; linhas longas e iluminação desértica.", "Longa distância"),
    Profile(9, "Station", "Mapa", "Eleva a iluminação industrial escura mantendo céu e neve protegidos.", "Station; áreas industriais, céu/neve e interiores.", "Iluminação ampla protegida"),
    Profile(10, "Verticality", "Mapa", "Clareia ruas e construções escuras sem estourar neve, céu ou pinheiros.", "Verticality; neve e corredores urbanos escuros.", "Neve luminosa protegida"),
    Profile(11, "Interior muito escuro", "Utilitário", "Máxima leitura de objetos e silhuetas em interiores.", "Qualquer mapa com iluminação interna extremamente baixa.", "Recuperação forte"),
    Profile(12, "Interior + exterior", "Utilitário", "Equilibra um interior escuro com portas ou janelas claras.", "Cenas de iluminação mista e transições internas/externas.", "Dinâmico misto"),
    Profile(13, "Longa distância / pouco haze", "Utilitário", "Aumenta microcontraste e reduz aparência de névoa.", "Sniper, montanhas, estradas e objetos pequenos distantes.", "Alcance máximo"),
    Profile(14, "Competitivo neutro", "Competitivo", "Equilíbrio geral entre naturalidade, visibilidade e contraste.", "Uso geral quando não quiser trocar o perfil por mapa.", "Equilibrado"),
    Profile(15, "Recuperação competitiva", "Competitivo", "Eleva sombras profundas com proteção de preto e contraste.", "Interiores e posições escondidas com pouca iluminação.", "Visibilidade máxima"),
    Profile(16, "Alto contraste competitivo", "Competitivo", "Reforça separação tonal em cenas planas ou enevoadas.", "Cenários com materiais visualmente próximos.", "Contraste forte"),
    Profile(17, "Market", "Mapa", "Equilibra ruas, lojas, sacadas e interiores urbanos sem névoa cinza.", "Market; combate urbano costeiro de curta e média distância.", "Urbano costeiro"),
    Profile(18, "Ministry", "Mapa", "Recupera corredores e salas mantendo concreto, portas e áreas iluminadas separados.", "Ministry; interiores extensos e transições entre corredores.", "Interior definido"),
    Profile(19, "Peak", "Mapa", "Aumenta leitura do relevo e da vegetação com microcontraste de longa distância.", "Peak; montanhas, árvores e linhas de visão abertas.", "Montanha nítida"),
    Profile(20, "Revolt", "Mapa", "Equilibra ruas claras, túneis e edifícios escuros sem lavar os pretos.", "Revolt; iluminação urbana mista e passagens subterrâneas.", "Urbano dinâmico"),
    Profile(21, "Siege", "Mapa", "Controla fachadas claras e sombras de rua na variante diurna do ambiente de Contact.", "Siege; ruas expostas, prédios claros e posições sombreadas.", "Dia urbano"),
    Profile(22, "Tell", "Mapa", "Protege paredes sob sol forte e recupera becos e interiores estreitos.", "Tell; cidade densa, combate próximo e contrastes extremos.", "Sol e becos"),
    Profile(23, "Uprising", "Mapa", "Reforça a separação de materiais em ruas estreitas sem criar uma camada cinza.", "Uprising; combate urbano de curta distância e interiores compactos.", "CQB contrastado"),
    Profile(24, "Kandagal", "Mapa", "Reduz o haze do vale preservando rio, vegetação, vila e profundidade.", "Kandagal; vale rural, ponte, cidade e linhas longas.", "Vale sem haze"),
)

PROFILE_BY_ID = {profile.id: profile for profile in PROFILES}


def _profile_sort_key(profile: Profile) -> str:
    """Chave alfabética sem acentos e insensível a maiúsculas."""
    decomposed = unicodedata.normalize("NFKD", profile.name)
    without_accents = "".join(
        char for char in decomposed if not unicodedata.combining(char)
    )
    return without_accents.casefold()


def profiles_alphabetical(
    profiles: Iterable[Profile] = PROFILES,
) -> tuple[Profile, ...]:
    """Perfis em ordem alfabética para exibição; os IDs não mudam."""
    return tuple(sorted(profiles, key=_profile_sort_key))


def profiles_by_section(
    profiles: Iterable[Profile] = PROFILES,
) -> tuple[tuple[str, tuple[Profile, ...]], ...]:
    """Perfis agrupados nas duas seções da interface, cada uma alfabética.

    "Efeitos de mapa" reúne os perfis criados para um mapa específico
    (categoria "Mapa"); "Efeitos utilitários" reúne os que valem em
    qualquer cenário — interiores, longa distância, competitivos e o
    neutro de referência.
    """
    ordered = tuple(sorted(profiles, key=_profile_sort_key))
    mapas = tuple(item for item in ordered if item.category == "Mapa")
    utilitarios = tuple(item for item in ordered if item.category != "Mapa")
    sections: list[tuple[str, tuple[Profile, ...]]] = []
    if mapas:
        sections.append(("Efeitos de mapa", mapas))
    if utilitarios:
        sections.append(("Efeitos utilitários", utilitarios))
    return tuple(sections)


def map_image_slug(profile: Profile) -> str | None:
    """Slug do arquivo de foto oficial do mapa para o perfil, ou None.

    As fotos vêm dos depots oficiais do jogo (materials/vgui/maps/
    <mapa>_large.vtf) e ficam em assets/maps/<slug>.jpg. Perfis que não
    são de mapa não têm foto própria.
    """
    if profile.category != "Mapa":
        return None
    decomposed = unicodedata.normalize("NFKD", profile.name)
    without_accents = "".join(
        char for char in decomposed if not unicodedata.combining(char)
    )
    slug = re.sub(r"[^a-z0-9]", "", without_accents.casefold())
    return slug or None


class MultiLUTError(RuntimeError):
    """A user-facing MultiLUT operation error."""


def default_shader_path() -> Path:
    return Path.home() / ".config/vkBasalt/reshade-shaders/Shaders/MultiLUT_Insurgency_Optimized.fx"


def default_texture_path() -> Path:
    return Path.home() / ".config/vkBasalt/reshade-shaders/Textures/MultiLut_Insurgency_Optimized.png"


def default_vkbasalt_config_path() -> Path:
    return Path.home() / ".config/vkBasalt/vkBasalt.conf"


def app_config_path() -> Path:
    return Path.home() / ".config/multilut-controller/config.json"


def app_state_dir() -> Path:
    """Estado do aplicativo (XDG_STATE_HOME), ex.: ~/.local/state/multilut-controller."""
    root = os.environ.get("XDG_STATE_HOME", "").strip()
    base = Path(root).expanduser() if root else Path.home() / ".local/state"
    return base / "multilut-controller"


def legacy_history_path() -> Path:
    """Caminho antigo do histórico (versões anteriores ao XDG_STATE_HOME)."""
    return Path.home() / ".config/multilut-controller/history.jsonl"


def history_path() -> Path:
    """Histórico local: XDG_STATE_HOME (o arquivo legado é migrado na 1ª escrita)."""
    return app_state_dir() / "history.jsonl"


def _migrate_legacy_history() -> Path:
    """Move o histórico legado de ~/.config para XDG_STATE_HOME (idempotente).

    Versões antigas gravavam em ~/.config/multilut-controller/history.jsonl;
    se o arquivo novo ainda não existir, o legado é movido inteiro. Se a
    movimentação falhar (sistema de arquivos), o legado continua sendo lido.
    """
    target = history_path()
    legacy = legacy_history_path()
    if not legacy.is_file() or target.exists():
        return target
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        legacy.replace(target)
    except OSError:
        pass
    return target if target.exists() else legacy


def _resolved_file(path: Path | str) -> Path:
    candidate = Path(path).expanduser()
    try:
        resolved = candidate.resolve(strict=True)
    except FileNotFoundError as exc:
        raise MultiLUTError(f"Arquivo não encontrado: {candidate}") from exc
    if not resolved.is_file():
        raise MultiLUTError(f"O caminho não é um arquivo: {resolved}")
    return resolved


def read_active_profile(path: Path | str) -> int:
    target = _resolved_file(path)
    text = target.read_text(encoding="utf-8")
    matches = list(PROFILE_PATTERN.finditer(text))
    if len(matches) != 1:
        raise MultiLUTError(
            "O shader precisa conter exatamente uma definição ACTIVE_LUT_PROFILE."
        )
    value = int(matches[0].group("value"))
    if value not in PROFILE_BY_ID:
        raise MultiLUTError(f"Perfil inválido encontrado no shader: {value}")
    return value


def validate_shader(path: Path | str) -> tuple[bool, str]:
    try:
        target = _resolved_file(path)
        text = target.read_text(encoding="utf-8")
        profile_id = read_active_profile(target)
    except (OSError, UnicodeError, MultiLUTError) as exc:
        return False, str(exc)
    required = (
        "MultiLut_Insurgency_Optimized.png",
        "technique MultiLUT",
        "fLUT_DeepShadowRecovery",
        "fLUT_SceneBrightness",
        "fLUT_ColorSeparation",
    )
    missing = [item for item in required if item not in text]
    if missing:
        return False, "Shader incompatível; itens ausentes: " + ", ".join(missing)
    return True, f"Shader válido; perfil ativo {profile_id}: {PROFILE_BY_ID[profile_id].name}"


def backup_path(path: Path | str) -> Path:
    target = Path(path).expanduser()
    return target.with_name(target.name + ".bak")


def _atomic_write(target: Path, content: str, mode: int) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{target.name}.", suffix=".tmp", dir=target.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, mode)
        os.replace(temporary, target)
    finally:
        if temporary.exists():
            temporary.unlink()


def set_active_profile(path: Path | str, profile_id: int, make_backup: bool = True) -> int:
    if profile_id not in PROFILE_BY_ID:
        raise MultiLUTError(f"Perfil fora do intervalo permitido: {profile_id}")
    target = _resolved_file(path)
    text = target.read_text(encoding="utf-8")
    matches = list(PROFILE_PATTERN.finditer(text))
    if len(matches) != 1:
        raise MultiLUTError(
            "Não foi possível localizar uma única definição ACTIVE_LUT_PROFILE."
        )
    previous = int(matches[0].group("value"))
    if previous == profile_id:
        return previous
    match = matches[0]
    replacement = (
        f"{match.group('indent')}#define ACTIVE_LUT_PROFILE {profile_id}"
        f"{match.group('suffix')}"
    )
    updated = text[: match.start()] + replacement + text[match.end() :]
    mode = target.stat().st_mode & 0o777
    if make_backup:
        shutil.copy2(target, backup_path(target))
    _atomic_write(target, updated, mode)
    confirmed = read_active_profile(target)
    if confirmed != profile_id:
        raise MultiLUTError("A verificação após a gravação não confirmou o perfil.")
    return previous


def restore_backup(path: Path | str) -> int:
    target = _resolved_file(path)
    backup = backup_path(target)
    if not backup.is_file():
        raise MultiLUTError("Nenhum backup está disponível para este shader.")
    valid, message = validate_shader(backup)
    if not valid:
        raise MultiLUTError(f"O backup não é válido: {message}")
    target.parent.mkdir(parents=True, exist_ok=True)
    mode = backup.stat().st_mode & 0o777
    _atomic_write(target, backup.read_text(encoding="utf-8"), mode)
    return read_active_profile(target)


def find_shader_candidates() -> list[Path]:
    candidates = (
        default_shader_path(),
        Path.home() / ".local/share/vkBasalt/reshade-shaders/Shaders/MultiLUT_Insurgency_Optimized.fx",
        Path.home() / "reshade-shaders/Shaders/MultiLUT_Insurgency_Optimized.fx",
    )
    return [path for path in candidates if path.is_file()]


def game_processes() -> list[str]:
    found: list[str] = []
    proc = Path("/proc")
    if not proc.is_dir():
        return found
    for entry in proc.iterdir():
        if not entry.name.isdigit():
            continue
        try:
            raw = (entry / "cmdline").read_bytes().replace(b"\x00", b" ")
            command = raw.decode("utf-8", errors="ignore").lower()
        except (OSError, PermissionError):
            continue
        if not command or "multilut_controller" in command:
            continue
        if "insurgency" in command or f"rungameid/{STEAM_APP_ID}" in command:
            found.append(command.strip())
    return found


def is_game_running() -> bool:
    return bool(game_processes())


def launch_game() -> None:
    try:
        subprocess.Popen(
            ["xdg-open", f"steam://rungameid/{STEAM_APP_ID}"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except OSError as exc:
        raise MultiLUTError("Não foi possível abrir o Steam.") from exc


def load_config() -> dict:
    path = app_config_path()
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeError):
        return {}
    return data if isinstance(data, dict) else {}


def save_config(data: dict) -> None:
    path = app_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    old_mode = path.stat().st_mode & 0o777 if path.exists() else 0o600
    _atomic_write(path, json.dumps(data, ensure_ascii=False, indent=2) + "\n", old_mode)


def copy_bundle_assets(bundle_root: Path | str) -> tuple[Path, Path]:
    root = Path(bundle_root)
    source_shader = root / "Shaders/MultiLUT_Insurgency_Optimized.fx"
    source_texture = root / "Textures/MultiLut_Insurgency_Optimized.png"
    if not source_shader.is_file() or not source_texture.is_file():
        raise MultiLUTError("O pacote interno do MultiLUT está incompleto.")
    valid, message = validate_shader(source_shader)
    if not valid:
        raise MultiLUTError(f"O shader interno não passou na validação: {message}")
    target_shader = default_shader_path()
    target_texture = default_texture_path()
    target_shader.parent.mkdir(parents=True, exist_ok=True)
    target_texture.parent.mkdir(parents=True, exist_ok=True)
    for source, target in ((source_shader, target_shader), (source_texture, target_texture)):
        if target.exists():
            shutil.copy2(target, backup_path(target))
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{target.name}.", suffix=".tmp", dir=target.parent
        )
        os.close(descriptor)
        temporary = Path(temporary_name)
        try:
            shutil.copy2(source, temporary)
            os.replace(temporary, target)
        finally:
            if temporary.exists():
                temporary.unlink()
    return target_shader, target_texture


def profile_names(profiles: Iterable[Profile] = PROFILES) -> list[str]:
    return [f"{profile.id:02d} — {profile.name}" for profile in profiles]


# ------------------------------------------------------------ histórico de sessões
def append_history(entry: dict) -> None:
    """Registra um evento (perfil aplicado) no histórico local (JSONL)."""
    path = _migrate_legacy_history()
    path.parent.mkdir(parents=True, exist_ok=True)
    record = dict(entry)
    record.setdefault(
        "ts", datetime.now(timezone.utc).isoformat(timespec="seconds")
    )
    try:
        with path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(record, ensure_ascii=False) + "\n")
    except OSError:
        return
    _trim_history(path)


def _trim_history(path: Path, keep: int = 1000, max_lines: int = 2000) -> None:
    """Mantém o histórico enxuto: acima de max_lines, guarda as últimas keep."""
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return
    if len(lines) <= max_lines:
        return
    content = "\n".join(lines[-keep:]) + "\n"
    try:
        _atomic_write(path, content, 0o600)
    except OSError:
        pass


def read_history(limit: int = 100) -> list[dict]:
    """Entradas mais recentes primeiro (mais novas no fim da leitura)."""
    path = _migrate_legacy_history()
    if not path.is_file():
        return []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    entries: list[dict] = []
    for line in reversed(lines):
        line = line.strip()
        if not line:
            continue
        try:
            data = json.loads(line)
        except ValueError:
            continue
        if isinstance(data, dict):
            entries.append(data)
            if len(entries) >= limit:
                break
    return entries


def clear_history() -> None:
    try:
        _migrate_legacy_history().unlink()
    except FileNotFoundError:
        return
    except OSError:
        return


# ------------------------------------------------------------ atualizações
def normalize_version(tag: str) -> tuple[int, ...] | None:
    """"v1.10.2", "1.9" etc. viram tupla comparável; None se não houver dígitos."""
    text = str(tag).strip().casefold().lstrip("v")
    numbers: list[int] = []
    for part in re.split(r"[.\-+]", text):
        if part.isdigit():
            numbers.append(int(part))
        else:
            digits = ""
            for char in part:
                if char.isdigit():
                    digits += char
                else:
                    break
            if digits:
                numbers.append(int(digits))
            elif numbers:
                break
    return tuple(numbers) if numbers else None


def compare_versions(candidate: str, current: str) -> bool:
    """True quando candidate é estritamente mais nova que current."""
    left = normalize_version(candidate)
    right = normalize_version(current)
    if left is None or right is None:
        return False
    width = max(len(left), len(right))
    left += (0,) * (width - len(left))
    right += (0,) * (width - len(right))
    return left > right


def fetch_latest_release(timeout: float = 6.0) -> dict | None:
    """Consulta a release mais recente no GitHub; None em qualquer falha."""
    request = urllib.request.Request(
        RELEASES_API_URL,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "MultiLUTController/" + APP_VERSION,
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            data = json.loads(response.read().decode("utf-8"))
    except (OSError, ValueError, urllib.error.URLError, UnicodeError):
        return None
    if not isinstance(data, dict) or not data.get("tag_name"):
        return None
    return {
        "tag": str(data["tag_name"]),
        "name": str(data.get("name") or data["tag_name"]),
        "url": str(data.get("html_url") or ""),
    }


# ------------------------------------------------------------ bibliotecas Steam
VDF_LIBRARY_PATH_PATTERN = re.compile(r'"path"[ \t]*"([^"]+)"')


def steam_roots() -> list[Path]:
    roots: list[Path] = []
    for candidate in (
        Path.home() / ".steam/steam",
        Path.home() / ".local/share/Steam",
    ):
        if candidate.is_dir() and candidate not in roots:
            roots.append(candidate)
    return roots


def steam_libraries() -> list[Path]:
    """Raízes de biblioteca: libraryfolders.vdf + as raízes padrão."""
    libraries: list[Path] = []
    for root in steam_roots():
        steamapps = root / "steamapps"
        if steamapps.is_dir() and steamapps not in libraries:
            libraries.append(steamapps)
        vdf = steamapps / "libraryfolders.vdf"
        if not vdf.is_file():
            continue
        try:
            text = vdf.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for match in VDF_LIBRARY_PATH_PATTERN.finditer(text):
            raw = match.group(1).replace("\\\\", "/")
            candidate = Path(raw)
            apps = candidate / "steamapps"
            if apps.is_dir() and apps not in libraries:
                libraries.append(apps)
    return libraries


def find_game_roots() -> list[Path]:
    """Instalações plausíveis do Insurgency (2014); a configurada vem primeiro.

    O jogo pode estar como <library>/steamapps/common/insurgency2/insurgency
    (layout aninhado), como .../common/insurgency ou .../common/insurgency2.
    """
    candidates: list[Path] = []
    configured = load_config().get("game_dir")
    if isinstance(configured, str) and configured.strip():
        candidates.append(Path(configured).expanduser())
    for apps in steam_libraries():
        common = apps / "common"
        candidates.append(common / "insurgency2/insurgency")
        candidates.append(common / "insurgency")
        candidates.append(common / "insurgency2")
    seen: set[Path] = set()
    roots: list[Path] = []
    for candidate in candidates:
        if candidate in seen:
            continue
        seen.add(candidate)
        try:
            if candidate.is_dir():
                roots.append(candidate)
        except OSError:
            continue
    return roots


def find_console_log() -> Path | None:
    """console.log do jogo (exige -condebug na opção de inicialização)."""
    for root in find_game_roots():
        candidate = root / "console.log"
        try:
            if candidate.is_file():
                return candidate
        except OSError:
            continue
    return None


# ------------------------------------------------------------ piloto automático por mapa
# Padrões de linha do console (Source engine) que revelam o mapa carregado.
# Formatos confirmados em logs reais: 'Loading map "xxx"' (servidor TF2/CS e
# cliente GoldSrc), 'Host_NewGame on map xxx' e 'Mapchange to xxx' (servidores
# Insurgency/Day of Infamy da NWI).
MAP_LINE_PATTERNS: tuple[re.Pattern, ...] = (
    re.compile(r'Loading map "([^"\s]+)"'),
    re.compile(r"Host_NewGame on map (\S+)"),
    re.compile(r"Mapchange to ([A-Za-z0-9_\-\[\]\.]+)"),
    re.compile(r"Host_Changelevel\s*\(\s*[^,()]+,\s*([^\s,()]+)"),
    re.compile(r"Loading map (\S+)"),
    re.compile(r"^\s*map\s+([A-Za-z0-9_\-\[\]\.]+)\s*$"),
)


def parse_map_token(line: str) -> str | None:
    """Token do mapa carregado em uma linha do console, ou None."""
    for pattern in MAP_LINE_PATTERNS:
        match = pattern.search(line)
        if match:
            return match.group(1)
    return None


def match_map_profile(token: str | None) -> Profile | None:
    """Perfil de mapa correspondente ao nome do mapa carregado, ou None.

    "market_coop" casa com Market, "sinjar_night" com Sinjar. O casamento é
    por partes do nome (hífen/underline/colchetes separam) e, em segundo
    lugar, por prefixo do token inteiro.
    """
    if not token:
        return None
    text = str(token).strip().strip('"').casefold()
    if not text:
        return None
    parts = [part for part in re.split(r"[^a-z0-9]+", text) if part]
    for profile in PROFILES:
        slug = map_image_slug(profile)
        if slug is not None and slug in parts:
            return profile
    for profile in PROFILES:
        slug = map_image_slug(profile)
        if slug is not None and text.startswith(slug):
            rest = text[len(slug) :]
            if not rest or not rest[0].isalnum():
                return profile
    return None


class ConsoleTail:
    """Leitor incremental de console.log por deslocamento de bytes.

    Guarda só a posição lida e o fragmento parcial da última linha; cada
    `feed` devolve as linhas completas novas. Suporta truncamento (o jogo
    recria o console.log a cada boot) via `reset`.
    """

    def __init__(self) -> None:
        self.offset = 0
        self._buffer = b""

    def reset(self) -> None:
        self.offset = 0
        self._buffer = b""

    def feed(self, data: bytes) -> list[str]:
        if not data:
            return []
        self.offset += len(data)
        self._buffer += data
        chunks = self._buffer.split(b"\n")
        self._buffer = chunks.pop()
        lines: list[str] = []
        for chunk in chunks:
            lines.append(chunk.decode("utf-8", errors="ignore").rstrip("\r"))
        return lines

    def map_tokens(self, lines: Iterable[str]) -> list[str]:
        tokens: list[str] = []
        for line in lines:
            token = parse_map_token(line)
            if token:
                tokens.append(token)
        return tokens


def next_profile_id(current: int, step: int = 1) -> int:
    """Próximo perfil na ordem dos ids (0 a 24, ciclando)."""
    if current not in PROFILE_BY_ID:
        raise MultiLUTError(f"Perfil fora do intervalo permitido: {current}")
    if step == 0:
        return current
    ids = sorted(PROFILE_BY_ID)
    index = ids.index(current)
    return ids[(index + step) % len(ids)]


# --- Atlas v1.8 e utilidades --------------------------------------------------
#
# O atlas MultiLut_Insurgency_Optimized.png tem 32 fatias azuis x 17 linhas
# de LUT, com fatias de 32x32 pixels (1024x544 no total). O shader escolhe a
# linha pela variável P_LUT_ROW; perfis 0..16 usam a linha igual ao próprio id
# e os perfis 17..24 reaproveitam a LUT-base mais próxima (mapeamento abaixo,
# extraído do próprio shader v1.8).

ATLAS_TILE = 32
ATLAS_SLICES = 32
ATLAS_ROWS = 17
ATLAS_SIZE = (ATLAS_SLICES * ATLAS_TILE, ATLAS_ROWS * ATLAS_TILE)  # 1024 x 544

LUT_ROW_BY_PROFILE: dict[int, int] = {
    17: 3,
    18: 12,
    19: 13,
    20: 5,
    21: 2,
    22: 1,
    23: 3,
    24: 13,
}


def lut_row_for_profile(profile_id: int) -> int:
    """Linha do atlas usada pelo perfil (P_LUT_ROW do shader v1.8)."""
    return LUT_ROW_BY_PROFILE.get(int(profile_id), int(profile_id))


def _png_dimensions(path: Path) -> tuple[int, int] | None:
    try:
        with open(path, "rb") as stream:
            header = stream.read(33)
    except OSError:
        return None
    if len(header) < 33 or header[:8] != b"\x89PNG\r\n\x1a\n" or header[12:16] != b"IHDR":
        return None
    width, height = struct.unpack(">II", header[16:24])
    return int(width), int(height)


def validate_texture(path: Path | str) -> tuple[bool, str]:
    """Confere se o atlas tem a geometria esperada do pacote v1.8."""
    target = Path(path)
    if not target.is_file():
        return False, f"Atlas não encontrado: {target}"
    dims = _png_dimensions(target)
    if dims is None:
        return False, "O atlas não é um PNG válido."
    if dims != ATLAS_SIZE:
        return False, (
            f"Atlas com geometria inesperada: {dims[0]}x{dims[1]} "
            f"(esperado {ATLAS_SIZE[0]}x{ATLAS_SIZE[1]})."
        )
    return True, (
        f"Atlas v1.8 válido ({dims[0]}x{dims[1]}, "
        f"{ATLAS_SLICES} fatias x {ATLAS_ROWS} linhas)."
    )


def file_hash(path: Path | str, algorithm: str = "sha256") -> str | None:
    """Hash hexadecimal do arquivo (None se não puder ser lido)."""
    try:
        digest = hashlib.new(algorithm)
        with open(path, "rb") as stream:
            for chunk in iter(lambda: stream.read(256 * 1024), b""):
                digest.update(chunk)
    except (OSError, ValueError):
        return None
    return digest.hexdigest()
