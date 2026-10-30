#!/usr/bin/env python3
"""Fundações do lote 5: regras aprendidas, launcher com pre-checagens e
notificações com desfazer."""

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import multilut_core as core
import multilut_extra as extra

try:
    import multilut_daemon as daemon_mod
except (ImportError, ValueError, SystemExit):  # sem PyGObject no ambiente
    daemon_mod = None


SHADER = """#ifndef ACTIVE_LUT_PROFILE
    #define ACTIVE_LUT_PROFILE 14
#endif
#define fLUT_TextureName "MultiLut_Insurgency_Optimized.png"
uniform float fLUT_DeepShadowRecovery = 0.5;
uniform float fLUT_SceneBrightness = 0.0;
uniform float fLUT_ColorSeparation = 0.1;
technique MultiLUT { pass Test { } }
"""


class Lote5TestCase(unittest.TestCase):
    """Sandbox de HOME + XDG_RUNTIME_DIR + XDG_STATE_HOME por teste."""

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

    def write_shader(self, profile: int = 14) -> Path:
        target = self.home / ".config/vkBasalt/reshade-shaders/Shaders"
        target.mkdir(parents=True, exist_ok=True)
        path = target / "MultiLUT_Insurgency_Optimized.fx"
        path.write_text(
            SHADER.replace(
                "#define ACTIVE_LUT_PROFILE 14",
                f"#define ACTIVE_LUT_PROFILE {profile}",
            ),
            encoding="utf-8",
        )
        return path


class MapRulesCoreTests(Lote5TestCase):
    def test_normalize_token(self):
        self.assertEqual(core.normalize_map_token(' "Sinjar_Night" '), "sinjar_night")
        self.assertEqual(core.normalize_map_token(None), "")
        self.assertEqual(core.normalize_map_token(""), "")

    def test_set_get_remove_rule(self):
        config = {}
        self.assertTrue(core.set_map_rule(config, "Tell", 22))
        self.assertEqual(core.map_rules(config), {"tell": 22})
        # atualização
        self.assertTrue(core.set_map_rule(config, "tell", 15))
        self.assertEqual(core.map_rules(config), {"tell": 15})
        self.assertTrue(core.remove_map_rule(config, " TELL "))
        self.assertEqual(core.map_rules(config), {})
        self.assertFalse(core.remove_map_rule(config, "tell"))

    def test_regras_invalidas_sao_descartadas(self):
        config = {
            "map_rules": {
                "tell": 22,
                "sinjar": 999,  # perfil inexistente
                "  ": 14,  # token vazio
                "market": "não-numérico",
                42: 15,  # chave não-texto
            }
        }
        self.assertEqual(core.map_rules(config), {"tell": 22})

    def test_regra_vence_casamento_por_slug(self):
        # sinjar_night casaria com Sinjar (8) por slug; a regra aprendida vence
        config = {"map_rules": {"sinjar_night": 15}}
        profile = core.match_map_profile("sinjar_night", core.map_rules(config))
        self.assertEqual(profile.id, 15)
        # sem regra, comportamento antigo preservado
        self.assertEqual(core.match_map_profile("sinjar_night").id, 8)

    def test_regra_com_perfil_inexistente_cai_no_slug(self):
        config = {"map_rules": {"tell": 999}}
        profile = core.match_map_profile("tell", core.map_rules(config))
        self.assertEqual(profile.id, 22)

    def test_match_sem_regras_compativel(self):
        self.assertIsNone(core.match_map_profile(None))
        self.assertIsNone(core.match_map_profile("mapa_inexistente"))
        self.assertEqual(core.match_map_profile("tell").id, 22)

    def test_config_roundtrip(self):
        config = {}
        core.set_map_rule(config, "market_coop", 17)
        core.save_config(config)
        loaded = core.load_config()
        self.assertEqual(core.map_rules(loaded), {"market_coop": 17})


