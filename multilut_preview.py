#!/usr/bin/env python3
"""Simulação visual (CPU) do pipeline do shader MultiLUT v1.8.

Reproduz, pixel a pixel, o fluxo de PS_MultiLUT_Apply do arquivo
bundle/Shaders/MultiLUT_Insurgency_Optimized.fx usando Pillow + numpy:

  1. ApplyShadowAndLowMid   (recuperação de sombras e baixo-médio)
  2. ApplyProtectedBrightness (brilho de cena com proteção de preto/branco)
  3. SampleMultiLUT         (amostragem trilinear da LUT do atlas v1.8)
  4. BlendLumaChroma        (mistura independente de luma e croma)
  5. Contraste local        (4 taps; aproximação na escala da imagem)
  6. Saturação adaptativa e separação de cores
  7. Compressão suave de highlights

As constantes por perfil (P_CHROMA, P_LUMA, ...) são lidas diretamente do
próprio shader .fx, portanto a simulação acompanha qualquer ajuste feito no
arquivo instalado. O perfil 0 é bypass real, como no shader.

Dependências opcionais: numpy e Pillow. Sem elas, DEPENDENCIES_AVAILABLE é
False e a interface informa como instalar; nada quebra no import.
"""

from __future__ import annotations

import io
import re
import time
from pathlib import Path

import multilut_core as core

try:
    import numpy as np
    from PIL import Image
except ImportError:  # pragma: no cover - ambiente sem as dependências opcionais
    np = None
    Image = None

DEPENDENCIES_AVAILABLE = np is not None and Image is not None

# Geometria do atlas v1.8, herdada do núcleo (fonte única de verdade).
LUT_TILE = core.ATLAS_TILE
LUT_SLICES = core.ATLAS_SLICES
LUT_ROWS = core.ATLAS_ROWS

# Constantes por perfil definidas no shader (cadeia #if ACTIVE_LUT_PROFILE).
CONSTANT_NAMES = (
    "CHROMA",
    "LUMA",
    "SHADOW",
    "DEEP",
    "LOWMID",
    "LOCAL",
    "RADIUS",
    "SAT",
    "HIGHLIGHT",
    "BRIGHT",
    "SEP",
)

_PROFILE_BRANCH = re.compile(r"^\s*#(?:if|elif)\s+ACTIVE_LUT_PROFILE\s*==\s*(\d+)")
_BRANCH_END = re.compile(r"^\s*#(?:else|endif)\b")
_DEFINE = re.compile(r"^\s*#define\s+P_([A-Z]+)\s+(-?\d+(?:\.\d+)?)\s*(?:$|//)")

# kLuma do shader (Rec. 709).
KLUMA = (0.2126, 0.7152, 0.0722)

# Resolução de render padrão do jogo (configurável na interface e no config.json).
# No shader, o passo do contraste local é ReShade::PixelSize * P_RADIUS, ou seja,
# P_RADIUS pixels da resolução nativa — a prévia reproduz essa proporção.
DEFAULT_GAME_RESOLUTION = (1366, 768)


class PreviewError(RuntimeError):
    """Erro user-facing da simulação de LUT."""


def parse_game_resolution(value) -> tuple[int, int]:
    """Converte a resolução do jogo para (largura, altura) inteiros válidos.

    Aceita tuplas/listas de dois números ou texto ``largura x altura``
    (ex.: "1366x768"). Levanta PreviewError para valores inválidos.
    """
    if value is None:
        return DEFAULT_GAME_RESOLUTION
    if isinstance(value, str):
        match = re.fullmatch(
            r"\s*(\d{2,5})\s*[xX×]\s*(\d{2,5})\s*", value
        )
        if not match:
            raise PreviewError(
                f"Resolução do jogo inválida: {value!r} (use, por exemplo, 1366x768)."
            )
        candidate = (int(match.group(1)), int(match.group(2)))
    elif isinstance(value, (tuple, list)) and len(value) == 2:
        try:
            candidate = (int(value[0]), int(value[1]))
        except (TypeError, ValueError) as exc:
            raise PreviewError(f"Resolução do jogo inválida: {value!r}.") from exc
    else:
        raise PreviewError(f"Resolução do jogo inválida: {value!r}.")
    if not (16 <= candidate[0] <= 16384 and 16 <= candidate[1] <= 16384):
        raise PreviewError(
            "Resolução do jogo fora do intervalo suportado (16 a 16384 por eixo)."
        )
    return candidate


