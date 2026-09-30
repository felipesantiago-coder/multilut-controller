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

    def test_per_weapon_scope_blocks_at_twelve(self):
        """Armas com fov_wpn_scope próprio precisam do override por arma."""
        text = scopes.build_theater(12.0, ["optic_scope_7x", "optic_scope_mk4"])
        for optic_id in ("optic_scope_7x", "optic_scope_mk4"):
            for weapon_id, _fov in scopes.OPTIC_WEAPON_FOVS[optic_id]:
                self.assertIn(f'"{weapon_id}"', text, weapon_id)
        # todas as 7 armas recebem o mesmo FOV escalado (10 * 7/12 = 5.83);
        # linhas por arma têm 5 tabs de recuo, o topo tem 4
        self.assertEqual(
            text.count('\t\t\t\t\t"fov_wpn_scope"\t\t\t\t"5.83"'), 7
        )

    def test_per_weapon_scale_follows_target(self):
        # 10 * (7/3) = 23.33 -> per-weapon acompanha o alvo
        text = scopes.build_theater(3.0, ["optic_scope_7x"])
        self.assertIn('\t\t\t\t\t"fov_wpn_scope"\t\t\t\t"23.33"', text)

    def test_optics_without_per_weapon_scope_have_no_weapon_block(self):
        # Elcan/PO/Aimpoint não definem fov_wpn_scope por arma no dump
        text = scopes.build_theater(12.0, ["optic_elcan", "optic_po4x24",
                                           "optic_2xaimpoint"])
        self.assertNotIn('"weapon_mosin"', text)
        self.assertNotIn('"weapon_m40a1"', text)

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
        scopes.set_listenserver_zoom(self.game, True)
        changed = scopes.revert_zoom(self.game)
        self.assertTrue(changed)
        self.assertFalse(scopes.is_applied(self.game))
        self.assertFalse(scopes.autoexec_zoom_enabled(self.game))
        self.assertFalse(scopes.listenserver_zoom_enabled(self.game))
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