class DaemonRulesAndUndoTests(Lote5TestCase):
    @unittest.skipIf(daemon_mod is None, "multilut_daemon indisponível (sem PyGObject)")
    def test_apply_usa_regra_aprendida(self):
        shader = self.write_shader(profile=8)
        core.save_config(
            {
                "auto_map_switch": True,
                "shader_path": str(shader),
                "notify_changes": False,
                "map_rules": {"sinjar_night": 15},
            }
        )
        pilot = daemon_mod.DaemonPilot()
        result = pilot.apply_map_token("sinjar_night")
        self.assertIsNotNone(result)
        self.assertEqual(result["profile_id"], 15)
        self.assertEqual(core.read_active_profile(shader), 15)
        entries = core.read_history(limit=3)
        self.assertEqual(entries[0]["origin"], "daemon")
        self.assertEqual(entries[0]["profile_id"], 15)

    @unittest.skipIf(daemon_mod is None, "multilut_daemon indisponível (sem PyGObject)")
    def test_apply_profile_id_desfaz(self):
        shader = self.write_shader(profile=14)
        core.save_config(
            {"auto_map_switch": True, "shader_path": str(shader), "notify_changes": False}
        )
        pilot = daemon_mod.DaemonPilot()
        changed = pilot.apply_map_token("tell")  # 14 -> 22
        self.assertEqual(changed["profile_id"], 22)
        undone = pilot.apply_profile_id(14, origin="undo")
        self.assertIsNotNone(undone)
        self.assertEqual(core.read_active_profile(shader), 14)
        entries = core.read_history(limit=3)
        self.assertEqual(entries[0]["origin"], "undo")
        self.assertEqual(entries[0]["previous"], 22)

    @unittest.skipIf(daemon_mod is None, "multilut_daemon indisponível (sem PyGObject)")
    def test_apply_profile_id_ignorado_quando_ja_ativo(self):
        shader = self.write_shader(profile=14)
        core.save_config({"shader_path": str(shader), "notify_changes": False})
        pilot = daemon_mod.DaemonPilot()
        self.assertIsNone(pilot.apply_profile_id(14, origin="undo"))

    def test_notify_send_args_sem_desfazer(self):
        argv = daemon_mod.notify_send_args("Título", "Corpo")
        self.assertEqual(argv[-2:], ["Título", "Corpo"])
        self.assertNotIn("--wait", argv)
        self.assertIn("-a", argv)
        self.assertIn("MultiLUT Controller", argv)

    def test_notify_send_args_com_desfazer(self):
        argv = daemon_mod.notify_send_args("Título", "Corpo", undo_profile_id=14)
        self.assertIn("--action=undo=Desfazer", argv)
        self.assertIn("--wait", argv)
        self.assertEqual(argv[-2:], ["Título", "Corpo"])

    @unittest.skipIf(daemon_mod is None, "multilut_daemon indisponível (sem PyGObject)")
    def test_notificacao_com_desfazer_usa_argv_correto(self):
        shader = self.write_shader(profile=14)
        core.save_config(
            {
                "auto_map_switch": True,
                "shader_path": str(shader),
                "notify_changes": True,
            }
        )
        pilot = daemon_mod.DaemonPilot()
        recorded: list[list[str]] = []

        def fake_run(argv, **kwargs):
            recorded.append(list(argv))
            return mock.Mock(stdout="undo\n", returncode=0)

        class SyncThread:
            """Roda o alvo na hora: elimina a corrida da thread de --wait."""

            def __init__(self, target, args, daemon=False):
                self._target, self._args = target, args

            def start(self):
                self._target(*self._args)

        with mock.patch.object(daemon_mod.shutil, "which", return_value="/usr/bin/notify-send"):
            with mock.patch.object(daemon_mod.subprocess, "run", side_effect=fake_run):
                with mock.patch.object(daemon_mod.threading, "Thread", SyncThread):
                    with mock.patch.object(daemon_mod, "GLib", mock.Mock()) as glib:
                        pilot.apply_map_token("tell")
        idle = glib.idle_add
        self.assertEqual(len(recorded), 1)
        argv = recorded[0]
        self.assertIn("--action=undo=Desfazer", argv)
        self.assertIn("--wait", argv)
        self.assertIn("Competitivo neutro → Tell", argv[-1])
        self.assertTrue(idle.called)
        # o alvo do desfazer é o perfil anterior (14)
        idle_args = idle.call_args[0]
        self.assertEqual(idle_args[1], 14)

    @unittest.skipIf(daemon_mod is None, "multilut_daemon indisponível (sem PyGObject)")
    def test_notificacao_desligada_nao_invoca_notify_send(self):
        shader = self.write_shader(profile=14)
        core.save_config(
            {
                "auto_map_switch": True,
                "shader_path": str(shader),
                "notify_changes": False,
            }
        )
        pilot = daemon_mod.DaemonPilot()
        with mock.patch.object(daemon_mod.shutil, "which", return_value="/usr/bin/notify-send") as which:
            pilot.apply_map_token("tell")
        self.assertFalse(which.called)