# --------------------------------------------------------------------------
# Constantes por perfil extraídas do shader
# --------------------------------------------------------------------------
def parse_profile_constants(shader_text: str) -> dict[int, dict[str, float]]:
    """Lê os blocos ``#if ACTIVE_LUT_PROFILE == N`` e devolve os P_* de cada perfil.

    Somente defines numéricos de nomes conhecidos são considerados; o
    ``#else`` do shader (que cobre o erro de perfil inválido) é ignorado,
    assim como comentários de linha.
    """
    constants: dict[int, dict[str, float]] = {}
    active: int | None = None
    for raw_line in shader_text.splitlines():
        line = raw_line.split("//", 1)[0].rstrip()
        branch = _PROFILE_BRANCH.match(line)
        if branch:
            active = int(branch.group(1))
            continue
        if _BRANCH_END.match(line):
            active = None
            continue
        if active is None:
            continue
        define = _DEFINE.match(line)
        if define and define.group(1) in CONSTANT_NAMES:
            constants.setdefault(active, {})[define.group(1)] = float(
                define.group(2)
            )
    return constants


def missing_constant_profiles(
    constants: dict[int, dict[str, float]], profile_ids: range = range(0, 25)
) -> list[int]:
    """Ids do intervalo que não têm as 11 constantes completas."""
    missing: list[int] = []
    for profile_id in profile_ids:
        values = constants.get(profile_id)
        if not values or any(name not in values for name in CONSTANT_NAMES):
            missing.append(profile_id)
    return missing


# --------------------------------------------------------------------------
# LUT 3D a partir do atlas
# --------------------------------------------------------------------------
def lut3d_from_atlas(atlas: "np.ndarray", row: int) -> "np.ndarray":
    """Converte uma linha do atlas em LUT 3D (32, 32, 32, 3) indexada [b, g, r].

    Layout confirmado no shader: dentro da fatia (tile 32x32), a coluna é o
    vermelho e a linha vertical é o verde; o índice da fatia horizontal é o
    azul. ``atlas`` tem forma (544, 1024, 3) em float [0, 1].
    """
    if np is None:
        raise PreviewError("numpy não está disponível.")
    if atlas.ndim != 3 or atlas.shape[0] < (row + 1) * LUT_TILE:
        raise PreviewError(
            f"Atlas incompatível com a linha {row}: forma {atlas.shape}."
        )
    strip = atlas[row * LUT_TILE : (row + 1) * LUT_TILE]  # (g, x_total, rgb)
    tiles = strip.reshape(LUT_TILE, LUT_SLICES, LUT_TILE, 3)  # (g, b, r, rgb)
    lut = np.transpose(tiles, (1, 0, 2, 3))  # (b, g, r, rgb)
    return np.ascontiguousarray(lut)


def sample_lut(lut: "np.ndarray", rgb: "np.ndarray") -> "np.ndarray":
    """Amostragem trilinear equivalente a SampleMultiLUT do shader.

    ``rgb`` tem forma (..., 3) em [0, 1]; a saída tem a mesma forma. A GPU faz
    bilinear em (r, g) dentro da fatia e o shader interpola o azul entre as
    duas fatias vizinhas — o resultado combinado é trilinear no grid 32³, com
    coordenadas color * (N-1) e canto superior limitado a N-1.
    """
    size = lut.shape[0]
    last = size - 1
    coords = np.clip(rgb, 0.0, 1.0) * last
    r = coords[..., 0]
    g = coords[..., 1]
    b = coords[..., 2]

    def axis(value: "np.ndarray") -> tuple["np.ndarray", "np.ndarray", "np.ndarray"]:
        base = np.floor(value)
        i0 = np.clip(base.astype(np.intp), 0, last)
        i1 = np.clip(i0 + 1, 0, last)
        weight = (value - base)[..., None]
        return i0, i1, weight

    r0, r1, fr = axis(r)
    g0, g1, fg = axis(g)
    b0, b1, fb = axis(b)

    c000 = lut[b0, g0, r0]
    c100 = lut[b1, g0, r0]
    c010 = lut[b0, g1, r0]
    c110 = lut[b1, g1, r0]
    c001 = lut[b0, g0, r1]
    c101 = lut[b1, g0, r1]
    c011 = lut[b0, g1, r1]
    c111 = lut[b1, g1, r1]

    c00 = c000 + (c001 - c000) * fr  # vermelho, fatia b0, linha g0
    c10 = c010 + (c011 - c010) * fr  # vermelho, fatia b0, linha g1
    c01 = c100 + (c101 - c100) * fr  # vermelho, fatia b1, linha g0
    c11 = c110 + (c111 - c110) * fr  # vermelho, fatia b1, linha g1
    c0 = c00 + (c10 - c00) * fg  # verde dentro da fatia b0
    c1 = c01 + (c11 - c01) * fg  # verde dentro da fatia b1
    return c0 + (c1 - c0) * fb  # azul entre as duas fatias


