#!/usr/bin/env python3
"""Testes da simulação visual de LUT (multilut_preview)."""

from __future__ import annotations

import io
import math
from pathlib import Path

import pytest

import multilut_core as core

pytest.importorskip("numpy")
pytest.importorskip("PIL")

import multilut_preview as preview  # noqa: E402
import numpy as np  # noqa: E402
from PIL import Image  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
BUNDLE_SHADER = REPO / "bundle/Shaders/MultiLUT_Insurgency_Optimized.fx"
BUNDLE_ATLAS = REPO / "bundle/Textures/MultiLut_Insurgency_Optimized.png"
MAP_HEIGHTS = REPO / "assets/maps/heights.jpg"


# ---------------------------------------------------------------------------
# Utilidades de teste
# ---------------------------------------------------------------------------
def identity_lut() -> np.ndarray:
    """LUT linear identidade: lut[b,g,r] = (r/31, g/31, b/31)."""
    axis = np.arange(32, dtype=np.float32) / 31.0
    r = np.broadcast_to(axis[None, None, :], (32, 32, 32))
    g = np.broadcast_to(axis[None, :, None], (32, 32, 32))
    b = np.broadcast_to(axis[:, None, None], (32, 32, 32))
    return np.stack((r, g, b), axis=-1).astype(np.float32)


def atlas_from_rows(rows: dict[int, np.ndarray]) -> np.ndarray:
    """Monta um atlas (544, 1024, 3) a partir de {linha: lut3d}."""
    atlas = np.zeros((core.ATLAS_SIZE[1], core.ATLAS_SIZE[0], 3), dtype=np.float32)
    for row, lut in rows.items():
        tiles = np.transpose(lut, (1, 0, 2, 3))  # (b,g,r) -> (g,b,r)
        atlas[row * 32 : (row + 1) * 32] = tiles.reshape(32, 1024, 3)
    return atlas


SYNTHETIC_SHADER = """
#if ACTIVE_LUT_PROFILE == 0
    #define P_CHROMA     0.00
    #define P_LUMA       0.00
    #define P_SHADOW     0.00
    #define P_DEEP       0.00
    #define P_LOWMID     0.00
    #define P_LOCAL      0.00
    #define P_RADIUS     1.00
    #define P_SAT        0.000
    #define P_HIGHLIGHT  0.00
    #define P_BRIGHT     0.00
    #define P_SEP        0.00
#elif ACTIVE_LUT_PROFILE == 5
    #define P_CHROMA     1.00 // croma integral
    #define P_LUMA       1.00
    #define P_SHADOW     0.00
    #define P_DEEP       0.00
    #define P_LOWMID     0.00
    #define P_LOCAL      0.00
    #define P_RADIUS     1.00
    #define P_SAT        0.000
    #define P_HIGHLIGHT  0.00
    #define P_BRIGHT     0.00
    #define P_SEP        0.00
#else
    #error ACTIVE_LUT_PROFILE deve usar um numero inteiro entre 0 e 24
#endif
"""


# ---------------------------------------------------------------------------
# Parser de constantes
# ---------------------------------------------------------------------------
def test_parse_bundle_constants_complete() -> None:
    constants = preview.parse_profile_constants(BUNDLE_SHADER.read_text("utf-8"))
    assert sorted(constants) == list(range(25))
    assert preview.missing_constant_profiles(constants) == []
    neutral = constants[0]
    assert neutral["CHROMA"] == 0.0 and neutral["HIGHLIGHT"] == 0.0
    district = constants[3]
    assert 0.0 < district["CHROMA"] <= 1.0
    assert district["RADIUS"] == pytest.approx(1.0)


def test_parse_ignores_comments_and_else() -> None:
    constants = preview.parse_profile_constants(SYNTHETIC_SHADER)
    assert sorted(constants) == [0, 5]
    assert constants[0]["CHROMA"] == 0.0
    assert constants[5]["CHROMA"] == 1.0
    # P_LUT_ROW do shader real não pode vazar como constante
    real = preview.parse_profile_constants(BUNDLE_SHADER.read_text("utf-8"))
    assert all("LUT_ROW" not in values for values in real.values())


