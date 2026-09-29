#!/usr/bin/env python3
"""Unit tests for multilut_scopes (Insurgency scope zoom via theaters)."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from multilut_core import MultiLUTError
import multilut_scopes as scopes


class ComputeFovTests(unittest.TestCase):
    def test_seven_to_twelve(self):
        # 10 * (7/12) = 5.8333 -> 5.83
        self.assertAlmostEqual(scopes.compute_scope_fov(10.0, 7.0, 12.0), 5.83)

    def test_identity_when_target_equals_current(self):
        self.assertAlmostEqual(scopes.compute_scope_fov(10.0, 7.0, 7.0), 10.0)

    def test_four_to_eight(self):
        # 12 * (4/8) = 6.0
        self.assertAlmostEqual(scopes.compute_scope_fov(12.0, 4.0, 8.0), 6.0)

    def test_rejects_target_above_limit(self):
        with self.assertRaises(MultiLUTError):
            scopes.compute_scope_fov(10.0, 7.0, scopes.MAX_TARGET + 0.5)

    def test_rejects_target_below_one(self):
        with self.assertRaises(MultiLUTError):
            scopes.compute_scope_fov(10.0, 7.0, 0.5)

    def test_rejects_nonpositive_currents(self):
        with self.assertRaises(MultiLUTError):
            scopes.compute_scope_fov(0.0, 7.0, 12.0)
        with self.assertRaises(MultiLUTError):
            scopes.compute_scope_fov(10.0, 0.0, 12.0)

    def test_rejects_non_numeric(self):
        with self.assertRaises(MultiLUTError):
            scopes.compute_scope_fov("dez", 7.0, 12.0)


class BuildTheaterTests(unittest.TestCase):
    def test_contains_base_chain(self):
        text = scopes.build_theater(12.0, scopes.DEFAULT_OPTICS)
        for base in scopes.THEATER_BASE_CHAIN:
            self.assertIn(f'"#base" "{base}"', text)

    def test_seven_x_values_at_twelve(self):
        text = scopes.build_theater(12.0, ["optic_scope_7x"])
        self.assertIn('"fov_wpn_scope"\t\t\t\t"5.83"', text)
        self.assertIn('"fov_wpn_ironsight"\t\t\t"37"', text)
        self.assertIn('"fov_wpn_focus"\t\t\t\t"43"', text)
        self.assertIn('"optic_scope_7x"', text)

    def test_integer_fov_format(self):
        # Elcan 14 * (4/8) = 7 -> inteiro sem casas decimais
        text = scopes.build_theater(8.0, ["optic_elcan"])
        self.assertIn('"fov_wpn_scope"\t\t\t\t"7"', text)

    def test_only_selected_optics(self):
        text = scopes.build_theater(12.0, ["optic_scope_7x"])
        self.assertNotIn('"optic_elcan"', text)
        self.assertNotIn('"optic_po4x24"', text)

    def test_empty_selection_rejected(self):
        with self.assertRaises(MultiLUTError):
            scopes.build_theater(12.0, [])

    def test_unknown_optic_rejected(self):
        with self.assertRaises(MultiLUTError):
            scopes.build_theater(12.0, ["optic_inexistente"])

    def test_target_out_of_range_rejected(self):
        with self.assertRaises(MultiLUTError):
            scopes.build_theater(15.0, ["optic_scope_7x"])
        with self.assertRaises(MultiLUTError):
            scopes.build_theater("abc", ["optic_scope_7x"])


class ApplyRevertTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.game = Path(self.tmp.name) / "insurgency"
        (self.game / "scripts" / "theaters").mkdir(parents=True)
        (self.game / "cfg").mkdir(parents=True)

    def tearDown(self):
        self.tmp.cleanup()

    def test_apply_creates_theater(self):
        path = scopes.apply_zoom(self.game, 12.0, ["optic_scope_7x", "optic_scope_mk4"])
        self.assertTrue(path.is_file())
        self.assertTrue(scopes.is_applied(self.game))
        self.assertAlmostEqual(scopes.applied_target(self.game), 12.0)
        text = path.read_text(encoding="utf-8")
        self.assertIn('"optic_scope_7x"', text)
        self.assertIn('"optic_scope_mk4"', text)

    def test_apply_overwrites_existing(self):
        scopes.apply_zoom(self.game, 12.0, ["optic_scope_7x"])
        scopes.apply_zoom(self.game, 9.0, ["optic_scope_7x"])
        self.assertAlmostEqual(scopes.applied_target(self.game), 9.0)

    def test_apply_requires_valid_dir(self):
        with self.assertRaises(MultiLUTError):
            scopes.apply_zoom(self.tmp.name + "/vazio", 12.0, ["optic_scope_7x"])

    def test_revert_removes_theater_and_autoexec(self):
        scopes.apply_zoom(self.game, 12.0, ["optic_scope_7x"])
        scopes.set_autoexec_zoom(self.game, True)
        changed = scopes.revert_zoom(self.game)
        self.assertTrue(changed)
        self.assertFalse(scopes.is_applied(self.game))
        self.assertFalse(scopes.autoexec_zoom_enabled(self.game))
        # segunda reversão não tem mais o que fazer
        self.assertFalse(scopes.revert_zoom(self.game))

    def test_rejects_invalid_target_on_apply(self):
        with self.assertRaises(MultiLUTError):
            scopes.apply_zoom(self.game, 20.0, ["optic_scope_7x"])


class AutoexecTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.game = Path(self.tmp.name) / "insurgency"
        (self.game / "cfg").mkdir(parents=True)
        self.autoexec = self.game / "cfg" / "autoexec.cfg"
        self.autoexec.write_text(
            '// config pessoal do jogador\nvolume 0.8\n', encoding="utf-8"
        )

    def tearDown(self):
        self.tmp.cleanup()

    def test_add_and_remove_block(self):
        scopes.set_autoexec_zoom(self.game, True)
        text = self.autoexec.read_text(encoding="utf-8")
        self.assertIn(scopes.AUTOEXEC_LINE, text)
        self.assertIn("volume 0.8", text)  # conteúdo do usuário preservado
        self.assertTrue(scopes.autoexec_zoom_enabled(self.game))

        scopes.set_autoexec_zoom(self.game, False)
        text = self.autoexec.read_text(encoding="utf-8")
        self.assertNotIn(scopes.AUTOEXEC_LINE, text)
        self.assertIn("volume 0.8", text)
        self.assertFalse(scopes.autoexec_zoom_enabled(self.game))

    def test_add_is_idempotent(self):
        scopes.set_autoexec_zoom(self.game, True)
        scopes.set_autoexec_zoom(self.game, True)
        text = self.autoexec.read_text(encoding="utf-8")
        self.assertEqual(text.count(scopes.AUTOEXEC_LINE), 1)

    def test_creates_missing_autoexec(self):
        self.autoexec.unlink()
        scopes.set_autoexec_zoom(self.game, True)
        self.assertTrue(scopes.autoexec_zoom_enabled(self.game))

    def test_missing_autoexec_means_disabled(self):
        self.autoexec.unlink()
        self.assertFalse(scopes.autoexec_zoom_enabled(self.game))


class FindGameDirsTests(unittest.TestCase):
    def test_finds_install_under_steam_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            steam = Path(tmp) / "steam"
            game = steam / "steamapps" / "common" / "insurgency2" / "insurgency"
            (game / "scripts").mkdir(parents=True)
            found = scopes.find_game_dirs(roots=[steam])
            self.assertIn(game, found)

    def test_finds_install_in_vdf_library(self):
        with tempfile.TemporaryDirectory() as tmp:
            steam = Path(tmp) / "steam"
            (steam / "steamapps").mkdir(parents=True)
            (steam / "steamapps" / "libraryfolders.vdf").write_text(
                '"libraryfolders"\n{\n\t"1"\n\t{\n\t\t"path"\t\t"' + tmp.replace("\\", "/")
                + '/disk2"\n\t}\n}\n',
                encoding="utf-8",
            )
            disk2 = Path(tmp) / "disk2"
            game = disk2 / "steamapps" / "common" / "insurgency2" / "insurgency"
            (game / "scripts").mkdir(parents=True)
            found = scopes.find_game_dirs(roots=[steam])
            self.assertIn(game, found)

    def test_ignores_empty_dirs(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(scopes.find_game_dirs(roots=[tmp]), [])


class NormalizeConfigTests(unittest.TestCase):
    def test_defaults(self):
        data = scopes.normalize_scope_config(None)
        self.assertEqual(data["target"], scopes.MAX_TARGET)
        self.assertEqual(tuple(data["optics"]), scopes.DEFAULT_OPTICS)
        self.assertTrue(data["autoexec"])

    def test_clamps_target(self):
        data = scopes.normalize_scope_config({"target": 99})
        self.assertEqual(data["target"], scopes.MAX_TARGET)
        data = scopes.normalize_scope_config({"target": "3.5"})
        self.assertEqual(data["target"], 3.5)

    def test_filters_unknown_optics(self):
        data = scopes.normalize_scope_config(
            {"optics": ["optic_elcan", "lixo"], }
        )
        self.assertEqual(data["optics"], ["optic_elcan"])
        data = scopes.normalize_scope_config({"optics": ["lixo"]})
        self.assertEqual(tuple(data["optics"]), scopes.DEFAULT_OPTICS)

    def test_keeps_manual_game_dir(self):
        data = scopes.normalize_scope_config({"game_dir": " /jogos/insurgency "})
        self.assertEqual(data["game_dir"], "/jogos/insurgency")


if __name__ == "__main__":
    unittest.main()