# --------------------------------------------------------------------------
# Estágios do pipeline (vetorizados; cores em float [0, 1])
# --------------------------------------------------------------------------
def smoothstep(edge0: float, edge1: float, x: "np.ndarray") -> "np.ndarray":
    t = np.clip((x - edge0) / (edge1 - edge0), 0.0, 1.0)
    return t * t * (3.0 - 2.0 * t)


def luma709(img: "np.ndarray") -> "np.ndarray":
    return (
        img[..., 0] * KLUMA[0] + img[..., 1] * KLUMA[1] + img[..., 2] * KLUMA[2]
    )


def _set_luma_stable(
    color: "np.ndarray", old_luma: "np.ndarray", new_luma: "np.ndarray"
) -> "np.ndarray":
    """Reconstrução multiplicativa do shader, com confiança perto do preto."""
    safe = np.maximum(old_luma, 0.0001)[..., None]
    scaled = color * (new_luma[..., None] / safe)
    confidence = smoothstep(0.006, 0.050, old_luma)[..., None]
    neutral = np.broadcast_to(new_luma[..., None], color.shape)
    return neutral + (scaled - neutral) * confidence


def _recover_luma(luma: "np.ndarray", const: dict[str, float]) -> "np.ndarray":
    deep_gate = smoothstep(0.002, 0.018, luma)
    deep_mask = 1.0 - smoothstep(0.075, 0.34, luma)
    deep = (
        const["DEEP"]
        * 0.30
        * np.sqrt(np.maximum(luma, 0.0))
        * deep_gate
        * deep_mask
    )
    gate = smoothstep(0.006, 0.060, luma)
    mask = 1.0 - smoothstep(0.10, 0.52, luma)
    recovery = const["SHADOW"] * 0.115 * gate * mask
    return np.minimum(luma + deep + recovery, 1.0)


def apply_shadow_and_lowmid(img: "np.ndarray", const: dict[str, float]) -> "np.ndarray":
    source_luma = luma709(img)
    recovered = _recover_luma(source_luma, const)
    window = smoothstep(0.045, 0.20, recovered) * (
        1.0 - smoothstep(0.54, 0.78, recovered)
    )
    separation = (recovered - 0.30) * 0.16 * const["LOWMID"] * window
    target = np.clip(recovered + separation, 0.0, 1.0)
    return np.clip(_set_luma_stable(img, source_luma, target), 0.0, 1.0)


def apply_protected_brightness(img: "np.ndarray", const: dict[str, float]) -> "np.ndarray":
    source_luma = luma709(img)
    gate = smoothstep(0.006, 0.035, source_luma)
    exclusion = 1.0 - smoothstep(0.58, 0.86, source_luma)
    lift = (
        const["BRIGHT"] * 0.18 * gate * exclusion * (1.0 - source_luma)
    )
    target = np.minimum(source_luma + lift, 1.0)
    return np.clip(_set_luma_stable(img, source_luma, target), 0.0, 1.0)