# ---------------------------------------------------------------------------
# LUT 3D e amostragem
# ---------------------------------------------------------------------------
def test_lut3d_orientation_from_atlas() -> None:
    atlas = atlas_from_rows({7: identity_lut()})
    lut = preview.lut3d_from_atlas(atlas, 7)
    assert lut.shape == (32, 32, 32, 3)
    expected = identity_lut()
    np.testing.assert_allclose(lut, expected, atol=1e-6)


def test_sample_lut_exact_grid_points() -> None:
    lut = identity_lut()
    probes = np.array(
        [
            [0.0, 0.0, 0.0],
            [1.0, 1.0, 1.0],
            [0.5, 0.25, 0.75],
            [13.0 / 31.0, 3.0 / 31.0, 30.0 / 31.0],
        ],
        dtype=np.float32,
    )
    np.testing.assert_allclose(preview.sample_lut(lut, probes), probes, atol=1e-6)


def test_sample_lut_interpolates_between_slices() -> None:
    lut = np.zeros((32, 32, 32, 3), dtype=np.float32)
    lut[:16] = (1.0, 0.0, 0.0)  # azul baixo -> vermelho puro
    lut[16:] = (0.0, 1.0, 0.0)  # azul alto -> verde puro
    point = np.array([[[0.0, 0.0, 15.5 / 31.0]]], dtype=np.float32)
    out = preview.sample_lut(lut, point)
    np.testing.assert_allclose(out[0, 0], (0.5, 0.5, 0.0), atol=1e-6)


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------
def test_profile0_is_true_bypass() -> None:
    rng = np.random.default_rng(7)
    pixels = rng.random((16, 16, 3), dtype=np.float32)
    constants = preview.parse_profile_constants(BUNDLE_SHADER.read_text("utf-8"))
    atlas = preview.load_atlas_array(BUNDLE_ATLAS)
    lut = preview.lut3d_from_atlas(atlas, core.lut_row_for_profile(0))
    out = preview.simulate_pixels(0, pixels, lut, constants[0])
    np.testing.assert_array_equal(out, pixels)


def test_synthetic_red_boost_lut() -> None:
    """LUT sintética que multiplica o vermelho por 1.5 com mistura integral."""
    lut = identity_lut().copy()
    lut[..., 0] = np.clip(lut[..., 0] * 1.5, 0.0, 1.0)
    atlas = atlas_from_rows({5: lut})

    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        atlas_path = Path(tmp) / "atlas.png"
        Image.fromarray((atlas * 255.0 + 0.5).astype(np.uint8)).save(atlas_path)
        shader_path = Path(tmp) / "fake.fx"
        shader_path.write_text(SYNTHETIC_SHADER, encoding="utf-8")
        source_path = Path(tmp) / "src.png"
        source = Image.new("RGB", (64, 32), (100, 120, 140))
        source.save(source_path)

        result = preview.render_preview(5, source_path, atlas_path, shader_path)

    simulated = np.asarray(result["simulated"], dtype=np.float32)
    original = np.asarray(result["original"], dtype=np.float32)
    # vermelho sobe ~50% (100 -> 150), verde e azul ficam
    assert simulated[..., 0].mean() == pytest.approx(150.0, abs=6.0)
    np.testing.assert_allclose(simulated[..., 1], original[..., 1], atol=2.0)
    np.testing.assert_allclose(simulated[..., 2], original[..., 2], atol=2.0)


def test_render_preview_real_bundle_profile3_changes_image() -> None:
    result = preview.render_preview(3, MAP_HEIGHTS, BUNDLE_ATLAS, BUNDLE_SHADER, max_width=512)
    composed = preview.compose_side_by_side(result["original"], result["simulated"])
    data = preview.png_bytes(composed)
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    image = Image.open(io.BytesIO(data))
    assert image.size == (512 * 2 + 6, result["original"].height)

    original = np.asarray(result["original"], dtype=np.int16)
    simulated = np.asarray(result["simulated"], dtype=np.int16)
    mean_abs = float(np.abs(simulated - original).mean())
    assert mean_abs > 1.5, f"simulação não alterou a imagem (diff média {mean_abs:.2f})"


