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
import tarfile
import tempfile
import unicodedata
import urllib.error
import urllib.request
from typing import Iterable


APP_ID = "com.felipesantiago.MultiLUTController"
APP_VERSION = "1.9.1"
REPO_OWNER = "felipesantiago-coder"
REPO_NAME = "multilut-controller"
REPO_URL = f"https://github.com/{REPO_OWNER}/{REPO_NAME}"
RELEASES_API_URL = f"{REPO_URL}/releases/latest"
COMMITS_API_URL = f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/commits/main"
TARBALL_URL = f"https://github.com/{REPO_OWNER}/{REPO_NAME}/archive/refs/heads/main.tar.gz"
RAW_CORE_URL = f"https://raw.githubusercontent.com/{REPO_OWNER}/{REPO_NAME}/main/multilut_core.py"
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


def _http_get(url: str, timeout: float = 6.0) -> bytes | None:
    """GET simples com User-Agent do app; None em qualquer falha de rede."""
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "MultiLUTController/" + APP_VERSION},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.read()
    except (OSError, ValueError, urllib.error.URLError, UnicodeError):
        return None


def fetch_latest_release(timeout: float = 6.0) -> dict | None:
    """Consulta a release mais recente no GitHub; None quando não há release."""
    data = _http_get(RELEASES_API_URL, timeout=timeout)
    if data is None:
        return None
    try:
        payload = json.loads(data.decode("utf-8"))
    except (ValueError, UnicodeError):
        return None
    if not isinstance(payload, dict) or not payload.get("tag_name"):
        return None
    return {
        "tag": str(payload["tag_name"]),
        "name": str(payload.get("name") or payload["tag_name"]),
        "url": str(payload.get("html_url") or ""),
    }


def fetch_latest_commit(timeout: float = 6.0) -> dict | None:
    """Consulta o commit mais recente do main na API do GitHub.

    O repositório não publica releases, então o main é a fonte da verdade.
    Retorna {"sha", "date", "message"}; None em qualquer falha (inclusive
    404 de repositorio vazio e 403 de limite de requisicoes).
    """
    data = _http_get(COMMITS_API_URL, timeout=timeout)
    if data is None:
        return None
    try:
        payload = json.loads(data.decode("utf-8"))
    except (ValueError, UnicodeError):
        return None
    if not isinstance(payload, dict) or not payload.get("sha"):
        return None
    commit = payload.get("commit") or {}
    message = str(commit.get("message") or "").splitlines()[0] if commit else ""
    date = str(((commit.get("committer") or {}).get("date")) or "")
    return {"sha": str(payload["sha"]), "date": date, "message": message}


def fetch_remote_app_version(timeout: float = 6.0) -> str | None:
    """Lê APP_VERSION do multilut_core.py publicado no main (raw, sem API)."""
    data = _http_get(RAW_CORE_URL, timeout=timeout)
    if data is None:
        return None
    head = data[:8192].decode("utf-8", errors="ignore")
    match = re.search(r'^APP_VERSION\s*=\s*"([^"]+)"', head, re.MULTILINE)
    return match.group(1) if match else None


def installed_commit(repo: Path | None = None) -> str | None:
    """Commit de origem da instalação: HEAD do git ou o arquivo source_commit.

    Instalações feitas por install.sh gravam `source_commit` (quando a origem
    era um clone) e o próprio atualizador regrava o arquivo após cada
    atualização por tarball.
    """
    repo = repo or app_repo_dir()
    head = local_git_head(repo)
    if head is not None:
        return head
    marker = repo / "source_commit"
    try:
        text = marker.read_text(encoding="utf-8", errors="ignore").strip()
    except OSError:
        return None
    if not text:
        return None
    first = text.splitlines()[0].strip()
    return first or None


def app_repo_dir() -> Path:
    """Diretório do código do aplicativo (raiz do checkout quando via git)."""
    return Path(__file__).resolve().parent


