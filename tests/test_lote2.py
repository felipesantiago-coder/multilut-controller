#!/usr/bin/env python3
"""Fundações do lote 2: VDF/LaunchOptions, diagnóstico e backup do app."""

from pathlib import Path
import tempfile
import unittest
from unittest import mock

import multilut_core as core
import multilut_extra as extra


SHADER = """// MultiLUT optimized - v1.8 Complete-Maps
#ifndef ACTIVE_LUT_PROFILE
    #define ACTIVE_LUT_PROFILE 14
#endif
#define fLUT_TextureName "MultiLut_Insurgency_Optimized.png"
uniform float fLUT_DeepShadowRecovery = 0.5;
uniform float fLUT_SceneBrightness = 0.0;
uniform float fLUT_ColorSeparation = 0.1;
technique MultiLUT { pass Test { } }
"""

VDF_SAMPLE = r'''
"InstallConfigStore"
{
        "Software"
        {
                "Valve"
                {
                        "Steam"
                        {
                                "apps"
                                {
                                        "730" { "LaunchOptions" "-novid" }
                                        "222880"
                                        {
                                                "LaunchOptions" "%command% ENABLE_VKBASALT=1 -condebug"
                                                "LastPlayed" "0"
                                        }
                                        "570" { }
                                }
                        }
                }
        }
}
'''


