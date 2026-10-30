#!/usr/bin/env python3
"""Fundações do lote 6: bandeja (tray), importação .3dl e gerador de LUT."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import multilut_core as core
import multilut_tray as tray_mod

pytest_skip_numpy = None  # marcado abaixo

try:
    import numpy as np  # noqa: E402
    from PIL import Image  # noqa: E402

    import multilut_atlas as atlas  # noqa: E402

    NUMPY_OK = True
except (ImportError, ValueError):  # pragma: no cover
    NUMPY_OK = False


class Lote6TestCase(unittest.TestCase):
    """Sandbox de HOME + XDG_STATE_HOME por teste (histórico isolado)."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.home = Path(self._tmp.name)
        home_patcher = mock.patch(
            "pathlib.Path.home",
            new=lambda: self.home,
        )
        home_patcher.start()
        self.addCleanup(home_patcher.stop)
        env_patcher = mock.patch.dict(
            os.environ,
            {
                "XDG_RUNTIME_DIR": str(self.home / "run"),
                "XDG_STATE_HOME": str(self.home / "state"),
            },
        )
        env_patcher.start()
        self.addCleanup(env_patcher.stop)
        (self.home / "run").mkdir(parents=True, exist_ok=True)


class TrayMenuTests(Lote6TestCase):
    def test_menu_basico(self):
        items = tray_mod.build_menu_entries(recent_profiles=[], pilot_on=True)
        kinds = [item[0] for item in items]
        self.assertTrue(all(kind == "action" for kind in kinds))
        labels = [item[1] for item in items]
        self.assertIn("Próximo perfil", labels)
        self.assertIn("Perfil anterior", labels)
        self.assertIn("Pausar piloto", labels)
        self.assertIn("Abrir janela", labels)
        self.assertIn("Sair", labels)
        actions = [item[2] for item in items]
        self.assertIn("app.next-profile", actions)
        self.assertIn("app.toggle-pilot", actions)

    def test_menu_com_recentes(self):
        items = tray_mod.build_menu_entries(
            recent_profiles=[(22, "Tell"), (14, "Competitivo neutro")],
            pilot_on=False,
        )
        profiles = [item for item in items if item[0] == "profile"]
        self.assertEqual(
            profiles,
            [
                ("profile", 22, "22 — Tell"),
                ("profile", 14, "14 — Competitivo neutro"),
            ],
        )
        actions = [item[2] for item in items if item[0] == "action" and item[2] != "disabled"]
        for item in items:
            if item[0] == "profile" and item[1] == 22:
                self.assertEqual(item[2], "22 — Tell")
        self.assertTrue(any(item[0] == "profile" for item in items))
        labels = [item[1] for item in items]
        self.assertIn("Retomar piloto", labels)
        self.assertNotIn("Pausar piloto", labels)

    def test_recentes_do_historico_distintos(self):
        for profile_id, origin in ((22, "daemon"), (14, "manual"), (22, "daemon"), (7, "cli")):
            core.append_history(
                {
                    "profile_id": profile_id,
                    "profile_name": core.PROFILE_BY_ID[profile_id].name,
                    "origin": origin,
                }
            )
        recent = tray_mod.recent_profiles(limit=3)
        self.assertEqual(recent, [(7, "Panj"), (22, "Tell"), (14, "Competitivo neutro")])

    def test_recentes_ignora_ids_invalidos(self):
        core.append_history({"profile_id": "x", "profile_name": "???"})
        core.append_history({"profile_id": 999, "profile_name": "fantasma"})
        core.append_history({"profile_id": 15, "profile_name": "Recuperação competitiva"})
        self.assertEqual(
            tray_mod.recent_profiles(),
            [(15, "Recuperação competitiva")],
        )

    def test_icon_path_encontra_o_asset(self):
        path = tray_mod.tray_icon_path()
        self.assertIsNotNone(path)
        self.assertTrue(Path(path).is_file())

    def test_supported_sem_gi_retorna_bool(self):
        self.assertIsInstance(tray_mod.tray_supported(), bool)