def local_git_head(repo: Path | None = None) -> str | None:
    """SHA curto do HEAD local; None fora de um checkout git ou sem git."""
    repo = repo or app_repo_dir()
    try:
        out = subprocess.run(
            ["git", "-C", str(repo), "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            timeout=6.0,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if out.returncode != 0:
        return None
    return out.stdout.strip() or None


def git_remote_head(repo: Path | None = None, timeout: float = 10.0) -> str | None:
    """SHA do main no servidor (git ls-remote); None em qualquer falha.

    Usa o próprio git em vez da API do GitHub: sem limite de requisições e
    funciona atrás de proxies que já autorizam o remoto configurado.
    """
    repo = repo or app_repo_dir()
    try:
        out = subprocess.run(
            ["git", "-C", str(repo), "ls-remote", "origin", "refs/heads/main"],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if out.returncode != 0:
        return None
    for line in out.stdout.splitlines():
        sha, _, ref = line.partition("\t")
        if ref.strip() == "refs/heads/main" and sha.strip():
            return sha.strip()
    return None


# Intervalo da reverificação automática de atualizações (30 min): o app
# aplica sozinho o que vier do main, sem diálogo nem clique do usuário.
UPDATE_RECHECK_SECONDS = 1800

# Lock compartilhado entre janela e daemon: nunca puxar ao mesmo tempo
# (index.lock do git / trabalho dobrado). Um lock velho — processo que
# morreu no meio do pull — é roubado depois deste tempo sem movimento.
UPDATE_LOCK_STALE_SECONDS = 900


def update_lock_path() -> Path:
    """Arquivo de lock da atualização (no estado do app, fora do repositório)."""
    return app_state_dir() / "update.lock"


def acquire_update_lock() -> bool:
    """Reserva a atualização para este processo (O_CREAT|O_EXCL).

    Janela e daemon dividem o mesmo lock: quem chega primeiro aplica; o
    outro recebe False e fica para a próxima verificação. Lock velho é
    roubado após UPDATE_LOCK_STALE_SECONDS para nunca travar para sempre.
    """
    path = update_lock_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
    except OSError:
        return False
    for _ in range(2):
        try:
            handle = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            try:
                age = datetime.now(timezone.utc).timestamp() - path.stat().st_mtime
            except OSError:
                return False
            if age <= UPDATE_LOCK_STALE_SECONDS:
                return False
            try:
                path.unlink()
            except OSError:
                return False
            continue  # lock velho roubado; tenta criar de novo
        except OSError:
            return False
        try:
            os.write(handle, f"{os.getpid()}\n".encode("utf-8"))
        except OSError:
            pass
        finally:
            os.close(handle)
        return True
    return False


def release_update_lock() -> None:
    """Solta o lock da atualização; silencioso quando não existe."""
    try:
        update_lock_path().unlink()
    except OSError:
        pass


def update_generation_path() -> Path:
    """Marcação da geração do código no disco (commit aplicado por último).

    É o passo de mão entre os processos: quando a janela, o daemon ou o
    install.sh aplicam código novo, a geração muda no estado do app e os
    demais processos percebem na verificação seguinte — cada um reinicia
    sozinho para rodar o código novo sem ninguém pedir nada.
    """
    return app_state_dir() / "update_generation"


def read_update_generation() -> str:
    """Geração do código no disco; "" enquanto não houve atualização."""
    try:
        return update_generation_path().read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def write_update_generation(head: str) -> None:
    """Registra a geração do código pós-atualização (falha silenciosa)."""
    try:
        path = update_generation_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(str(head).strip() + "\n", encoding="utf-8")
    except OSError:
        pass


_PROCESS_GENERATION: str | None = None


def process_update_generation() -> str:
    """Geração do código vista no arranque do processo (lida uma única vez).

    Referência do "este processo está velho?": se a geração no disco mudar
    depois do arranque, o processo está rodando código antigo e deve se
    reiniciar. Lida sob demanda e cacheada; ``reset_process_generation_cache``
    existe para os testes.
    """
    global _PROCESS_GENERATION
    if _PROCESS_GENERATION is None:
        _PROCESS_GENERATION = read_update_generation()
    return _PROCESS_GENERATION


def reset_process_generation_cache() -> None:
    """Descarta a geração pinada (uso dos testes)."""
    global _PROCESS_GENERATION
    _PROCESS_GENERATION = None


def display_version(repo: Path | None = None) -> str:
    """Versão para o usuário ver: base + commit instalado.

    "1.9.1 (5420ca5)" quando o commit de origem é conhecido; só "1.9.1"
    em instalação sem identificação. O sufixo muda a cada atualização
    aplicada — prova visível de que o código é fresco, mesmo que a versão
    base esqueça de subir em alguma correção futura.
    """
    commit = installed_commit(repo)
    if commit:
        return f"{APP_VERSION} ({commit[:7]})"
    return APP_VERSION


LAST_CHECK_FILE = "update_last_check.json"


def last_check_path() -> Path:
    """Registro da última verificação de atualizações (estado do app)."""
    return app_state_dir() / LAST_CHECK_FILE


def record_last_check(result: dict) -> None:
    """Guarda em disco o resultado da última verificação (melhor esforço).

    Diagnóstico: deixa registrado quando o verificador rodou pela última
    vez e o que ele decidiu — o usuário passa a poder confirmar que a
    verificação está viva. Falha de disco nunca derruba a verificação.
    """
    record = {
        "when": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "status": str(result.get("status") or ""),
        "local": result.get("local"),
        "remote": result.get("remote"),
        "message": str(result.get("message") or ""),
    }
    try:
        path = last_check_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(record, ensure_ascii=False), encoding="utf-8"
        )
    except (OSError, ValueError, TypeError):
        pass


def last_check_record() -> dict | None:
    """Lê o registro da última verificação; None quando não há registro."""
    try:
        data = json.loads(last_check_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def check_for_updates(repo: Path | None = None, timeout: float = 6.0) -> dict:
    """Decide se há versão nova no repositório, com ou sem release publicada.

    Ordem de verificação (a primeira resposta vence):
      1. Release publicada com tag mais nova que APP_VERSION (apenas para
         instalações sem git — em clone git este repositório não publica
         releases e a comparação de commits via ls-remote é a verdade,
         sem gastar limite de API);
      2. Commit do main diferente do commit instalado (git clone via
         ls-remote sem limite de API; demais instalações via API de commits
         ou marker source_commit);
      3. Sinal alternativo sem API: APP_VERSION do main publicado em
         raw.githubusercontent comparado com a versão local.

    Todo resultado é registrado no estado do app (`record_last_check`) para
    diagnóstico. Retorna {"status": "available"|"current"|"unknown",
    "local", "remote", "release", "message", "commit_message"}.
    """
    result = {
        "status": "unknown",
        "local": None,
        "remote": None,
        "release": None,
        "message": "Não foi possível verificar atualizações agora.",
        "commit_message": "",
    }
    # O código no disco mudou desde o arranque deste processo (a janela, o
    # daemon ou o install.sh aplicaram uma atualização): este processo
    # ficou velho mesmo que o repositório já esteja em dia.
    result["stale_process"] = (
        process_update_generation() != read_update_generation()
    )
    local = installed_commit(repo)
    result["local"] = local
    remote: str | None
    if local_git_head(repo or app_repo_dir()) is not None:
        # Clone git: ls-remote não sofre limite de requisições da API e
        # este repositório não publica releases — a comparação de commits
        # é a verdade; nenhuma chamada de API é necessária.
        remote = git_remote_head(repo)
        remote_commit = None
        release = None
    else:
        remote_commit = fetch_latest_commit(timeout=timeout)
        remote = remote_commit["sha"] if remote_commit else None
        release = fetch_latest_release(timeout=timeout)
    result["remote"] = remote
    result["release"] = release
    if release is not None and compare_versions(release["tag"], APP_VERSION):
        result["status"] = "available"
        result["message"] = f"Release {release['tag']} disponível."
        record_last_check(result)
        return result

    if local and remote:
        if remote.startswith(local[:12]):
            result["status"] = "current"
            result["message"] = "Você já está na versão mais recente."
        else:
            result["status"] = "available"
            result["message"] = f"Commits novos no main ({remote[:7]})."
            if remote_commit:
                result["commit_message"] = remote_commit.get("message", "")
        record_last_check(result)
        return result

    # Sem comparação de commit possível (instalação sem marker, ou API de
    # commits indisponível): sinal alternativo — APP_VERSION publicado no
    # main via raw.githubusercontent, que não sofre limite de requisições.
    remote_version = fetch_remote_app_version(timeout=timeout)
    if remote_version is not None and compare_versions(remote_version, APP_VERSION):
        result["status"] = "available"
        result["message"] = f"Versão {remote_version} disponível no repositório."
        record_last_check(result)
        return result
    if remote_version is not None and not local:
        result["status"] = "current"
        result["message"] = "Você já está na versão mais recente."
    record_last_check(result)
    return result


def apply_update(repo: Path | None = None, timeout: float = 90.0) -> dict:
    """Atualiza o aplicativo para o main mais recente do repositório.

    Em checkouts git usa `git pull --ff-only` (nunca derruba alterações);
    em instalações copiadas por install.sh baixa o tarball do main e roda
    o install.sh novo. Retorna {"ok", "message", "old_head", "new_head"}.
    """
    repo = repo or app_repo_dir()
    old_head = local_git_head(repo)
    if old_head is None:
        return apply_update_tarball(timeout=timeout)
    try:
        out = subprocess.run(
            ["git", "-C", str(repo), "pull", "--ff-only"],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {
            "ok": False,
            "message": f"git falhou: {exc}",
            "old_head": old_head,
            "new_head": old_head,
        }
    new_head = local_git_head(repo)
    if out.returncode != 0:
        detail = (out.stderr or out.stdout or "").strip().splitlines()
        return {
            "ok": False,
            "message": detail[-1] if detail else "git pull falhou.",
            "old_head": old_head,
            "new_head": new_head,
        }
    if new_head == old_head:
        return {
            "ok": True,
            "message": "Já está na versão mais recente.",
            "old_head": old_head,
            "new_head": new_head,
        }
    write_update_generation(new_head)  # os demais processos se religam sozinhos
    return {
        "ok": True,
        "message": f"Atualizado: {old_head} -> {new_head}.",
        "old_head": old_head,
        "new_head": new_head,
    }


def _extract_tarball_safe(archive: Path, destination: Path) -> None:
    """Extrai um tar.gz rejeitando caminhos suspeitos (../, absolutos)."""
    with tarfile.open(archive, "r:gz") as tar:
        base = destination.resolve()
        for member in tar.getmembers():
            candidate = (base / member.name).resolve()
            if base != candidate and base not in candidate.parents:
                raise ValueError(f"caminho suspeito no pacote: {member.name}")
        try:
            tar.extractall(destination, filter="data")
        except TypeError:  # Python antigo sem o parâmetro filter
            tar.extractall(destination)


def apply_update_tarball(timeout: float = 120.0) -> dict:
    """Atualiza instalações sem git: baixa o main.tar.gz e roda install.sh.

    Grava `source_commit` na instalação para as próximas verificações
    saberem em que commit o código está.
    """
    old_head = installed_commit()
    commit = fetch_latest_commit(timeout=15.0) or {}
    sha = str(commit.get("sha") or "")
    workdir = Path(tempfile.mkdtemp(prefix="multilut-update-"))
    try:
        data = _http_get(TARBALL_URL, timeout=timeout)
        if data is None:
            return {
                "ok": False,
                "message": "Não foi possível baixar o pacote do repositório.",
                "old_head": old_head,
                "new_head": None,
            }
        archive = workdir / "main.tar.gz"
        archive.write_bytes(data)
        source = workdir / "src"
        source.mkdir()
        try:
            _extract_tarball_safe(archive, source)
        except (tarfile.TarError, ValueError) as exc:
            return {
                "ok": False,
                "message": f"Pacote inválido: {exc}",
                "old_head": old_head,
                "new_head": None,
            }
        entries = sorted(p for p in source.iterdir() if p.is_dir())
        if not entries:
            return {
                "ok": False,
                "message": "Pacote do repositório veio vazio.",
                "old_head": old_head,
                "new_head": None,
            }
        root = entries[0]
        if sha:
            (root / "source_commit").write_text(sha + "\n", encoding="utf-8")
        try:
            out = subprocess.run(
                ["bash", "install.sh"],
                cwd=root,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            return {
                "ok": False,
                "message": f"install.sh falhou: {exc}",
                "old_head": old_head,
                "new_head": sha[:7] or None,
            }
        if out.returncode != 0:
            detail = (out.stderr or out.stdout or "").strip().splitlines()
            message = detail[-1] if detail else "install.sh retornou erro."
            return {
                "ok": False,
                "message": message,
                "old_head": old_head,
                "new_head": sha[:7] or None,
            }
    finally:
        shutil.rmtree(workdir, ignore_errors=True)
    new_head = sha[:7] if sha else None
    if sha:
        # Mesmo conteúdo que o install.sh novo acabou de gravar (sha cheio):
        # reescrita idempotente, sem gerar falsa mudança de geração.
        write_update_generation(sha)
    return {
        "ok": True,
        "message": f"Atualizado para {new_head or 'main'}.",
        "old_head": old_head,
        "new_head": new_head,
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
# Insurgency/Day of Infamy da NWI) e o banner do próprio cliente com -condebug,
# que abre com 'Map: xxx' e é reimpresso a cada conexão/troca de mapa do
# cliente (linha 'Map:' do cabeçalho com Build e Server Number).
MAP_LINE_PATTERNS: tuple[re.Pattern, ...] = (
    re.compile(r'Loading map "([^"\s]+)"'),
    re.compile(r"Host_NewGame on map (\S+)"),
    re.compile(r"Mapchange to ([A-Za-z0-9_\-\[\]\.]+)"),
    re.compile(r"Host_Changelevel\s*\(\s*[^,()]+,\s*([^\s,()]+)"),
    re.compile(r"Loading map (\S+)"),
    re.compile(r"^\s*map\s+([A-Za-z0-9_\-\[\]\.]+)\s*$"),
    # banner do cliente (condebug): 'Map: tell' — nunca casava antes e por
    # isso o piloto não via o primeiro mapa de cada boot do jogo
    re.compile(r"^\s*[Mm]ap:\s*([A-Za-z0-9_\-\[\]\.]+)\s*$"),
)


def parse_map_token(line: str) -> str | None:
    """Token do mapa carregado em uma linha do console, ou None."""
    for pattern in MAP_LINE_PATTERNS:
        match = pattern.search(line)
        if match:
            return match.group(1)
    return None


def normalize_map_token(token: str | None) -> str:
    """Token do mapa normalizado: minúsculas, sem aspas ou espaços das bordas."""
    if not token:
        return ""
    text = str(token).strip().strip('"').casefold()
    return text


def map_rules(config: dict | None) -> dict[str, int]:
    """Regras aprendidas de mapa → perfil, validadas contra os perfis.

    Guardadas em config["map_rules"] como {"tell": 22, "sinjar_night": 15};
    entradas inválidas (perfil inexistente, token vazio) são ignoradas.
    """
    raw = (config or {}).get("map_rules")
    if not isinstance(raw, dict):
        return {}
    rules: dict[str, int] = {}
    for key, value in raw.items():
        if not isinstance(key, str):
            continue
        token = normalize_map_token(key)
        try:
            profile_id = int(value)
        except (TypeError, ValueError):
            continue
        if token and profile_id in PROFILE_BY_ID:
            rules[token] = profile_id
    return rules


def set_map_rule(config: dict, token: str, profile_id: int) -> bool:
    """Grava (ou atualiza) a regra mapa → perfil no config informado."""
    token = normalize_map_token(token)
    if not token or profile_id not in PROFILE_BY_ID:
        return False
    rules = config.setdefault("map_rules", {})
    if not isinstance(rules, dict):
        rules = config["map_rules"] = {}
    rules[token] = int(profile_id)
    return True


def remove_map_rule(config: dict, token: str) -> bool:
    """Remove a regra do mapa; devolve True se ela existia."""
    token = normalize_map_token(token)
    rules = (config or {}).get("map_rules")
    if isinstance(rules, dict) and token in rules:
        del rules[token]
        return True
    return False


def match_map_profile(
    token: str | None, rules: dict[str, int] | None = None
) -> Profile | None:
    """Perfil de mapa correspondente ao nome do mapa carregado, ou None.

    "market_coop" casa com Market, "sinjar_night" com Sinjar. Regras
    aprendidas (mapa exato → perfil) vêm primeiro e vencem o casamento por
    slug; o casamento por partes do nome (hífen/underline/colchetes) e, em
    segundo lugar, por prefixo do token inteiro continua como antes.
    """
    if not token:
        return None
    text = normalize_map_token(token)
    if not text:
        return None
    if rules:
        direct = rules.get(text)
        if direct is not None and direct in PROFILE_BY_ID:
            return PROFILE_BY_ID[direct]
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


# ------------------------------------------------------------ console.log
# Pico de leitura por evento do console.log: CONSOLE_DRAIN_BLOCKS blocos de
# CONSOLE_READ_BLOCK bytes (16 x 256 KB = 4 MB por dreno, no máximo). O pico
# baixo mantém a RAM do monitor longe do jogo; o que sobrar é lido no
# evento seguinte (o debounce de 400 ms agrupa as escritas).
CONSOLE_DRAIN_BLOCKS = 16
CONSOLE_READ_BLOCK = 262144

# Teto do fragmento parcial guardado no ConsoleTail. Linhas terminadas só em
# "\r" (progresso do motor durante o load) nunca fecham um "\n" e inflariam
# esse buffer sem limite, inchando o processo em segundo plano durante o jogo.
# Passando do teto, o prefixo velho é descartado e fica só a cauda recente:
# as linhas de mapa são curtas e sempre aparecem no fim do que foi escrito.
CONSOLE_BUFFER_LIMIT = 1048576
CONSOLE_BUFFER_KEEP = 65536


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
        if len(self._buffer) > CONSOLE_BUFFER_LIMIT:
            # log sem "\n" (só "\r"): descarta o prefixo velho em vez de crescer
            # sem limite; o offset já avançou, nada é relido
            self._buffer = self._buffer[-CONSOLE_BUFFER_KEEP:]
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
