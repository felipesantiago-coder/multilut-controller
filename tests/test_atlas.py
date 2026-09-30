#!/usr/bin/env python3
"""Testes da reindexação e override do atlas v1.8 (multilut_atlas)."""

from __future__ import annotations

from pathlib import Path

import pytest

import multilut_core as core

pytest.importorskip("numpy")
pytest.importorskip("PIL")

import multilut_atlas as atlas  # noqa: E402
import numpy as np  # noqa: E402
from PIL import Image  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
BUNDLE_SHADER = REPO / "bundle/Shaders/MultiLUT_Insurgency_Optimized.fx"
BUNDLE_ATLAS = REPO / "bundle/Textures/MultiLut_Insurgency_Optimized.png"


CUBE_2 = """
# LUT sintetica 2^3 para teste
TITLE "Teste"
LUT_3D_SIZE 2
0 0 0
1 0 0
0 1 0
1 1 0
0 0 1
1 0 1
0 1 1
1 1 1
"""


def synthetic_atlas(path: Path, seed: int = 1) -> Path:
    """Atlas 1024x544 com pixels determinísticos por linha."""
    rng = np.random.default_rng(seed)
    data = rng.integers(0, 256, size=(544, 1024, 3), dtype=np.uint8)
    Image.fromarray(data, "RGB").save(path)
    return path


# ---------------------------------------------------------------------------
# Parser .cube
# ---------------------------------------------------------------------------
def test_parse_cube_red_fastest_order() -> None:
    cube = atlas.parse_cube_text(CUBE_2)
    assert cube["size"] == 2
    assert cube["title"] == "Teste"
    assert cube["input_range"] == (0.0, 1.0)
    table = cube["table"]
    assert table.shape == (2, 2, 2, 3)
    assert table[0, 0, 0].tolist() == [0, 0, 0]
    assert table[0, 0, 1].tolist() == [1, 0, 0]  # vermelho varia primeiro
    assert table[0, 1, 0].tolist() == [0, 1, 0]
    assert table[1, 0, 0].tolist() == [0, 0, 1]
    assert table[1, 1, 1].tolist() == [1, 1, 1]


def test_parse_cube_input_range() -> None:
    text = CUBE_2.replace("LUT_3D_SIZE 2", "LUT_3D_SIZE 2\nLUT_3D_INPUT_RANGE 0.0 2.0")
    cube = atlas.parse_cube_text(text)
    assert cube["input_range"] == (0.0, 2.0)
    np.testing.assert_allclose(cube["table"][1, 1, 1], [0.5, 0.5, 0.5], atol=1e-6)


def test_parse_cube_rejects_invalid_files() -> None:
    with pytest.raises(atlas.AtlasError, match="LUT 1D"):
        atlas.parse_cube_text("LUT_1D_SIZE 8\n")
    with pytest.raises(atlas.AtlasError, match="LUT_3D_SIZE"):
        atlas.parse_cube_text("0 0 0\n")
    with pytest.raises(atlas.AtlasError, match="incompleta"):
        atlas.parse_cube_text("LUT_3D_SIZE 2\n0 0 0\n")
    with pytest.raises(atlas.AtlasError, match="não reconhecida"):
        atlas.parse_cube_text(CUBE_2 + "1 2 3 4\n")
    with pytest.raises(atlas.AtlasError, match="fora do intervalo"):
        atlas.parse_cube_text("LUT_3D_SIZE 99999\n")


def test_parse_cube_file_missing(tmp_path) -> None:
    with pytest.raises(atlas.AtlasError, match="Não foi possível abrir"):
        atlas.parse_cube_file(tmp_path / "ausente.cube")


# ---------------------------------------------------------------------------
# Reamostragem e faixa do atlas
# ---------------------------------------------------------------------------
def test_resample_identity_and_corners() -> None:
    axis = np.arange(2, dtype=np.float32)
    r = np.broadcast_to(axis[None, None, :], (2, 2, 2))
    g = np.broadcast_to(axis[None, :, None], (2, 2, 2))
    b = np.broadcast_to(axis[:, None, None], (2, 2, 2))
    identity = np.stack((r, g, b), axis=-1).astype(np.float32)  # (b, g, r, rgb)
    out = atlas.resample_lut(identity, 32)
    assert out.shape == (32, 32, 32, 3)
    # cantos preservados
    np.testing.assert_allclose(out[0, 0, 0], [0, 0, 0], atol=1e-6)
    np.testing.assert_allclose(out[31, 0, 0], [0, 0, 1], atol=1e-6)
    np.testing.assert_allclose(out[0, 0, 31], [1, 0, 0], atol=1e-6)
    np.testing.assert_allclose(out[31, 31, 31], [1, 1, 1], atol=1e-6)
    # monotonicidade no eixo vermelho
    assert np.all(np.diff(out[0, 0, :, 0]) >= -1e-6)