@unittest.skipUnless(NUMPY_OK, "numpy/Pillow indisponíveis")
class Parse3dlTests(Lote6TestCase):
    CUBE_2 = (
        "# identidade 2^3\n"
        'TITLE "Teste"\n'
        "LUT_3D_SIZE 2\n"
        "0 0 0\n1 0 0\n0 1 0\n1 1 0\n0 0 1\n1 0 1\n0 1 1\n1 1 1\n"
    )

    def _cube_entries(self) -> list[tuple[int, int, int]]:
        # ordem vermelho-rápido: (r, g, b) varia r primeiro
        return [
            (r, g, b) for b in range(2) for g in range(2) for r in range(2)
        ]

    def test_3dl_azul_rapido_identidade(self):
        # ordem azul-rápido (Lustre): para r, para g, para b
        rows = [
            (r, g, b) for r in range(2) for g in range(2) for b in range(2)
        ]
        text_lines = ["LUT_3D_INPUT_SIZE 2"]
        for r, g, b in rows:
            text_lines.append(f"{r} {g} {b}")
        text = "\n".join(text_lines) + "\n"
        lut = atlas.parse_3dl_text(text)
        self.assertEqual(lut["size"], 2)
        self.assertEqual(lut["format"], "3dl")
        self.assertEqual(lut["order"], "blue-fastest")
        cube = atlas.parse_cube_text(self.CUBE_2)
        np.testing.assert_allclose(lut["table"], cube["table"], atol=1e-6)

    def test_3dl_vermelho_rapido_detectado(self):
        text_lines = ["LUT_3D_INPUT_SIZE 2"]
        for r, g, b in self._cube_entries():
            text_lines.append(f"{r} {g} {b}")
        text = "\n".join(text_lines) + "\n"
        lut = atlas.parse_3dl_text(text)
        self.assertEqual(lut["order"], "red-fastest")
        cube = atlas.parse_cube_text(self.CUBE_2)
        np.testing.assert_allclose(lut["table"], cube["table"], atol=1e-6)

    def test_3dl_escala_inteira_0_1023(self):
        rows = [(r * 1023, g * 1023, b * 1023) for b in range(2) for g in range(2) for r in range(2)]
        text_lines = ["# Lustre 10-bit", "LUT_3D_INPUT_SIZE 2"]
        for r, g, b in rows:
            text_lines.append(f"{r} {g} {b}")
        text = "\n".join(text_lines) + "\n"
        lut = atlas.parse_3dl_text(text)
        self.assertAlmostEqual(float(lut["table"][1, 1, 1][0]), 1.0, places=5)

    def test_3dl_incompleto_e_sem_cabecalho(self):
        with self.assertRaises(core.MultiLUTError):
            atlas.parse_3dl_text("LUT_3D_INPUT_SIZE 2\n0 0 0\n")
        with self.assertRaises(core.MultiLUTError):
            atlas.parse_3dl_text("0 0 0\n1 1 1\n")

    def test_parse_lut_file_dispatch(self):
        tmp = Path(self.home)
        cube_path = tmp / "x.cube"
        cube_path.write_text(self.CUBE_2, encoding="utf-8")
        self.assertEqual(atlas.parse_lut_file(cube_path)["size"], 2)
        rows = [(r, g, b) for r in range(2) for g in range(2) for b in range(2)]
        three = tmp / "y.3dl"
        three.write_text(
            "LUT_3D_INPUT_SIZE 2\n"
            + "\n".join(f"{r} {g} {b}" for r, g, b in rows)
            + "\n",
            encoding="utf-8",
        )
        self.assertEqual(atlas.parse_lut_file(three)["format"], "3dl")
        bad = tmp / "z.lut"
        bad.write_text(self.CUBE_2, encoding="utf-8")
        with self.assertRaises(core.MultiLUTError):
            atlas.parse_lut_file(bad)


