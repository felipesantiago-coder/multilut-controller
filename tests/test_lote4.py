#!/usr/bin/env python3
"""Fundações do lote 4: daemon, autostart, atualização, relatório e ajuda."""

import json
import os
import socket
import tempfile
import threading
import unittest
import zipfile
from pathlib import Path
from unittest import mock

import multilut_core as core
import multilut_extra as extra

try:
    import multilut_daemon as daemon_mod
except (ImportError, ValueError, SystemExit):  # sem PyGObject no ambiente
    daemon_mod = None

try:
    import multilut_ctl
except ImportError:  # pragma: no cover - nunca deve faltar
    multilut_ctl = None


SHADER = """#ifndef ACTIVE_LUT_PROFILE
    #define ACTIVE_LUT_PROFILE 14
#endif
#define fLUT_TextureName \"MultiLut_Insurgency_Optimized.png\"
uniform float fLUT_DeepShadowRecovery = 0.5;
uniform float fLUT_SceneBrightness = 0.0;
uniform float fLUT_ColorSeparation = 0.1;
technique MultiLUT { pass Test { } }
"""


class Lote4TestCase(unittest.TestCase):
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


class DaemonHelperTests(Lote4TestCase):
    def test_socket_path_respeita_runtime_dir(self):
        expected = self.home / "run" / f"multilut-controller-{os.getuid()}" / "daemon.sock"
        self.assertEqual(extra.daemon_socket_path(), expected)

    def test_status_file_roundtrip(self):
        self.assertIsNone(extra.read_daemon_status())
        extra.write_daemon_status({"running": True, "pid": 4242})
        data = extra.read_daemon_status()
        self.assertEqual(data, {"running": True, "pid": 4242})

    def test_daemon_status_sem_daemon(self):
        status = extra.daemon_status()
        self.assertFalse(status["alive"])

    def test_daemon_running_falso_sem_socket(self):
        self.assertFalse(extra.daemon_running())

    def test_unit_install_uninstall(self):
        app_dir = self.home / "app"
        unit_dir = self.home / "systemd/user"
        self.assertFalse(extra.daemon_unit_installed(unit_dir))
        unit = extra.daemon_install_unit(app_dir=app_dir, unit_dir=unit_dir)
        self.assertTrue(unit.is_file())
        content = unit.read_text(encoding="utf-8")
        self.assertIn(str(app_dir), content)
        self.assertIn("ExecStart", content)
        self.assertIn("WantedBy=default.target", content)
        self.assertTrue(extra.daemon_uninstall_unit(unit_dir))
        self.assertFalse(unit.exists())

    def test_piloto_status_item_no_doctor(self):
        from multilut_extra import diagnostic_report

        titles = {item["title"] for item in diagnostic_report()}
        self.assertIn("Daemon (piloto sem janela)", titles)