def test_resample_passthrough_32() -> None:
    rng = np.random.default_rng(5)
    lut = rng.random((32, 32, 32, 3)).astype(np.float32)
    out = atlas.resample_lut(lut, 32)
    np.testing.assert_allclose(out, lut, atol=1e-7)


def test_strip_roundtrip_with_preview_decoder() -> None:
    import multilut_preview as preview

    rng = np.random.default_rng(9)
    lut = rng.random((32, 32, 32, 3)).astype(np.float32)
    cube = {"table": lut, "size": 32, "title": None, "input_range": (0.0, 1.0)}
    strip = atlas.strip_image_from_cube(cube)
    assert strip.size == (1024, 32)
    decoded = preview.lut3d_from_atlas(np.asarray(strip, dtype=np.float32) / 255.0, 0)
    np.testing.assert_allclose(decoded, lut, atol=1.0 / 255.0 + 1e-4)


def test_atlas_with_replaced_row_changes_only_target() -> None:
    cube = atlas.parse_cube_text(CUBE_2)
    strip = atlas.strip_image_from_cube(cube)
    source = atlas.load_atlas_image(BUNDLE_ATLAS)
    replaced = atlas.atlas_with_replaced_row(source, 3, strip)
    a_source = np.asarray(source)
    a_replaced = np.asarray(replaced)
    assert not np.array_equal(a_source[96:128], a_replaced[96:128])
    for row in (0, 1, 2, 4, 10, 16):
        np.testing.assert_array_equal(
            a_source[row * 32 : (row + 1) * 32],
            a_replaced[row * 32 : (row + 1) * 32],
        )


def test_atlas_with_replaced_row_validates() -> None:
    strip = Image.new("RGB", (1024, 32))
    source = atlas.load_atlas_image(BUNDLE_ATLAS)
    with pytest.raises(atlas.AtlasError, match="fora do atlas"):
        atlas.atlas_with_replaced_row(source, 17, strip)
    with pytest.raises(atlas.AtlasError, match="geometria inesperada"):
        atlas.atlas_with_replaced_row(source, 0, Image.new("RGB", (512, 32)))


# ---------------------------------------------------------------------------
# Override com .cube e restauração (arquivos reais, pasta temporária)
# ---------------------------------------------------------------------------
def test_override_row_with_cube_end_to_end(tmp_path) -> None:
    target = synthetic_atlas(tmp_path / "atlas.png")
    bundle_dir = tmp_path / "Textures"
    bundle_dir.mkdir()
    bundle_atlas = synthetic_atlas(bundle_dir / "MultiLut_Insurgency_Optimized.png", seed=99)
    cube_path = tmp_path / "minha.cube"
    cube_path.write_text(CUBE_2, encoding="utf-8")

    before = np.asarray(Image.open(target).convert("RGB"))
    info = atlas.override_row_with_cube(target, 3, cube_path)
    assert info["row"] == 3 and info["cube_size"] == 2
    assert Path(info["backup"]).is_file()

    after = np.asarray(Image.open(target).convert("RGB"))
    assert not np.array_equal(before[96:128], after[96:128])
    for row in (0, 5, 16):
        np.testing.assert_array_equal(before[row * 32 : (row + 1) * 32], after[row * 32 : (row + 1) * 32])
    assert core.validate_texture(target)[0]

    restored = atlas.restore_row_from_bundle(target, 3, tmp_path)
    assert restored["row"] == 3
    after_restore = np.asarray(Image.open(target).convert("RGB"))
    bundle_row = np.asarray(Image.open(bundle_atlas).convert("RGB"))[96:128]
    np.testing.assert_array_equal(after_restore[96:128], bundle_row)
    assert not np.array_equal(after_restore[96:128], after[96:128])


def test_restore_atlas_backup_roundtrip(tmp_path) -> None:
    target = synthetic_atlas(tmp_path / "atlas.png")
    cube_path = tmp_path / "minha.cube"
    cube_path.write_text(CUBE_2, encoding="utf-8")
    original = (tmp_path / "atlas.png").read_bytes()
    atlas.override_row_with_cube(target, 0, cube_path)
    modified = (tmp_path / "atlas.png").read_bytes()
    assert modified != original
    atlas.restore_atlas_backup(target)
    assert (tmp_path / "atlas.png").read_bytes() == original
    with pytest.raises(atlas.AtlasError, match="fora do atlas"):
        atlas.override_row_with_cube(target, 20, cube_path)


# ---------------------------------------------------------------------------
# Reindexação P_LUT_ROW
# ---------------------------------------------------------------------------
def test_parse_lut_row_map_bundle_shader() -> None:
    mapping = atlas.parse_lut_row_map(BUNDLE_SHADER.read_text("utf-8"))
    expected = {profile_id: profile_id for profile_id in range(25)}
    expected.update(core.LUT_ROW_BY_PROFILE)
    assert mapping == expected