@unittest.skipUnless(NUMPY_OK, "numpy/Pillow indisponíveis")
class GeneratorTests(Lote6TestCase):
    def test_parametros_neutros_sao_identidade(self):
        table = atlas.apply_lut_params(atlas.identity_table(8))
        np.testing.assert_allclose(table, atlas.identity_table(8), atol=1e-6)
        strip = atlas.generate_lut_image()
        self.assertEqual(strip.size, (atlas.STRIP_WIDTH, atlas.ATLAS_TILE))

    def test_brilho_aumenta_media_e_contraste_afasta(self):
        base = atlas.identity_table(8)
        bright = atlas.apply_lut_params(base, brightness=0.25)
        self.assertGreater(float(bright.mean()), float(base.mean()))
        contrast = atlas.apply_lut_params(base, contrast=1.4)
        self.assertGreater(float(contrast.std()), float(base.std()))

    def test_saturacao_zero_cinza_e_temperatura_desloca_canais(self):
        gray = atlas.apply_lut_params(atlas.identity_table(8), saturation=0.0)
        np.testing.assert_allclose(
            gray[..., 0], gray[..., 1], atol=1e-5
        )
        np.testing.assert_allclose(gray[..., 1], gray[..., 2], atol=1e-5)
        warm = atlas.apply_lut_params(atlas.identity_table(8), temperature=1.0)
        self.assertGreater(float(warm[..., 0].mean()), float(base := atlas.identity_table(8)[..., 0].mean()))
        self.assertLess(float(warm[..., 2].mean()), float(atlas.identity_table(8)[..., 2].mean()))

    def test_valores_sempre_em_0_1(self):
        table = atlas.apply_lut_params(
            atlas.identity_table(8), brightness=0.5, contrast=1.5,
            saturation=2.0, temperature=-1.0,
        )
        self.assertGreaterEqual(float(table.min()), 0.0)
        self.assertLessEqual(float(table.max()), 1.0)

    def test_preview_em_imagem(self):
        image = Image.new("RGB", (24, 16), (100, 120, 140))
        out = atlas.apply_params_to_image(image, brightness=0.2, saturation=0.5)
        self.assertEqual(out.size, (24, 16))
        self.assertEqual(out.mode, "RGB")
        original = np.asarray(image, dtype=np.int16)
        result = np.asarray(out, dtype=np.int16)
        self.assertGreater(int(result.mean()), int(original.mean()))

    def test_override_row_with_strip_grava_e_faz_backup(self):
        tmp = self.home / "atlas"
        tmp.mkdir(parents=True, exist_ok=True)
        target = tmp / "MultiLut_Insurgency_Optimized.png"
        rng = np.random.default_rng(7)
        data = rng.integers(0, 256, size=(core.ATLAS_ROWS * core.ATLAS_TILE, 1024, 3), dtype=np.uint8)
        Image.fromarray(data, "RGB").save(target)
        strip = atlas.generate_lut_image(brightness=0.4)
        info = atlas.override_row_with_strip(target, 3, strip, source="gerador (teste)")
        self.assertEqual(info["row"], 3)
        self.assertEqual(info["source"], "gerador (teste)")
        backup = Path(info["backup"])
        self.assertTrue(backup.is_file())
        reloaded = atlas.load_atlas_image(target)
        replaced_row = np.asarray(
            reloaded.crop((0, 3 * core.ATLAS_TILE, 1024, 4 * core.ATLAS_TILE))
        )
        original_row = np.asarray(
            atlas.load_atlas_image(backup).crop((0, 3 * core.ATLAS_TILE, 1024, 4 * core.ATLAS_TILE))
        )
        self.assertGreater(int(np.abs(replaced_row.astype(int) - original_row.astype(int)).max()), 0)
        # linha vizinha intacta
        other_row = np.asarray(
            reloaded.crop((0, 5 * core.ATLAS_TILE, 1024, 6 * core.ATLAS_TILE))
        )
        other_original = np.asarray(
            atlas.load_atlas_image(backup).crop((0, 5 * core.ATLAS_TILE, 1024, 6 * core.ATLAS_TILE))
        )
        np.testing.assert_array_equal(other_row, other_original)


if __name__ == "__main__":
    unittest.main()