def blend_luma_chroma(
    source: "np.ndarray", graded: "np.ndarray", const: dict[str, float]
) -> "np.ndarray":
    source_luma = luma709(source)
    graded_luma = luma709(graded)
    target_luma = source_luma + (graded_luma - source_luma) * const["LUMA"]

    source_ratio = (source - source_luma[..., None]) / np.maximum(
        source_luma, 0.025
    )[..., None]
    graded_ratio = (graded - graded_luma[..., None]) / np.maximum(
        graded_luma, 0.025
    )[..., None]
    source_ratio = np.clip(source_ratio, -1.75, 1.75)
    graded_ratio = np.clip(graded_ratio, -1.75, 1.75)

    confidence = smoothstep(0.008, 0.060, target_luma) * (
        1.0 - smoothstep(0.96, 1.0, target_luma)
    )
    mix = const["CHROMA"] * confidence[..., None]
    ratio = source_ratio + (graded_ratio - source_ratio) * mix
    return np.clip(target_luma[..., None] + ratio * target_luma[..., None], 0.0, 1.0)


def local_contrast_step(
    preview_size: tuple[int, int],
    game_resolution: tuple[int, int],
    radius: float,
) -> tuple[float, float]:
    """Passo dos 4 taps da prévia em pixels, replicando o shader.

    No jogo o passo é ``P_RADIUS`` pixels da resolução de render
    (``ReShade::PixelSize * fLUT_LocalRadius``); na prévia o mesmo deslocamento
    físico corresponde a ``P_RADIUS * prévia/jogo`` pixels por eixo.
    """
    preview_w, preview_h = int(preview_size[0]), int(preview_size[1])
    game_w, game_h = int(game_resolution[0]), int(game_resolution[1])
    if preview_w <= 0 or preview_h <= 0:
        raise PreviewError(f"Tamanho da prévia inválido: {preview_size}.")
    if game_w <= 0 or game_h <= 0:
        raise PreviewError(f"Resolução do jogo inválida: {game_resolution}.")
    return (
        float(radius) * preview_w / game_w,
        float(radius) * preview_h / game_h,
    )


def _bilinear_sample(
    image: "np.ndarray", offset_y: float, offset_x: float
) -> "np.ndarray":
    """Amostra a imagem deslocada por (offset_y, offset_x) fracionário.

    Equivale ao tex2D com filtro LINEAR e AddressU/V CLAMP da GPU: interpola
    entre os texels vizinhos e repete a borda fora da imagem.
    """
    height, width = image.shape
    ys = np.arange(height, dtype=np.float32) + np.float32(offset_y)
    xs = np.arange(width, dtype=np.float32) + np.float32(offset_x)

    def axis(values: "np.ndarray", limit: int):
        floor = np.floor(values)
        i0 = np.clip(floor.astype(np.intp), 0, limit)
        i1 = np.clip(i0 + 1, 0, limit)
        weight = values - floor
        weight = np.where(i0 == i1, np.float32(0.0), weight)
        return i0, i1, weight.astype(np.float32)

    y0, y1, ty = axis(ys, height - 1)
    x0, x1, tx = axis(xs, width - 1)
    ty = ty[:, None]
    tx = tx[None, :]
    top = image[np.ix_(y0, x0)] * (1.0 - tx) + image[np.ix_(y0, x1)] * tx
    bottom = image[np.ix_(y1, x0)] * (1.0 - tx) + image[np.ix_(y1, x1)] * tx
    return top * (1.0 - ty) + bottom * ty


def apply_local_contrast(
    color: "np.ndarray",
    original: "np.ndarray",
    const: dict[str, float],
    step_px: tuple[float, float] = (1.0, 1.0),
) -> "np.ndarray":
    """Contraste local: 4 taps com o raio escalado pela resolução do jogo.

    ``step_px`` é o deslocamento dos taps em pixels da prévia por eixo
    (horizontal, vertical), já contendo ``P_RADIUS * prévia/jogo`` — o mesmo
    deslocamento físico do shader na resolução configurada do jogo. Os taps
    usam a luma recuperada do quadro original (RecoveredNeighborLuma) e são
    amostrados de forma bilinear, como o filtro LINEAR da GPU.
    """
    base = _recover_luma(luma709(original), const)
    step_x, step_y = float(step_px[0]), float(step_px[1])
    right = _bilinear_sample(base, 0.0, step_x)
    left = _bilinear_sample(base, 0.0, -step_x)
    down = _bilinear_sample(base, step_y, 0.0)
    up = _bilinear_sample(base, -step_y, 0.0)
    local_average = 0.25 * (up + down + left + right)

    current = luma709(color)
    detail = np.clip(current - local_average, -0.055, 0.055)
    window = smoothstep(0.035, 0.18, current) * (
        1.0 - smoothstep(0.76, 0.94, current)
    )
    shift = (detail * const["LOCAL"] * window)[..., None]
    return np.clip(color + shift, 0.0, 1.0)


