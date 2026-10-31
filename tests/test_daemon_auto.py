#!/usr/bin/env python3
"""Automação do daemon: o app instala e inicia o piloto sem comando manual.

Cobre ensure_daemon_unit/ensure_daemon_autopilot (multilut_extra) e a
integração da janela (verificação estrutural via AST, sem PyGObject).
"""

import ast
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import multilut_extra as extra

CONTROLLER_SRC = Path(__file__).resolve().parent.parent / "multilut_controller.py"


class DaemonAutoTestCase(unittest.TestCase):
    """Sandbox de HOME + XDG_RUNTIME_DIR + XDG_STATE_HOME por teste."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.home = Path(self._tmp.name)
        home_patcher = mock.patch("pathlib.Path.home", new=lambda: self.home)
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
        self.app_dir = self.home / "app"
        self.unit_dir = self.home / "systemd/user"


class EnsureDaemonUnitTests(DaemonAutoTestCase):
    def test_instala_quando_ausente(self):
        self.assertFalse(extra.daemon_unit_installed(self.unit_dir))
        ok, _detail = extra.ensure_daemon_unit(
            app_dir=self.app_dir, unit_dir=self.unit_dir
        )
        self.assertTrue(ok)
        self.assertTrue(extra.daemon_unit_installed(self.unit_dir))
        content = extra.daemon_unit_path(self.unit_dir).read_text(encoding="utf-8")
        self.assertIn(str(self.app_dir), content)
        self.assertIn("WantedBy=default.target", content)

    def test_idempotente(self):
        extra.ensure_daemon_unit(app_dir=self.app_dir, unit_dir=self.unit_dir)
        unit = extra.daemon_unit_path(self.unit_dir)
        antes = unit.read_text(encoding="utf-8")
        ok, detail = extra.ensure_daemon_unit(
            app_dir=self.app_dir, unit_dir=self.unit_dir
        )
        self.assertTrue(ok)
        self.assertIn("já instalado", detail)
        self.assertEqual(unit.read_text(encoding="utf-8"), antes)

    def test_falha_reportada_sem_excecao(self):
        bloqueio = self.home / "bloqueio"
        bloqueio.write_text("não sou diretório", encoding="utf-8")
        ok, detail = extra.ensure_daemon_unit(
            app_dir=self.app_dir, unit_dir=bloqueio / "user"
        )
        self.assertFalse(ok)
        self.assertTrue(detail.startswith("Falha ao instalar"), detail)


class EnsureDaemonAutopilotTests(DaemonAutoTestCase):
    def test_instala_habilita_e_inicia(self):
        with mock.patch.object(
            extra, "daemon_running", return_value=False
        ), mock.patch.object(
            extra,
            "daemon_start",
            return_value=(True, "Daemon iniciado (piloto ativo sem janela)."),
        ) as start_mock, mock.patch.object(
            extra, "daemon_systemctl", return_value=(True, "")
        ) as sys_mock:
            ok, detail = extra.ensure_daemon_autopilot(
                app_dir=self.app_dir, unit_dir=self.unit_dir
            )
        self.assertTrue(ok)
        self.assertEqual(detail, "Daemon iniciado (piloto ativo sem janela).")
        self.assertTrue(extra.daemon_unit_installed(self.unit_dir))
        start_mock.assert_called_once_with()
        acoes = [call.args[0] for call in sys_mock.call_args_list]
        self.assertIn("enable", acoes)

    def test_nao_inicia_se_ja_rodando(self):
        extra.ensure_daemon_unit(app_dir=self.app_dir, unit_dir=self.unit_dir)
        with mock.patch.object(
            extra, "daemon_running", return_value=True
        ), mock.patch.object(extra, "daemon_start") as start_mock:
            ok, detail = extra.ensure_daemon_autopilot(
                app_dir=self.app_dir, unit_dir=self.unit_dir
            )
        self.assertTrue(ok)
        self.assertEqual(detail, "Serviço já instalado.")
        start_mock.assert_not_called()

    def test_start_false_nao_toca_no_daemon(self):
        with mock.patch.object(extra, "daemon_running") as running_mock, \
                mock.patch.object(extra, "daemon_start") as start_mock:
            ok, _detail = extra.ensure_daemon_autopilot(
                app_dir=self.app_dir, unit_dir=self.unit_dir, start=False
            )
        self.assertTrue(ok)
        running_mock.assert_not_called()
        start_mock.assert_not_called()

    def test_falha_de_instalacao_propagada_sem_excecao(self):
        bloqueio = self.home / "bloqueio"
        bloqueio.write_text("não sou diretório", encoding="utf-8")
        ok, detail = extra.ensure_daemon_autopilot(
            app_dir=self.app_dir, unit_dir=bloqueio / "user"
        )
        self.assertFalse(ok)
        self.assertTrue(detail.startswith("Falha ao instalar"), detail)


class DiagnosticoTests(DaemonAutoTestCase):
    def test_doctor_nao_exige_comando_manual(self):
        items = {item["title"]: item for item in extra.diagnostic_report()}
        daemon = items["Daemon (piloto sem janela)"]
        self.assertEqual(daemon["state"], "info")
        self.assertIn("instala e inicia sozinho", daemon["detail"])
        self.assertNotIn("opcional; instale com", daemon["detail"])

    def test_doctor_servico_parado_explica_automacao(self):
        extra.ensure_daemon_unit(app_dir=self.app_dir, unit_dir=None)
        items = {item["title"]: item for item in extra.diagnostic_report()}
        daemon = items["Daemon (piloto sem janela)"]
        self.assertIn("o aplicativo inicia sozinho ao abrir", daemon["detail"])


class IntegracaoInterfaceTests(unittest.TestCase):
    """A janela agenda a garantia do daemon (AST, sem PyGObject)."""

    @classmethod
    def setUpClass(cls):
        cls.tree = ast.parse(CONTROLLER_SRC.read_text(encoding="utf-8"))

    def _method(self, class_name: str, method_name: str):
        for node in ast.walk(self.tree):
            if isinstance(node, ast.ClassDef) and node.name == class_name:
                for item in node.body:
                    if (
                        isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef))
                        and item.name == method_name
                    ):
                        return item
        raise AssertionError(f"{class_name}.{method_name} não encontrado")

    def _extra_attrs(self, method) -> set:
        return {
            node.attr
            for node in ast.walk(method)
            if isinstance(node, ast.Attribute)
            and isinstance(node.value, ast.Name)
            and node.value.id == "extra"
        }

    def test_janela_agenda_garantia_do_daemon(self):
        init = self._method("MultiLUTWindow", "__init__")
        attrs = {
            node.attr
            for node in ast.walk(init)
            if isinstance(node, ast.Attribute)
        }
        self.assertIn("_ensure_daemon_once", attrs)
        metodo = self._method("MultiLUTWindow", "_ensure_daemon_once")
        usa_thread = any(
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "Thread"
            for node in ast.walk(metodo)
        )
        self.assertTrue(usa_thread, "a garantia deve rodar fora da main loop")

    def test_thread_chama_ensure_daemon_autopilot(self):
        thread = self._method("MultiLUTWindow", "_daemon_autopilot_thread")
        self.assertIn(
            "ensure_daemon_autopilot",
            self._extra_attrs(thread),
        )

    def test_anuncio_verifica_estado_do_daemon(self):
        anuncio = self._method("MultiLUTWindow", "_announce_daemon_autopilot")
        # o handoff consulta o estado real do daemon na main loop
        corpo = ast.dump(anuncio)
        self.assertIn("_console_monitor", corpo)
        self.assertIn("cancel", corpo)


if __name__ == "__main__":
    unittest.main()