def test_render_preview_profile0_identical() -> None:
    result = preview.render_preview(0, MAP_HEIGHTS, BUNDLE_ATLAS, BUNDLE_SHADER, max_width=512)
    original = np.asarray(result["original"])
    simulated = np.asarray(result["simulated"])
    np.testing.assert_array_equal(original, simulated)


def test_render_preview_rejects_bad_geometry() -> None:
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        bad_atlas = Path(tmp) / "atlas.png"
        Image.new("RGB", (64, 32)).save(bad_atlas)
        with pytest.raises(preview.PreviewError, match="geometria"):
            preview.render_preview(1, MAP_HEIGHTS, bad_atlas, BUNDLE_SHADER)


def test_render_preview_rejects_unknown_profile() -> None:
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        shader_path = Path(tmp) / "fake.fx"
        shader_path.write_text(SYNTHETIC_SHADER, encoding="utf-8")
        with pytest.raises(preview.PreviewError, match="perfil 3"):
            preview.render_preview(3, MAP_HEIGHTS, BUNDLE_ATLAS, shader_path, max_width=128)


# ---------------------------------------------------------------------------
# Referência escalar independente (float64) do shader
# ---------------------------------------------------------------------------
def _ss(edge0: float, edge1: float, x: float) -> float:
    t = min(1.0, max(0.0, (x - edge0) / (edge1 - edge0)))
    return t * t * (3.0 - 2.0 * t)


def _lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t