def apply_adaptive_saturation(color: "np.ndarray", const: dict[str, float]) -> "np.ndarray":
    current = luma709(color)
    window = smoothstep(0.018, 0.12, current) * (
        1.0 - smoothstep(0.82, 0.99, current)
    )
    chroma = color - current[..., None]
    return current[..., None] + chroma * (1.0 + const["SAT"] * window[..., None])


def apply_color_separation(color: "np.ndarray", const: dict[str, float]) -> "np.ndarray":
    current = luma709(color)
    chroma_vector = color - current[..., None]
    magnitude = np.sqrt((chroma_vector * chroma_vector).sum(axis=-1))
    chroma_window = smoothstep(0.012, 0.090, magnitude) * (
        1.0 - smoothstep(0.38, 0.62, magnitude)
    )
    range_window = smoothstep(0.020, 0.10, current) * (
        1.0 - smoothstep(0.86, 0.99, current)
    )
    gain = 1.0 + const["SEP"] * chroma_window[..., None] * range_window[..., None]
    return current[..., None] + chroma_vector * gain


def apply_highlight_protection(color: "np.ndarray", const: dict[str, float]) -> "np.ndarray":
    current = luma709(color)
    mask = smoothstep(0.72, 1.0, current)
    protected = current - const["HIGHLIGHT"] * 0.085 * mask * (current - 0.72) / 0.28
    return _set_luma_stable(color, current, np.maximum(protected, 0.0))


def simulate_pixels(
    profile_id: int,
    pixels: "np.ndarray",
    lut: "np.ndarray",
    const: dict[str, float],
    game_resolution: tuple[int, int] | None = None,
) -> "np.ndarray":
    """Pipeline completo do shader sobre pixels (h, w, 3) float [0, 1].

    ``game_resolution`` é a resolução de render configurada do jogo; o raio
    do contraste local (P_RADIUS) é escalado por ela para o tamanho da prévia.
    """
    if np is None:
        raise PreviewError("numpy não está disponível.")
    original = np.clip(pixels, 0.0, 1.0).astype(np.float32)
    if profile_id == 0:  # bypass real, como no shader
        return original
    resolution = parse_game_resolution(game_resolution)
    height, width = original.shape[:2]
    step = local_contrast_step(
        (width, height), resolution, const.get("RADIUS", 1.0)
    )
    prepared = apply_shadow_and_lowmid(original, const)
    prepared = apply_protected_brightness(prepared, const)
    lut_color = sample_lut(lut, prepared)
    color = blend_luma_chroma(prepared, lut_color, const)
    color = apply_local_contrast(color, original, const, step_px=step)
    color = apply_adaptive_saturation(color, const)
    color = apply_color_separation(color, const)
    color = apply_highlight_protection(color, const)
    return np.clip(color, 0.0, 1.0)


# --------------------------------------------------------------------------
# Entradas/saídas de alto nível
# --------------------------------------------------------------------------
_ATLAS_CACHE: dict[str, tuple[float, "np.ndarray"]] = {}


def load_atlas_array(atlas_path: Path | str) -> "np.ndarray":
    if not DEPENDENCIES_AVAILABLE:
        raise PreviewError(
            "Simulação indisponível: instale numpy e Pillow "
            "(no Solus: sudo eopkg it numpy python-pillow)."
        )
    path = Path(atlas_path)
    try:
        image = Image.open(path).convert("RGB")
    except (OSError, ValueError) as exc:
        raise PreviewError(f"Não foi possível abrir o atlas: {atlas_path}") from exc
    try:
        stamp = path.stat().st_mtime
    except OSError:
        stamp = 0.0
    key = str(path)
    cached = _ATLAS_CACHE.get(key)
    if cached is not None and cached[0] == stamp:
        return cached[1]
    atlas = np.asarray(image, dtype=np.float32) / 255.0
    _ATLAS_CACHE[key] = (stamp, atlas)
    return atlas