@unittest.skipIf(daemon_mod is None, "multilut_daemon indisponível (sem PyGObject)")
class DaemonControlTests(Lote4TestCase):
    def setUp(self) -> None:
        super().setUp()
        self.pilot = daemon_mod.DaemonPilot()
        self.server = daemon_mod.ControlServer(self.pilot)
        self.server.start()
        self.addCleanup(self.server.stop)

    def request(self, payload: dict) -> dict:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
            client.settimeout(3.0)
            client.connect(str(extra.daemon_socket_path()))
            client.sendall((json.dumps(payload) + "\n").encode("utf-8"))
            reply = client.recv(8192)
        return json.loads(reply.decode("utf-8"))

    def test_status_via_socket(self):
        data = extra.query_daemon()
        self.assertIsNotNone(data)
        self.assertTrue(data["running"])
        self.assertEqual(data["pid"], os.getpid())
        self.assertEqual(data["events"], 0)
        status = extra.daemon_status()
        self.assertTrue(status["alive"])
        self.assertTrue(extra.daemon_running())

    def test_comando_desconhecido(self):
        reply = self.request({"cmd": "abracadabra"})
        self.assertIn("error", reply)

    def test_requisicao_invalida(self):
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
            client.settimeout(3.0)
            client.connect(str(extra.daemon_socket_path()))
            client.sendall(b"isto nao e json\n")
            reply = client.recv(8192)
        self.assertIn("error", json.loads(reply.decode("utf-8")))

    def test_stop_aciona_callback(self):
        stopped = threading.Event()
        self.server.on_stop = lambda: stopped.set()
        reply = self.request({"cmd": "stop"})
        self.assertTrue(reply["ok"])
        self.assertTrue(stopped.wait(timeout=3.0))
        self.assertTrue(self.pilot.stop_requested)

    def test_apply_por_comando_troca_perfil_e_historico(self):
        shader = self.write_shader()
        core.save_config(
            {"auto_map_switch": True, "shader_path": str(shader), "notify_changes": False}
        )
        reply = self.request({"cmd": "apply", "token": "tell"})
        self.assertTrue(reply["applied"])
        self.assertEqual(reply["profile_id"], 22)
        self.assertEqual(reply["profile_name"], "Tell")
        self.assertTrue(reply["changed"])
        # perfil realmente gravado no shader
        self.assertEqual(core.read_active_profile(shader), 22)
        # histórico com origem daemon
        entries = core.read_history(limit=5)
        self.assertEqual(entries[0]["origin"], "daemon")
        self.assertEqual(entries[0]["detail"], "tell")
        # status do daemon registra o último mapa
        self.assertEqual(self.pilot.last_map["token"], "tell")
        self.assertEqual(self.pilot.events, 1)
        # segundo apply: já ativo, sem troca
        again = self.request({"cmd": "apply", "token": "tell"})
        self.assertTrue(again["applied"])
        self.assertFalse(again["changed"])

    def test_apply_ignorado_com_piloto_desligado(self):
        self.write_shader()
        core.save_config({"auto_map_switch": False})
        reply = self.request({"cmd": "apply", "token": "tell"})
        self.assertFalse(reply["applied"])

    def test_status_file_registrado(self):
        self.pilot.record_status()
        data = extra.read_daemon_status()
        self.assertTrue(data["running"])
        self.assertIn("started_at", data)


class AutostartTests(Lote4TestCase):
    def test_install_remove(self):
        app_dir = self.home / "app"
        self.assertFalse(extra.autostart_installed())
        target = extra.autostart_install(app_dir=app_dir, minimized=True)
        self.assertTrue(target.is_file())
        content = target.read_text(encoding="utf-8")
        self.assertIn(f"Exec={app_dir}/run.sh --minimized", content)
        self.assertIn("X-GNOME-Autostart-enabled=true", content)
        self.assertIn("StartupWMClass=com.felipesantiago.MultiLUTController", content)
        self.assertTrue(extra.autostart_installed())
        self.assertTrue(extra.autostart_remove())
        self.assertFalse(extra.autostart_installed())

    def test_install_sem_minimized(self):
        target = extra.autostart_install(app_dir=self.home / "app", minimized=False)
        content = target.read_text(encoding="utf-8")
        self.assertIn("Exec=" + str(self.home / "app") + "/run.sh\n", content)
        self.assertNotIn("--minimized", content)


class DiagnosticReportTests(Lote4TestCase):
    def test_texto_do_relatorio(self):
        self.write_shader()
        text = extra.build_diagnostic_text(include_log_tail=False)
        self.assertIn(f"MultiLUT Controller v{core.APP_VERSION}", text)
        self.assertIn("== Ambiente ==", text)
        self.assertIn("== Diagnóstico ==", text)
        self.assertIn("Shader MultiLUT", text)
        self.assertIn("== Histórico (últimos 20) ==", text)
        self.assertIn("(histórico vazio)", text)

    def test_export_txt(self):
        target = self.home / "docs/relatorio.txt"
        summary = extra.export_diagnostic_report(target)
        self.assertFalse(summary["zip"])
        self.assertEqual(summary["path"], str(target))
        saved = target.read_text(encoding="utf-8")
        self.assertIn("MultiLUT Controller", saved)

    def test_export_zip_com_config_e_historico(self):
        core.save_config({"auto_map_switch": True, "game_width": 1366})
        core.append_history(
            {"profile_id": 22, "profile_name": "Tell", "origin": "daemon"}
        )
        target = self.home / "docs/relatorio.zip"
        summary = extra.export_diagnostic_report(target)
        self.assertTrue(summary["zip"])
        self.assertEqual(summary["members"], 3)
        with zipfile.ZipFile(target) as bundle:
            names = set(bundle.namelist())
            self.assertIn("relatorio-diagnostico.txt", names)
            self.assertIn("config.json", names)
            self.assertIn("history.jsonl", names)
            report = bundle.read("relatorio-diagnostico.txt").decode("utf-8")
            self.assertIn("auto_map_switch: True", report)
            self.assertIn("Tell", report)