def test_parse_lut_row_map_explicit_chain() -> None:
    text = "\n".join(
        ["#if ACTIVE_LUT_PROFILE == 0", "    #define P_LUT_ROW 5"]
        + [
            f"#elif ACTIVE_LUT_PROFILE == {i}\n    #define P_LUT_ROW {i % 17}"
            for i in range(1, 25)
        ]
        + ["#endif"]
    )
    mapping = atlas.parse_lut_row_map(text)
    assert mapping[0] == 5
    assert mapping[17] == 0
    assert len(mapping) == 25


def test_parse_lut_row_map_rejects_out_of_range() -> None:
    text = "#if ACTIVE_LUT_PROFILE == 0\n    #define P_LUT_ROW 42\n#endif"
    with pytest.raises(atlas.AtlasError, match="fora do atlas"):
        atlas.parse_lut_row_map(text)


def test_write_and_reindex_roundtrip() -> None:
    text = BUNDLE_SHADER.read_text("utf-8")
    mapping = atlas.parse_lut_row_map(text)
    updated = atlas.write_lut_row_map(text, {**mapping, 5: 9, 0: 4})
    # ACTIVE_LUT_PROFILE intacto
    assert core.PROFILE_PATTERN.search(updated)
    confirmed = atlas.parse_lut_row_map(updated)
    assert confirmed[5] == 9 and confirmed[0] == 4
    assert confirmed[18] == 12 and confirmed[3] == 3  # demais preservados
    # blocos de constantes intactos
    assert "#define P_CHROMA     0.80" in updated
    assert updated.count("#define P_LUT_ROW") == 26  # 25 perfis + fallback #else


def test_reindex_profile_applies_and_resets(tmp_path) -> None:
    shader = tmp_path / "shader.fx"
    shader.write_text(BUNDLE_SHADER.read_text("utf-8"), encoding="utf-8")
    info = atlas.reindex_profile(shader, 15, 2)
    assert info["changed"] and info["previous_row"] == 15
    text = shader.read_text("utf-8")
    assert atlas.parse_lut_row_map(text)[15] == 2
    assert core.read_active_profile(shader) == core.read_active_profile(BUNDLE_SHADER)
    assert core.backup_path(shader).is_file()
    # idempotente
    again = atlas.reindex_profile(shader, 15, 2)
    assert not again["changed"]
    # restauração do padrão
    reset = atlas.reset_lut_row_map(shader)
    assert reset["changed"]
    assert atlas.parse_lut_row_map(shader.read_text("utf-8")) == {
        profile_id: core.lut_row_for_profile(profile_id) for profile_id in range(25)
    }


def test_reindex_profile_validates_inputs(tmp_path) -> None:
    shader = tmp_path / "shader.fx"
    shader.write_text(BUNDLE_SHADER.read_text("utf-8"), encoding="utf-8")
    with pytest.raises(core.MultiLUTError, match="intervalo"):
        atlas.reindex_profile(shader, 30, 0)
    with pytest.raises(atlas.AtlasError, match="fora do atlas"):
        atlas.reindex_profile(shader, 5, 17)


def test_row_owner_profiles() -> None:
    mapping = {i: i for i in range(25)}
    mapping.update(core.LUT_ROW_BY_PROFILE)
    owners = atlas.row_owner_profiles(mapping)
    assert owners[3] == [3, 17, 23]
    assert owners[13] == [13, 19, 24]
    assert owners[9] == [9]
    assert len(owners) == core.ATLAS_ROWS


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def test_cli_rows_reindex_and_atlas(tmp_path, capsys) -> None:
    import multilut_ctl

    shader = tmp_path / "shader.fx"
    shader.write_text(BUNDLE_SHADER.read_text("utf-8"), encoding="utf-8")
    atlas_target = synthetic_atlas(tmp_path / "atlas.png")
    cube_path = tmp_path / "troca.cube"
    cube_path.write_text(CUBE_2, encoding="utf-8")

    assert multilut_ctl.main(["rows", "--shader", str(shader)]) == 0
    assert "linha  3" in capsys.readouterr().out

    assert multilut_ctl.main(
        ["reindex", "20", "7", "--shader", str(shader)]
    ) == 0
    assert atlas.parse_lut_row_map(shader.read_text("utf-8"))[20] == 7
    assert multilut_ctl.main(["reindex", "--reset", "--shader", str(shader)]) == 0
    mapping = atlas.parse_lut_row_map(shader.read_text("utf-8"))
    assert mapping == {i: core.lut_row_for_profile(i) for i in range(25)}

    # sem perfil/linha: erro amigável (código 1, não exceção)
    assert multilut_ctl.main(["reindex", "--shader", str(shader)]) == 1
    assert "--reset" in capsys.readouterr().err

    assert multilut_ctl.main(
        ["atlas", "5", str(cube_path), "--atlas", str(atlas_target)]
    ) == 0
    assert "reamostrada para 32³" in capsys.readouterr().out
    assert core.backup_path(atlas_target).is_file()