def load_source_image(source_path: Path | str, max_width: int = 1024) -> "Image.Image":
    """Foto do mapa em RGB, reduzida para caber em max_width quando maior."""
    if not DEPENDENCIES_AVAILABLE:
        raise PreviewError(
            "Simulação indisponível: instale numpy e Pillow "
            "(no Solus: sudo eopkg it numpy python-pillow)."
        )
    try:
        image = Image.open(source_path).convert("RGB")
    except (OSError, ValueError) as exc:
        raise PreviewError(f"Não foi possível abrir a imagem: {source_path}") from exc
    if image.width > max_width:
        scale = max_width / image.width
        new_size = (max_width, max(1, round(image.height * scale)))
        image = image.resize(new_size, _resampling_lanczos())
    return image


def render_preview(
    profile_id: int,
    source_path: Path | str,
    atlas_path: Path | str,
    shader_path: Path | str,
    max_width: int = 1024,
    game_resolution: tuple[int, int] | str | None = None,
    lut_row: int | None = None,
) -> dict:
    """Gera {'original', 'simulated', 'elapsed_ms', 'source_size', 'game_resolution'}.

    Levanta PreviewError quando atlas/shader/imagem não estiverem acessíveis
    ou quando as dependências opcionais não existirem. ``game_resolution``
    aceita (largura, altura) ou "largura x altura"; ``lut_row`` permite apontar
    explicitamente a linha do atlas (reindexação); sem ele vale o mapeamento
    padrão P_LUT_ROW do shader v1.8.
    """
    started = time.perf_counter()
    resolution = parse_game_resolution(game_resolution)
    source = load_source_image(source_path, max_width=max_width)
    atlas = load_atlas_array(atlas_path)
    expected = (core.ATLAS_SIZE[1], core.ATLAS_SIZE[0], 3)
    if atlas.shape != expected:
        raise PreviewError(
            "Atlas com geometria inesperada: "
            f"{atlas.shape[1]}x{atlas.shape[0]} (esperado "
            f"{core.ATLAS_SIZE[0]}x{core.ATLAS_SIZE[1]})."
        )
    try:
        shader_text = Path(shader_path).read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise PreviewError(f"Não foi possível ler o shader: {shader_path}") from exc
    constants = parse_profile_constants(shader_text)
    const = constants.get(int(profile_id))
    if const is None:
        raise PreviewError(
            f"O shader não define constantes para o perfil {profile_id}."
        )

    row = int(lut_row) if lut_row is not None else core.lut_row_for_profile(
        int(profile_id)
    )
    lut = lut3d_from_atlas(atlas, row)

    pixels = np.asarray(source, dtype=np.float32) / 255.0
    simulated = simulate_pixels(
        int(profile_id), pixels, lut, const, game_resolution=resolution
    )
    simulated_image = Image.fromarray(
        (np.clip(simulated, 0.0, 1.0) * 255.0 + 0.5).astype(np.uint8)
    )
    elapsed_ms = (time.perf_counter() - started) * 1000.0
    return {
        "original": source,
        "simulated": simulated_image,
        "elapsed_ms": elapsed_ms,
        "source_size": source.size,
        "game_resolution": resolution,
    }


def compose_side_by_side(
    left: "Image.Image", right: "Image.Image", divider: int = 6
) -> "Image.Image":
    """Junta as duas imagens na mesma altura com um separador escuro."""
    if left.size != right.size:
        right = right.resize(left.size, _resampling_nearest())
    width = left.width + right.width + divider
    height = max(left.height, right.height)
    composed = Image.new("RGB", (width, height), (16, 16, 20))
    composed.paste(left, (0, 0))
    composed.paste(right, (left.width + divider, 0))
    return composed


def _resampling_lanczos():  # pragma: no cover - compatibilidade Pillow antigo
    try:
        return Image.Resampling.LANCZOS
    except AttributeError:
        return Image.LANCZOS  # type: ignore[attr-defined]


def _resampling_nearest():  # pragma: no cover - compatibilidade Pillow antigo
    try:
        return Image.Resampling.NEAREST
    except AttributeError:
        return Image.NEAREST  # type: ignore[attr-defined]


def png_bytes(image: "Image.Image") -> bytes:
    buffer = io.BytesIO()
    image.save(buffer, format="PNG", optimize=False)
    return buffer.getvalue()