def _ref_pipeline_pixel(rgb, original_img, y, x, lut, const):
    """Transcrição escalar do PS_MultiLUT_Apply para conferência pontual."""
    color = [min(1.0, max(0.0, c)) for c in rgb]

    def luma(v):
        return 0.2126 * v[0] + 0.7152 * v[1] + 0.0722 * v[2]

    def set_luma(col, old, new):
        safe = max(old, 0.0001)
        scaled = [c * (new / safe) for c in col]
        conf = _ss(0.006, 0.050, old)
        neutral = (new, new, new)
        return [_lerp(neutral[i], scaled[i], conf) for i in range(3)]

    def recover(l):
        deep = const["DEEP"] * 0.30 * math.sqrt(max(l, 0.0)) * _ss(0.002, 0.018, l) * (
            1.0 - _ss(0.075, 0.34, l)
        )
        rec = const["SHADOW"] * 0.115 * _ss(0.006, 0.060, l) * (1.0 - _ss(0.10, 0.52, l))
        return min(l + deep + rec, 1.0)

    def shadow_lowmid(col):
        sl = luma(col)
        rec = recover(sl)
        window = _ss(0.045, 0.20, rec) * (1.0 - _ss(0.54, 0.78, rec))
        target = min(max(rec + (rec - 0.30) * 0.16 * const["LOWMID"] * window, 0.0), 1.0)
        return [min(max(v, 0.0), 1.0) for v in set_luma(col, sl, target)]

    def brightness(col):
        sl = luma(col)
        lift = const["BRIGHT"] * 0.18 * _ss(0.006, 0.035, sl) * (
            1.0 - _ss(0.58, 0.86, sl)
        ) * (1.0 - sl)
        target = min(sl + lift, 1.0)
        return [min(max(v, 0.0), 1.0) for v in set_luma(col, sl, target)]

    def sample(col):
        c = [min(1.0, max(0.0, v)) for v in col]
        r, g, b = (v * 31.0 for v in c)
        b0, b1 = min(int(b), 31), min(int(b) + 1, 31)
        fb = b - math.floor(b)
        r0, g0 = min(int(r), 31), min(int(g), 31)
        r1, g1 = min(r0 + 1, 31), min(g0 + 1, 31)
        fr, fg = r - math.floor(r), g - math.floor(g)

        def at(bb, gg, rr):
            return lut[bb, gg, rr].tolist()

        c00 = [ _lerp(at(b0, g0, r0)[i], at(b0, g0, r1)[i], fr) for i in range(3)]
        c10 = [ _lerp(at(b0, g1, r0)[i], at(b0, g1, r1)[i], fr) for i in range(3)]
        c01 = [ _lerp(at(b1, g0, r0)[i], at(b1, g0, r1)[i], fr) for i in range(3)]
        c11 = [ _lerp(at(b1, g1, r0)[i], at(b1, g1, r1)[i], fr) for i in range(3)]
        c0 = [_lerp(c00[i], c10[i], fg) for i in range(3)]
        c1 = [_lerp(c01[i], c11[i], fg) for i in range(3)]
        return [_lerp(c0[i], c1[i], fb) for i in range(3)]

    def blend(src, grad):
        sl, gl = luma(src), luma(grad)
        target = _lerp(sl, gl, const["LUMA"])
        sr = [min(1.75, max(-1.75, (src[i] - sl) / max(sl, 0.025))) for i in range(3)]
        gr = [min(1.75, max(-1.75, (grad[i] - gl) / max(gl, 0.025))) for i in range(3)]
        conf = _ss(0.008, 0.060, target) * (1.0 - _ss(0.96, 1.0, target))
        mix = const["CHROMA"] * conf
        ratio = [_lerp(sr[i], gr[i], mix) for i in range(3)]
        return [min(max(target + ratio[i] * target, 0.0), 1.0) for i in range(3)]

    prepared = brightness(shadow_lowmid(color))
    lut_color = sample(prepared)
    col = blend(prepared, lut_color)

    def recovered_at(yy, xx):
        return recover(luma(original_img[yy, xx].tolist()))

    # Passo do shader: ReShade::PixelSize * fLUT_LocalRadius — na prévia, o
    # mesmo deslocamento físico escala por prévia/resolução-do-jogo por eixo.
    game_w, game_h = preview.DEFAULT_GAME_RESOLUTION
    height, width = original_img.shape[0], original_img.shape[1]
    step_x = const["RADIUS"] * width / game_w
    step_y = const["RADIUS"] * height / game_h

    def recovered_sample(fy, fx):
        """tex2D LINEAR + CLAMP sobre a luma recuperada."""
        fy = min(max(fy, 0.0), height - 1.0)
        fx = min(max(fx, 0.0), width - 1.0)
        y0, x0 = int(math.floor(fy)), int(math.floor(fx))
        y1, x1 = min(y0 + 1, height - 1), min(x0 + 1, width - 1)
        ty, tx = fy - y0, fx - x0
        top = _lerp(recovered_at(y0, x0), recovered_at(y0, x1), tx)
        bottom = _lerp(recovered_at(y1, x0), recovered_at(y1, x1), tx)
        return _lerp(top, bottom, ty)

    local = 0.25 * (
        recovered_sample(y + step_y, x)
        + recovered_sample(y - step_y, x)
        + recovered_sample(y, x + step_x)
        + recovered_sample(y, x - step_x)
    )
    cur = luma(col)
    detail = min(0.055, max(-0.055, cur - local))
    window = _ss(0.035, 0.18, cur) * (1.0 - _ss(0.76, 0.94, cur))
    col = [min(max(c + detail * const["LOCAL"] * window, 0.0), 1.0) for c in col]

    cur = luma(col)
    win = _ss(0.018, 0.12, cur) * (1.0 - _ss(0.82, 0.99, cur))
    col = [cur + (c - cur) * (1.0 + const["SAT"] * win) for c in col]

    cur = luma(col)
    chroma = [c - cur for c in col]
    mag = math.sqrt(chroma[0] ** 2 + chroma[1] ** 2 + chroma[2] ** 2)
    cwin = _ss(0.012, 0.090, mag) * (1.0 - _ss(0.38, 0.62, mag))
    rwin = _ss(0.020, 0.10, cur) * (1.0 - _ss(0.86, 0.99, cur))
    col = [cur + chroma[i] * (1.0 + const["SEP"] * cwin * rwin) for i in range(3)]

    cur = luma(col)
    mask = _ss(0.72, 1.0, cur)
    protected = max(cur - const["HIGHLIGHT"] * 0.085 * mask * (cur - 0.72) / 0.28, 0.0)
    col = set_luma(col, cur, protected)
    return [min(max(c, 0.0), 1.0) for c in col]