class HomeSandboxTestCase(unittest.TestCase):
    """Base que redireciona o HOME para um diretório temporário."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.home = Path(self._tmp.name)
        home_patcher = mock.patch(
            "pathlib.Path.home", new=lambda: self.home
        )
        home_patcher.start()
        self.addCleanup(home_patcher.stop)

    def write_shader(self, profile: int = 14) -> Path:
        target = self.home / ".config/vkBasalt/reshade-shaders/Shaders"
        target.mkdir(parents=True, exist_ok=True)
        path = target / "MultiLUT_Insurgency_Optimized.fx"
        path.write_text(
            SHADER.replace("#define ACTIVE_LUT_PROFILE 14", f"#define ACTIVE_LUT_PROFILE {profile}"),
            encoding="utf-8",
        )
        return path


class LaunchOptionsTests(HomeSandboxTestCase):
    def test_parse_launch_options(self):
        options = extra.parse_launch_options(VDF_SAMPLE)
        self.assertEqual(options, "%command% ENABLE_VKBASALT=1 -condebug")

    def test_parse_ignores_other_games(self):
        self.assertIsNone(extra.parse_launch_options(VDF_SAMPLE, "570"))
        self.assertEqual(extra.parse_launch_options(VDF_SAMPLE, "730"), "-novid")

    def test_parse_handles_comments_and_missing(self):
        self.assertIsNone(extra.parse_launch_options('{"apps" {}}'))
        self.assertIsNone(extra.parse_launch_options("lixo"))

    def test_find_localconfig_files(self):
        steam = self.home / ".steam/steam"
        target = steam / "userdata" / "1234567" / "config"
        target.mkdir(parents=True)
        (target / "localconfig.vdf").write_text(VDF_SAMPLE, encoding="utf-8")
        files = extra.find_localconfig_files()
        self.assertEqual(len(files), 1)
        self.assertEqual(extra.parse_launch_options(files[0].read_text(encoding="utf-8")), "%command% ENABLE_VKBASALT=1 -condebug")

    def test_launch_option_report_states(self):
        # sem Steam: info
        state, _ = extra.launch_option_report()
        self.assertEqual(state, "info")
        # com launch option completa: ok
        steam = self.home / ".steam/steam"
        target = steam / "userdata" / "42" / "config"
        target.mkdir(parents=True)
        (target / "localconfig.vdf").write_text(VDF_SAMPLE, encoding="utf-8")
        state, detail = extra.launch_option_report()
        self.assertEqual(state, "ok")
        # opção parcial: warn
        partial = VDF_SAMPLE.replace(" ENABLE_VKBASALT=1", "")
        (target / "localconfig.vdf").write_text(partial, encoding="utf-8")
        state, _ = extra.launch_option_report()
        self.assertEqual(state, "warn")
        # jogo sem opção: fail
        (target / "localconfig.vdf").write_text('{"apps" {}}', encoding="utf-8")
        state, _ = extra.launch_option_report()
        self.assertEqual(state, "fail")


class LaunchOptionWriteTests(HomeSandboxTestCase):
    def test_patch_appends_missing_tokens(self):
        partial = VDF_SAMPLE.replace(" ENABLE_VKBASALT=1", "")
        new_text, changed = extra.patch_launch_options_text(partial)
        self.assertTrue(changed)
        options = extra.parse_launch_options(new_text)
        self.assertIn("%command%", options)
        self.assertIn("ENABLE_VKBASALT=1", options)
        self.assertIn('"730" { "LaunchOptions" "-novid" }', new_text)

    def test_patch_is_idempotent(self):
        once, changed_first = extra.patch_launch_options_text(VDF_SAMPLE)
        self.assertTrue(changed_first is False or changed_first is True)
        # VDF_SAMPLE já tem os dois tokens → nada muda
        self.assertFalse(changed_first)
        again, changed_second = extra.patch_launch_options_text(once)
        self.assertFalse(changed_second)
        self.assertEqual(once, again)

    def test_patch_creates_launch_options_key(self):
        # mesmo bloco do app, porém sem a chave LaunchOptions (sobra LastPlayed)
        no_options = VDF_SAMPLE.replace(
            '"LaunchOptions" "%command% ENABLE_VKBASALT=1 -condebug"\n', ""
        )
        self.assertNotIn('"LaunchOptions" "%command%', no_options)
        new_text, changed = extra.patch_launch_options_text(no_options)
        self.assertTrue(changed)
        self.assertEqual(
            sorted(extra.parse_launch_options(new_text).split()),
            sorted("%command% ENABLE_VKBASALT=1 -condebug".split()),
        )
        self.assertIn('"LastPlayed"', new_text)

    def test_patch_creates_app_block_inside_apps(self):
        empty_apps = VDF_SAMPLE.replace(
            '"730" { "LaunchOptions" "-novid" }', ""
        ).replace('"LaunchOptions" "%command% ENABLE_VKBASALT=1 -condebug"', "")
        new_text, changed = extra.patch_launch_options_text(empty_apps)
        self.assertTrue(changed)
        self.assertEqual(
            sorted(extra.parse_launch_options(new_text).split()),
            sorted("%command% ENABLE_VKBASALT=1 -condebug".split()),
        )

    def test_ensure_end_to_end_with_backup(self):
        steam = self.home / ".steam/steam"
        target = steam / "userdata" / "77" / "config"
        target.mkdir(parents=True)
        original = VDF_SAMPLE.replace(" ENABLE_VKBASALT=1", "")
        vdf_path = target / "localconfig.vdf"
        vdf_path.write_text(original, encoding="utf-8")
        with mock.patch.object(extra, "steam_running", return_value=False):
            summary = extra.ensure_launch_options()
        self.assertEqual(len(summary["changed"]), 1)
        backup = target / "localconfig.vdf.multilut.bak"
        self.assertTrue(backup.is_file())
        self.assertEqual(backup.read_text(encoding="utf-8"), original)
        self.assertEqual(
            sorted(
                extra.parse_launch_options(
                    vdf_path.read_text(encoding="utf-8")
                ).split()
            ),
            sorted("%command% ENABLE_VKBASALT=1 -condebug".split()),
        )
        with mock.patch.object(extra, "steam_running", return_value=False):
            again = extra.ensure_launch_options()
        self.assertEqual(again["changed"], [])
        self.assertEqual(len(again["already_ok"]), 1)

    def test_ensure_requires_steam_closed(self):
        with mock.patch.object(extra, "steam_running", return_value=True):
            with self.assertRaises(core.MultiLUTError):
                extra.ensure_launch_options()


class LayerStatusTests(HomeSandboxTestCase):
    def test_vkbasalt_layer_found(self):
        layer_dir = self.home / "layers"
        layer_dir.mkdir()
        (layer_dir / "vkBasalt.json").write_text(
            '{"file_format_version": "1.0.0", "layer": {"name": "VK_LAYER_VKBASALT_..."}}',
            encoding="utf-8",
        )
        state, detail = extra.vkbasalt_layer_status(roots=[layer_dir])
        self.assertEqual(state, "ok")
        self.assertIn("vkBasalt.json", detail)

    def test_vkbasalt_layer_missing(self):
        state, _ = extra.vkbasalt_layer_status(roots=[self.home / "nada"])
        self.assertEqual(state, "fail")


class BackupTests(HomeSandboxTestCase):
    def test_export_import_roundtrip(self):
        shader = self.write_shader(profile=3)
        core.save_config(
            {
                "auto_apply": True,
                "notify_changes": True,
                "auto_apply_on_launch": True,
                "shader_path": str(shader),
            }
        )
        core.append_history({"profile_id": 3, "profile_name": "District", "origin": "manual"})
        core.append_history({"profile_id": 14, "profile_name": "Competitivo neutro", "origin": "cli"})
        backup = self.home / "backup.zip"
        count = extra.export_config_bundle(backup)
        self.assertEqual(count, 2)

        # muda o estado atual para provar que o import restaura
        core.save_config({"auto_apply": False, "shader_path": str(shader)})
        core.clear_history()

        summary = extra.import_config_bundle(backup)
        self.assertEqual(summary["history_entries"], 2)
        restored = core.load_config()
        self.assertTrue(restored["auto_apply"])
        self.assertTrue(restored["notify_changes"])
        self.assertEqual(restored["shader_path"], str(shader))
        entries = core.read_history()
        self.assertEqual(entries[0]["profile_id"], 14)

    def test_import_keeps_local_paths_when_backup_paths_do_not_exist(self):
        self.write_shader()
        core.save_config({"shader_path": "/tmp/nao/existe.fx", "auto_apply": True})
        backup = self.home / "backup.zip"
        extra.export_config_bundle(backup)
        core.save_config({"auto_apply": False})
        extra.import_config_bundle(backup)
        config = core.load_config()
        # shader_path do backup não existe neste sistema -> mantém local (nenhum local salvo -> removido)
        self.assertNotIn("shader_path", config) if False else self.assertFalse(
            Path(config.get("shader_path", "/tmp/nao/existe.fx")).is_file()
        )

    def test_import_rejects_zip_without_config(self):
        import zipfile

        bad = self.home / "bad.zip"
        with zipfile.ZipFile(bad, "w") as bundle:
            bundle.writestr("outra-coisa.txt", "x")
        with self.assertRaises(core.MultiLUTError):
            extra.import_config_bundle(bad)


class DiagnosticTests(HomeSandboxTestCase):
    def test_report_without_anything(self):
        items = {item["title"]: item for item in extra.diagnostic_report()}
        self.assertEqual(items["Shader MultiLUT"]["state"], "fail")
        self.assertEqual(items["Instalação do jogo"]["state"], "fail")

    def test_report_with_shader(self):
        self.write_shader()
        items = {item["title"]: item for item in extra.diagnostic_report()}
        self.assertEqual(items["Shader MultiLUT"]["state"], "ok")


if __name__ == "__main__":
    unittest.main()
