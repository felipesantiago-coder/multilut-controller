#!/usr/bin/env python3
"""Fundações do lote 1: histórico, versões, bibliotecas Steam e CLI."""

from pathlib import Path
import tempfile
import unittest
from unittest import mock

import multilut_core as core
import multilut_ctl as ctl


SHADER = """#ifndef ACTIVE_LUT_PROFILE
    #define ACTIVE_LUT_PROFILE 14
#endif
#define fLUT_TextureName \"MultiLut_Insurgency_Optimized.png\"
uniform float fLUT_DeepShadowRecovery = 0.5;
uniform float fLUT_SceneBrightness = 0.0;
uniform float fLUT_ColorSeparation = 0.1;
technique MultiLUT { pass Test { } }
"""


def _write_shader(directory: Path, profile: int = 14) -> Path:
    text = SHADER.replace(
        "#define ACTIVE_LUT_PROFILE 14", f"#define ACTIVE_LUT_PROFILE {profile}"
    )
    path = directory / "MultiLUT_Insurgency_Optimized.fx"
    path.write_text(text, encoding="utf-8")
    return path


class HomeSandboxTestCase(unittest.TestCase):
    """Base que redireciona o HOME para um diretório temporário."""

    def setUp(self) -> None:
        self._patcher = mock.patch("pathlib.Path.home", return_value=None)
        home_patcher = mock.patch(
            "pathlib.Path.home",
            new=lambda: self.home,
        )
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.home = Path(self._tmp.name)
        home_patcher.start()
        self.addCleanup(home_patcher.stop)


class HistoryTests(HomeSandboxTestCase):
    def test_append_and_read_roundtrip(self):
        core.append_history({"profile_id": 1, "profile_name": "Buhriz", "origin": "cli"})
        core.append_history({"profile_id": 14, "profile_name": "Competitivo neutro", "origin": "manual"})
        entries = core.read_history(limit=10)
        self.assertEqual(len(entries), 2)
        self.assertEqual(entries[0]["profile_id"], 14)  # mais recente primeiro
        for entry in entries:
            self.assertIn("ts", entry)

    def test_clear_history(self):
        core.append_history({"profile_id": 1, "origin": "manual"})
        core.clear_history()
        self.assertEqual(core.read_history(), [])

    def test_history_trims_to_keep(self):
        path = core.history_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        lines = [f'{{"profile_id": {i}, "origin": "manual"}}' for i in range(2000)]
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        core.append_history({"profile_id": 99, "origin": "cli"})
        kept = path.read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(kept), 1000)
        self.assertIn('"profile_id": 99', kept[-1])

    def test_read_history_skips_corrupted_lines(self):
        path = core.history_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            "lixo\n"
            '{"profile_id": 5, "origin": "manual"}\n'
            "\n",
            encoding="utf-8",
        )
        entries = core.read_history()
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["profile_id"], 5)


class VersionTests(unittest.TestCase):
    def test_newer_versions(self):
        self.assertTrue(core.compare_versions("v1.9.0", "1.8.0"))
        self.assertTrue(core.compare_versions("1.8.1", "v1.8.0"))
        self.assertTrue(core.compare_versions("v2.0", "1.9.9"))
        self.assertTrue(core.compare_versions("v1.10.0", "1.9.99"))

    def test_same_or_older(self):
        self.assertFalse(core.compare_versions("1.8.0", "v1.8.0"))
        self.assertFalse(core.compare_versions("v1.7.9", "1.8.0"))

    def test_unparseable_version_is_never_newer(self):
        self.assertFalse(core.compare_versions("beta", "1.8.0"))
        self.assertIsNone(core.normalize_version("sem-numeros"))