class ListenserverTests(unittest.TestCase):
    """Ativação por cfg/listenserver.cfg (executado a cada partida local)."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.game = Path(self.tmp.name) / "insurgency"
        (self.game / "cfg").mkdir(parents=True)
        self.listenserver = self.game / "cfg" / "listenserver.cfg"

    def tearDown(self):
        self.tmp.cleanup()

    def test_creates_file_with_block(self):
        self.assertFalse(scopes.listenserver_zoom_enabled(self.game))
        scopes.set_listenserver_zoom(self.game, True)
        text = self.listenserver.read_text(encoding="utf-8")
        self.assertIn(scopes.LISTENSERVER_LINE, text)
        self.assertIn(scopes.AUTOEXEC_BEGIN, text)
        self.assertTrue(scopes.listenserver_zoom_enabled(self.game))

    def test_existing_content_preserved(self):
        self.listenserver.write_text(
            "// config do servidor do jogador\nsv_cheats 0\n", encoding="utf-8"
        )
        scopes.set_listenserver_zoom(self.game, True)
        text = self.listenserver.read_text(encoding="utf-8")
        self.assertIn("sv_cheats 0", text)
        self.assertIn(scopes.LISTENSERVER_LINE, text)

        scopes.set_listenserver_zoom(self.game, False)
        text = self.listenserver.read_text(encoding="utf-8")
        self.assertNotIn(scopes.LISTENSERVER_LINE, text)
        self.assertIn("sv_cheats 0", text)  # conteúdo do jogador permanece
        self.assertFalse(scopes.listenserver_zoom_enabled(self.game))

    def test_add_is_idempotent(self):
        scopes.set_listenserver_zoom(self.game, True)
        scopes.set_listenserver_zoom(self.game, True)
        text = self.listenserver.read_text(encoding="utf-8")
        self.assertEqual(text.count(scopes.LISTENSERVER_LINE), 1)

    def test_disable_removes_file_created_by_us(self):
        scopes.set_listenserver_zoom(self.game, True)
        scopes.set_listenserver_zoom(self.game, False)
        self.assertFalse(self.listenserver.exists())
        self.assertFalse(scopes.listenserver_zoom_enabled(self.game))

    def test_revert_zoom_removes_listenserver_block(self):
        scopes.apply_zoom(self.game, 12.0, ["optic_scope_7x"])
        scopes.set_listenserver_zoom(self.game, True)
        self.assertTrue(scopes.revert_zoom(self.game))
        self.assertFalse(scopes.listenserver_zoom_enabled(self.game))


class LaunchOptionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.steam = Path(self.tmp.name) / "steam"
        (self.steam / "config").mkdir(parents=True)
        self.localconfig = self.steam / "config" / "localconfig.vdf"
        # desliga a checagem real de processos do Steam nos testes
        self._original_running = scopes.steam_running
        scopes.steam_running = lambda: False

    def tearDown(self):
        scopes.steam_running = self._original_running
        self.tmp.cleanup()

    def write_localconfig(self, text: str) -> None:
        self.localconfig.write_text(text, encoding="utf-8")

    APP_TEMPLATE = (
        '"Software"\n{\n\t"Valve"\n\t{\n\t\t"Steam"\n\t\t{\n'
        '\t\t\t"apps"\n\t\t\t{\n\t\t\t\t"222880"\n\t\t\t\t{\n'
        '%s\t\t\t\t}\n\t\t\t}\n\t\t}\n\t}\n}\n'
    )

    def test_inserts_when_key_missing(self):
        self.write_localconfig(self.APP_TEMPLATE % "")
        changed = scopes.set_launch_option(True, roots=[self.steam])
        self.assertEqual(changed, [self.localconfig])
        text = self.localconfig.read_text(encoding="utf-8")
        self.assertIn(scopes.LAUNCH_OPTION, text)
        self.assertTrue(scopes.launch_option_installed(roots=[self.steam]))

    def test_appends_to_existing_options(self):
        self.write_localconfig(
            self.APP_TEMPLATE % '\t\t\t\t       "LaunchOptions"         "-novid -condebug"\n'
        )
        scopes.set_launch_option(True, roots=[self.steam])
        text = self.localconfig.read_text(encoding="utf-8")
        self.assertIn('-novid -condebug ' + scopes.LAUNCH_OPTION, text)

    def test_replaces_existing_theater_override(self):
        self.write_localconfig(
            self.APP_TEMPLATE % '\t\t\t\t       "LaunchOptions"         "+mp_theater_override outro"\n'
        )
        scopes.set_launch_option(True, roots=[self.steam])
        text = self.localconfig.read_text(encoding="utf-8")
        self.assertIn(scopes.LAUNCH_OPTION, text)
        self.assertNotIn("outro", text)

    def test_add_is_idempotent(self):
        self.write_localconfig(self.APP_TEMPLATE % "")
        scopes.set_launch_option(True, roots=[self.steam])
        first = self.localconfig.read_text(encoding="utf-8")
        changed = scopes.set_launch_option(True, roots=[self.steam])
        self.assertEqual(changed, [])
        self.assertEqual(first, self.localconfig.read_text(encoding="utf-8"))

    def test_remove_keeps_other_options(self):
        self.write_localconfig(
            self.APP_TEMPLATE
            % ('\t\t\t\t"LaunchOptions"\t\t"-novid %s"\n' % scopes.LAUNCH_OPTION)
        )
        changed = scopes.set_launch_option(False, roots=[self.steam])
        self.assertEqual(changed, [self.localconfig])
        text = self.localconfig.read_text(encoding="utf-8")
        self.assertNotIn("mp_theater_override", text)
        self.assertIn("-novid", text)
        self.assertFalse(scopes.launch_option_installed(roots=[self.steam]))

    def test_file_without_app_block_is_untouched(self):
        self.write_localconfig('"Software"\n{\n\t"Valve"\n\t{\n\t}\n}\n')
        changed = scopes.set_launch_option(True, roots=[self.steam])
        self.assertEqual(changed, [])
        self.assertFalse(scopes.launch_option_installed(roots=[self.steam]))

    def test_userdata_localconfigs_are_patched(self):
        user_cfg = self.steam / "userdata" / "12345" / "config"
        user_cfg.mkdir(parents=True)
        user_file = user_cfg / "localconfig.vdf"
        user_file.write_text(self.APP_TEMPLATE % "", encoding="utf-8")
        self.write_localconfig(self.APP_TEMPLATE % "")
        changed = scopes.set_launch_option(True, roots=[self.steam])
        self.assertIn(self.localconfig, changed)
        self.assertIn(user_file, changed)
        self.assertTrue(scopes.launch_option_installed(roots=[self.steam]))

    def test_backup_is_created(self):
        original = self.APP_TEMPLATE % ""
        self.write_localconfig(original)
        scopes.set_launch_option(True, roots=[self.steam])
        backup = self.localconfig.with_name(
            self.localconfig.name + ".multilut.bak"
        )
        self.assertTrue(backup.is_file())
        self.assertEqual(backup.read_text(encoding="utf-8"), original)

    def test_refuses_when_steam_is_running(self):
        scopes.steam_running = lambda: True
        self.write_localconfig(self.APP_TEMPLATE % "")
        with self.assertRaises(MultiLUTError):
            scopes.set_launch_option(True, roots=[self.steam])
        # nada foi gravado
        self.assertEqual(
            self.localconfig.read_text(encoding="utf-8"),
            self.APP_TEMPLATE % "",
        )


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
        self.assertTrue(data["launch_option"])

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


class QuickTargetsTests(unittest.TestCase):
    def test_contains_requested_options(self):
        self.assertEqual(
            scopes.QUICK_TARGETS, (3.0, 5.0, 10.0, scopes.MAX_TARGET)
        )

    def test_all_within_valid_range(self):
        for mag in scopes.QUICK_TARGETS:
            self.assertGreaterEqual(mag, scopes.MIN_TARGET)
            self.assertLessEqual(mag, scopes.MAX_TARGET)


class LooksLikeGameDirTests(unittest.TestCase):
    def test_accepts_dir_with_two_source_markers(self):
        with tempfile.TemporaryDirectory() as tmp:
            game = Path(tmp) / "insurgency"
            (game / "maps").mkdir(parents=True)
            (game / "cfg").mkdir()
            self.assertTrue(scopes.looks_like_game_dir(game))

    def test_accepts_dir_without_scripts(self):
        # Instalação com conteúdo empacotado em VPK: nada de scripts/ solto.
        with tempfile.TemporaryDirectory() as tmp:
            game = Path(tmp) / "insurgency"
            for marker in ("maps", "materials", "models", "sound"):
                (game / marker).mkdir(parents=True)
            self.assertTrue(scopes.looks_like_game_dir(game))
            self.assertFalse((game / "scripts").exists())

    def test_accepts_folder_named_insurgency(self):
        with tempfile.TemporaryDirectory() as tmp:
            game = Path(tmp) / "Insurgency"
            game.mkdir()
            self.assertTrue(scopes.looks_like_game_dir(game))

    def test_rejects_dir_with_single_marker(self):
        with tempfile.TemporaryDirectory() as tmp:
            other = Path(tmp) / "outro"
            (other / "maps").mkdir(parents=True)
            self.assertFalse(scopes.looks_like_game_dir(other))

    def test_rejects_missing_or_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertFalse(scopes.looks_like_game_dir(Path(tmp) / "nada"))
            arquivo = Path(tmp) / "arquivo.txt"
            arquivo.write_text("x", encoding="utf-8")
            self.assertFalse(scopes.looks_like_game_dir(arquivo))


class FindGameDirsWithoutScriptsTests(unittest.TestCase):
    def test_finds_install_without_scripts_folder(self):
        with tempfile.TemporaryDirectory() as tmp:
            steam = Path(tmp) / "steam"
            game = steam / "steamapps" / "common" / "insurgency2" / "insurgency"
            for marker in ("maps", "cfg", "materials", "models"):
                (game / marker).mkdir(parents=True)
            found = scopes.find_game_dirs(roots=[steam])
            self.assertIn(game, found)

    def test_apply_creates_missing_scripts_theaters(self):
        with tempfile.TemporaryDirectory() as tmp:
            game = Path(tmp) / "insurgency"
            (game / "maps").mkdir(parents=True)
            (game / "cfg").mkdir()
            path = scopes.apply_zoom(game, 12.0, ["optic_scope_7x"])
            self.assertTrue(path.is_file())
            self.assertTrue((game / "scripts" / "theaters").is_dir())


class FindGameDirAboveTests(unittest.TestCase):
    def test_resolves_download_scripts_to_game_dir(self):
        # Caminho real relatado por um usuário: scripts solto dentro de download/
        with tempfile.TemporaryDirectory() as tmp:
            game = Path(tmp) / "insurgency2" / "insurgency"
            (game / "download" / "scripts").mkdir(parents=True)
            (game / "maps").mkdir()
            (game / "cfg").mkdir()
            found = scopes.find_game_dir_above(game / "download" / "scripts")
            self.assertEqual(found, game)

    def test_none_when_outside_any_game(self):
        with tempfile.TemporaryDirectory() as tmp:
            deep = Path(tmp) / "a" / "b" / "c" / "d" / "e" / "f"
            deep.mkdir(parents=True)
            self.assertIsNone(scopes.find_game_dir_above(deep))


if __name__ == "__main__":
    unittest.main()