def test_vectorized_matches_scalar_reference() -> None:
    constants = preview.parse_profile_constants(BUNDLE_SHADER.read_text("utf-8"))
    atlas = preview.load_atlas_array(BUNDLE_ATLAS)
    rng = np.random.default_rng(42)
    pixels = rng.random((24, 24, 3), dtype=np.float32)
    for profile_id in (1, 3, 15, 23):
        const = constants[profile_id]
        lut = preview.lut3d_from_atlas(atlas, core.lut_row_for_profile(profile_id))
        out = preview.simulate_pixels(profile_id, pixels, lut, const)
        for y, x in ((5, 9), (12, 3), (20, 18), (2, 22), (15, 15)):
            expected = _ref_pipeline_pixel(
                pixels[y, x].tolist(), pixels, y, x, lut, const
            )
            np.testing.assert_allclose(
                out[y, x], expected, atol=2e-3,
                err_msg=f"perfil {profile_id} pixel ({y},{x})",
            )


def test_png_bytes_roundtrip() -> None:
    image = Image.new("RGB", (10, 6), (200, 10, 10))
    data = preview.png_bytes(image)
    recovered = Image.open(io.BytesIO(data))
    assert recovered.size == (10, 6)
    assert recovered.convert("RGB").getpixel((0, 0)) == (200, 10, 10)


def test_cli_preview_writes_png(tmp_path) -> None:
    import multilut_ctl

    output = tmp_path / "preview.png"
    code = multilut_ctl.main(
        [
            "preview",
            "3",
            "--shader",
            str(BUNDLE_SHADER),
            "--atlas",
            str(BUNDLE_ATLAS),
            "--saida",
            str(output),
        ]
    )
    assert code == 0
    assert output.is_file()
    assert output.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"
    image = Image.open(output)
    # original + simulado lado a lado, foto 1024x512 limitada a 1024 de largura
    assert image.width > 1024 and image.height == 512


def test_cli_preview_rejects_profile_without_map(tmp_path, capsys) -> None:
    import multilut_ctl

    code = multilut_ctl.main(
        [
            "preview",
            "14",
            "--shader",
            str(BUNDLE_SHADER),
            "--atlas",
            str(BUNDLE_ATLAS),
            "--saida",
            str(tmp_path / "x.png"),
        ]
    )
    assert code == 1
    assert "--mapa" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# Raio do contraste local escalado pela resolução configurada do jogo
# ---------------------------------------------------------------------------
def test_parse_game_resolution_variants() -> None:
    assert preview.parse_game_resolution(None) == preview.DEFAULT_GAME_RESOLUTION
    assert preview.DEFAULT_GAME_RESOLUTION == (1366, 768)
    assert preview.parse_game_resolution("1366x768") == (1366, 768)
    assert preview.parse_game_resolution("1920X1080") == (1920, 1080)
    assert preview.parse_game_resolution((2560, 1440)) == (2560, 1440)
    with pytest.raises(preview.PreviewError):
        preview.parse_game_resolution("1366")
    with pytest.raises(preview.PreviewError):
        preview.parse_game_resolution("1366xabc")
    with pytest.raises(preview.PreviewError):
        preview.parse_game_resolution((10, 10))


def test_local_contrast_step_scales_by_resolution() -> None:
    step = preview.local_contrast_step((768, 432), (1366, 768), 1.0)
    assert step == pytest.approx((768 / 1366, 432 / 768))
    assert preview.local_contrast_step(
        (1366, 768), (1366, 768), 1.5
    ) == pytest.approx((1.5, 1.5))
    assert preview.local_contrast_step((3840, 2160), (1366, 768), 2.0)[0] > 5.0