class UpdateHelperTests(Lote4TestCase):
    def test_local_git_head_fora_de_git(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertIsNone(core.local_git_head(Path(tmp)))

    def test_remote_head_fora_de_git(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertIsNone(core.git_remote_head(Path(tmp), timeout=4.0))

    def test_apply_update_sem_git_orienta_download(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = core.apply_update(repo=Path(tmp))
            self.assertFalse(result["ok"])
            self.assertIn("releases", result["message"])

    def test_apply_update_em_repo_sem_remoto(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            import subprocess

            subprocess.run(["git", "init", "-q", str(repo)], check=True)
            (repo / "arquivo.txt").write_text("x", encoding="utf-8")
            subprocess.run(
                ["git", "-C", str(repo), "add", "arquivo.txt"], check=True
            )
            subprocess.run(
                ["git", "-C", str(repo), "-c", "user.email=a@b.c",
                 "-c", "user.name=t", "commit", "-qm", "init"],
                check=True,
            )
            self.assertEqual(core.local_git_head(repo), core.local_git_head(repo))
            result = core.apply_update(repo=repo)
            self.assertFalse(result["ok"])
            self.assertEqual(result["old_head"], result["new_head"])


class HelpContentTests(unittest.TestCase):
    def test_atalhos(self):
        self.assertGreaterEqual(len(extra.HELP_SHORTCUTS), 4)
        for keys, description in extra.HELP_SHORTCUTS:
            self.assertTrue(keys.strip())
            self.assertTrue(description.strip())

    def test_glossario(self):
        terms = [term for term, _ in extra.HELP_GLOSSARY]
        self.assertGreaterEqual(len(terms), 8)
        self.assertIn("-condebug", terms)
        self.assertIn("vkBasalt", terms)
        self.assertIn("Daemon", terms)
        for term, definition in extra.HELP_GLOSSARY:
            self.assertTrue(definition.strip())

    def test_problemas_comuns(self):
        problems = [problem for problem, _ in extra.HELP_TROUBLESHOOTING]
        self.assertGreaterEqual(len(problems), 5)
        for problem, steps in extra.HELP_TROUBLESHOOTING:
            self.assertTrue(problem.strip())
            self.assertTrue(steps)
            for step in steps:
                self.assertTrue(step.strip())


@unittest.skipIf(multilut_ctl is None, "multilut_ctl indisponível")
class CliParserTests(unittest.TestCase):
    def test_comandos_novos_existentes(self):
        parser = multilut_ctl.build_parser()
        daemon_args = parser.parse_args(["daemon", "status"])
        self.assertEqual(daemon_args.func, multilut_ctl.cmd_daemon)
        autostart_args = parser.parse_args(["autostart", "on"])
        self.assertEqual(autostart_args.func, multilut_ctl.cmd_autostart)
        update_args = parser.parse_args(["update", "check"])
        self.assertEqual(update_args.func, multilut_ctl.cmd_update)

    def test_doctor_export_flag(self):
        parser = multilut_ctl.build_parser()
        args = parser.parse_args(["doctor", "--export", "relatorio.txt"])
        self.assertEqual(args.export, "relatorio.txt")

    def test_acoes_invalidas_rejeitadas(self):
        parser = multilut_ctl.build_parser()
        with self.assertRaises(SystemExit):
            parser.parse_args(["daemon", "reinventar"])
        with self.assertRaises(SystemExit):
            parser.parse_args(["autostart", "talvez"])


if __name__ == "__main__":
    unittest.main()