class LaunchPrechecksTests(Lote5TestCase):
    def _patch_all_ok(self):
        layer = mock.patch.object(
            extra, "vkbasalt_layer_status", return_value=("ok", "camada presente")
        )
        conf = mock.patch.object(
            extra, "vkbasalt_config_status", return_value=("ok", "config ok")
        )
        option = mock.patch.object(
            extra, "launch_option_report", return_value=("ok", "opção completa")
        )
        game = mock.patch.object(core, "is_game_running", return_value=False)
        daemon = mock.patch.object(extra, "query_daemon", return_value=None)
        for patcher in (layer, conf, option, game, daemon):
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_tudo_ok_nao_bloqueia(self):
        self._patch_all_ok()
        shader = self.write_shader(profile=14)
        checks = extra.launch_prechecks(
            {"auto_map_switch": True}, shader_path=shader
        )
        blocked = [item for item in checks if not item["ok"] and item["critical"]]
        self.assertEqual(blocked, [])
        titles = {item["title"] for item in checks}
        self.assertIn("Jogo", titles)
        self.assertIn("Piloto automático por mapa", titles)

    def test_shader_invalido_e_critico(self):
        self._patch_all_ok()
        checks = extra.launch_prechecks(
            {"auto_map_switch": True},
            shader_path=self.home / "inexistente.fx",
        )
        blocked = [item for item in checks if not item["ok"] and item["critical"]]
        self.assertTrue(any("shader" in item["title"].lower() for item in blocked))

    def test_launch_option_faltando_e_critico(self):
        self._patch_all_ok()
        shader = self.write_shader(profile=14)
        with mock.patch.object(
            extra,
            "launch_option_report",
            return_value=("fail", "Insurgency sem opção de inicialização no Steam."),
        ):
            checks = extra.launch_prechecks(
                {"auto_map_switch": True}, shader_path=shader
            )
        blocked = [item for item in checks if not item["ok"] and item["critical"]]
        self.assertTrue(
            any("Opção de inicialização" in item["title"] for item in blocked)
        )

    def test_camada_vkbasalt_ausente_e_critica(self):
        self._patch_all_ok()
        shader = self.write_shader(profile=14)
        with mock.patch.object(
            extra,
            "vkbasalt_layer_status",
            return_value=("fail", "vkBasalt não encontrado"),
        ):
            checks = extra.launch_prechecks(
                {"auto_map_switch": True}, shader_path=shader
            )
        blocked = [item for item in checks if not item["ok"] and item["critical"]]
        self.assertTrue(
            any("camada Vulkan" in item["title"] for item in blocked)
        )

    def test_piloto_desligado_nao_e_critico(self):
        self._patch_all_ok()
        shader = self.write_shader(profile=14)
        checks = extra.launch_prechecks({"auto_map_switch": False}, shader_path=shader)
        blocked = [item for item in checks if not item["ok"] and item["critical"]]
        self.assertEqual(blocked, [])
        pilot = next(item for item in checks if item["title"].startswith("Piloto"))
        self.assertFalse(pilot["ok"])

    def test_jogo_aberto_aparece_como_info(self):
        self._patch_all_ok()
        shader = self.write_shader(profile=14)
        with mock.patch.object(core, "is_game_running", return_value=True):
            checks = extra.launch_prechecks(
                {"auto_map_switch": True}, shader_path=shader
            )
        game = next(item for item in checks if item["title"] == "Jogo")
        self.assertTrue(game["ok"])
        self.assertIn("aberto", game["detail"])


