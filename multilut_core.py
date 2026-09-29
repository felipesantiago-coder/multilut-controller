#!/usr/bin/env python3
"""Safe file operations for MultiLUT Controller."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import json
import os
import re
import shutil
import subprocess
import tempfile
import unicodedata
from typing import Iterable


APP_ID = "com.felipesantiago.MultiLUTController"
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