class SteamLibraryTests(HomeSandboxTestCase):
    def _make_library(self, root: Path) -> Path:
        apps = root / "steamapps"
        apps.mkdir(parents=True, exist_ok=True)
        return apps

    def test_libraries_from_vdf(self):
        steam_root = self.home / ".steam/steam"
        apps = self._make_library(steam_root)
        games = self.home / "discos/jogos"
        self._make_library(games)
        (apps / "libraryfolders.vdf").write_text(
            '"libraries"\n'
            "{\n"
            '\t"0"\n\t{\n'
            f'\t\t"path"\t\t"{steam_root}"\n'
            "\t}\n"
            '\t"1"\n\t{\n'
            f'\t\t"path"\t\t"{games}"\n'
            "\t}\n"
            "}\n",
            encoding="utf-8",
        )
        libraries = core.steam_libraries()
        self.assertIn(apps, libraries)
        self.assertIn(games / "steamapps", libraries)

    def test_game_roots_nested_layout(self):
        steam_root = self.home / ".steam/steam"
        apps = self._make_library(steam_root)
        nested = apps / "common/insurgency2/insurgency"
        nested.mkdir(parents=True, exist_ok=True)
        roots = core.find_game_roots()
        self.assertIn(nested, roots)

    def test_configured_game_dir_comes_first(self):
        steam_root = self.home / ".steam/steam"
        apps = self._make_library(steam_root)
        discovered = apps / "common/insurgency"
        discovered.mkdir(parents=True, exist_ok=True)
        chosen = self.home / "outra/instalacao"
        chosen.mkdir(parents=True, exist_ok=True)
        config = core.load_config()
        config["game_dir"] = str(chosen)
        core.save_config(config)
        roots = core.find_game_roots()
        self.assertEqual(roots[0], chosen)

    def test_console_log_found(self):
        steam_root = self.home / ".steam/steam"
        apps = self._make_library(steam_root)
        nested = apps / "common/insurgency2/insurgency"
        nested.mkdir(parents=True, exist_ok=True)
        (nested / "console.log").write_text("Loading map \"buhriz\"\n", encoding="utf-8")
        self.assertEqual(core.find_console_log(), nested / "console.log")


class CliTests(HomeSandboxTestCase):
    def test_match_profile_by_id_name_and_slug(self):
        self.assertEqual(ctl.match_profile("14").name, "Competitivo neutro")
        self.assertEqual(ctl.match_profile("buhriz").id, 1)
        self.assertEqual(ctl.match_profile("Dry Canal").id, 4)
        self.assertEqual(ctl.match_profile("drycanal").id, 4)
        self.assertEqual(ctl.match_profile("SINJAR").id, 8)
        self.assertEqual(ctl.match_profile("verticality").id, 10)

    def test_match_profile_rejects_unknown(self):
        with self.assertRaises(core.MultiLUTError):
            ctl.match_profile("999")
        with self.assertRaises(core.MultiLUTError):
            ctl.match_profile("nao-existe")
        with self.assertRaises(core.MultiLUTError):
            ctl.match_profile("")

    def test_set_updates_shader_and_history(self):
        shader = _write_shader(Path(self.home), profile=14)
        exit_code = ctl.main(["set", "buhriz", "--shader", str(shader)])
        self.assertEqual(exit_code, 0)
        self.assertEqual(core.read_active_profile(shader), 1)
        entries = core.read_history()
        self.assertEqual(entries[0]["origin"], "cli")
        self.assertEqual(entries[0]["profile_id"], 1)

    def test_set_same_profile_is_noop(self):
        shader = _write_shader(Path(self.home), profile=1)
        exit_code = ctl.main(["set", "buhriz", "--shader", str(shader)])
        self.assertEqual(exit_code, 0)
        self.assertEqual(core.read_active_profile(shader), 1)

    def test_active_and_status(self):
        shader = _write_shader(Path(self.home), profile=8)
        self.assertEqual(ctl.main(["active", "--shader", str(shader)]), 0)
        self.assertEqual(ctl.main(["status", "--shader", str(shader)]), 0)

    def test_list_runs(self):
        shader = _write_shader(Path(self.home), profile=14)
        self.assertEqual(ctl.main(["list", "--shader", str(shader)]), 0)

    def test_resolve_shader_falls_back_to_config(self):
        shader = _write_shader(Path(self.home), profile=14)
        config = core.load_config()
        config["shader_path"] = str(shader)
        core.save_config(config)
        self.assertEqual(ctl.resolve_shader(None), shader)


if __name__ == "__main__":
    unittest.main()