class MapRulesDoctorTests(Lote5TestCase):
    def test_sem_regras(self):
        state, detail = extra.map_rules_status()
        self.assertEqual(state, "info")
        self.assertIn("nenhuma", detail)

    def test_com_regras(self):
        config = {}
        core.set_map_rule(config, "tell", 22)
        core.set_map_rule(config, "sinjar_night", 15)
        core.save_config(config)
        state, detail = extra.map_rules_status()
        self.assertEqual(state, "ok")
        self.assertIn("2 regra(s)", detail)
        self.assertIn("tell → Tell", detail)
        self.assertIn("sinjar_night → Recuperação competitiva", detail)

    def test_item_no_diagnostico(self):
        titles = {item["title"] for item in extra.diagnostic_report()}
        self.assertIn("Regras aprendidas por mapa", titles)


class CliRulesAndLaunchTests(Lote5TestCase):
    def setUp(self) -> None:
        super().setUp()
        import multilut_ctl

        self.ctl = multilut_ctl

    def test_rules_listagem(self):
        config = {}
        core.set_map_rule(config, "tell", 22)
        core.save_config(config)
        parser = self.ctl.build_parser()
        with mock.patch("sys.stdout") as out:
            code = parser.parse_args(["rules"]).func(
                parser.parse_args(["rules"])
            )
        self.assertEqual(code, 0)

    def test_rules_remove(self):
        config = {}
        core.set_map_rule(config, "tell", 22)
        core.save_config(config)
        parser = self.ctl.build_parser()
        args = parser.parse_args(["rules", "remove", "TELL"])
        code = args.func(args)
        self.assertEqual(code, 0)
        self.assertEqual(core.map_rules(core.load_config()), {})
        args = parser.parse_args(["rules", "remove", "tell"])
        self.assertEqual(args.func(args), 1)

    def test_launch_bloqueia_sem_pre_requisito(self):
        self.write_shader(profile=14)
        with mock.patch.object(core, "is_game_running", return_value=False):
            with mock.patch.object(
                extra,
                "launch_option_report",
                return_value=("fail", "sem opção"),
            ):
                with mock.patch.object(
                    extra, "vkbasalt_layer_status", return_value=("ok", "ok")
                ):
                    with mock.patch.object(
                        extra, "vkbasalt_config_status", return_value=("ok", "ok")
                    ):
                        parser = self.ctl.build_parser()
                        args = parser.parse_args(["launch"])
                        code = args.func(args)
        self.assertEqual(code, 1)

    def test_launch_force_abre(self):
        self.write_shader(profile=14)
        launched = mock.patch.object(core, "launch_game")
        with launched as launch:
            with mock.patch.object(core, "is_game_running", return_value=False):
                with mock.patch.object(
                    extra,
                    "launch_option_report",
                    return_value=("fail", "sem opção"),
                ):
                    with mock.patch.object(
                        extra, "vkbasalt_layer_status", return_value=("ok", "ok")
                    ):
                        with mock.patch.object(
                            extra, "vkbasalt_config_status", return_value=("ok", "ok")
                        ):
                            parser = self.ctl.build_parser()
                            args = parser.parse_args(["launch", "--force"])
                            code = args.func(args)
        self.assertEqual(code, 0)
        self.assertTrue(launch.called)


if __name__ == "__main__":
    unittest.main()