def test_bilinear_sample_matches_roll_for_integer_offsets() -> None:
    rng = np.random.default_rng(3)
    image = rng.random((9, 11)).astype(np.float32)
    np.testing.assert_allclose(preview._bilinear_sample(image, 0, 0), image, atol=1e-6)
    shifted = preview._bilinear_sample(image, 0, 2)
    np.testing.assert_allclose(shifted[:, :-2], image[:, 2:], atol=1e-6)
    np.testing.assert_allclose(shifted[:, -2], image[:, -1], atol=1e-6)  # clamp
    np.testing.assert_allclose(shifted[:, -1], image[:, -1], atol=1e-6)  # clamp
    up = preview._bilinear_sample(image, -1, 0)
    np.testing.assert_allclose(up[1:], image[:-1], atol=1e-6)
    np.testing.assert_allclose(up[0], image[0], atol=1e-6)  # clamp


def test_bilinear_sample_interpolates_fractional_offsets() -> None:
    ramp = np.tile(np.arange(8, dtype=np.float32)[None, :], (4, 1))
    sampled = preview._bilinear_sample(ramp, 0.0, 0.5)
    np.testing.assert_allclose(
        sampled[0, :6], [0.5, 1.5, 2.5, 3.5, 4.5, 5.5], atol=1e-5
    )


def test_radius_constant_changes_local_contrast() -> None:
    constants = preview.parse_profile_constants(BUNDLE_SHADER.read_text("utf-8"))
    atlas = preview.load_atlas_array(BUNDLE_ATLAS)
    rng = np.random.default_rng(11)
    pixels = rng.random((40, 60, 3), dtype=np.float32)
    lut = preview.lut3d_from_atlas(atlas, core.lut_row_for_profile(15))
    const = dict(constants[15])
    base = preview.simulate_pixels(15, pixels, lut, const, game_resolution=(1366, 768))
    wider = dict(const)
    wider["RADIUS"] = 2.0
    expanded = preview.simulate_pixels(
        15, pixels, lut, wider, game_resolution=(1366, 768)
    )
    assert np.abs(base - expanded).mean() > 0.001


def test_game_resolution_changes_simulated_output() -> None:
    constants = preview.parse_profile_constants(BUNDLE_SHADER.read_text("utf-8"))
    atlas = preview.load_atlas_array(BUNDLE_ATLAS)
    rng = np.random.default_rng(12)
    pixels = rng.random((72, 128, 3), dtype=np.float32)
    lut = preview.lut3d_from_atlas(atlas, core.lut_row_for_profile(15))
    const = constants[15]
    native = preview.simulate_pixels(
        15, pixels, lut, const, game_resolution=(1366, 768)
    )
    half = preview.simulate_pixels(
        15, pixels, lut, const, game_resolution=(683, 384)
    )
    double = preview.simulate_pixels(
        15, pixels, lut, const, game_resolution=(2732, 1536)
    )
    assert np.abs(native - half).mean() > 0.001
    assert np.abs(native - double).mean() > 0.0005


def test_render_preview_passes_game_resolution() -> None:
    result = preview.render_preview(
        15,
        MAP_HEIGHTS,
        BUNDLE_ATLAS,
        BUNDLE_SHADER,
        max_width=256,
        game_resolution="1920x1080",
    )
    assert result["game_resolution"] == (1920, 1080)
    with pytest.raises(preview.PreviewError):
        preview.render_preview(
            15,
            MAP_HEIGHTS,
            BUNDLE_ATLAS,
            BUNDLE_SHADER,
            max_width=256,
            game_resolution="0x0",
        )


def test_cli_preview_accepts_resolucao(tmp_path, capsys) -> None:
    import multilut_ctl

    output = tmp_path / "preview.png"
    code = multilut_ctl.main(
        [
            "preview",
            "3",
            "--shader",
            str(BUNDLE_SHADER),
            "--atlas",
            str(BUNDLE_ATLAS),
            "--resolucao",
            "1600x900",
            "--saida",
            str(output),
        ]
    )
    assert code == 0
    assert "1600x900" in capsys.readouterr().out
