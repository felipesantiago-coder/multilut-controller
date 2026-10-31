#!/usr/bin/env python3
"""Indicador da bandeja como processo auxiliar GTK3.

Causa-raiz corrigida: um processo GTK4 não consegue usar o binding GTK3
do AppIndicator (Gtk.Menu não existe no GTK4 e a namespace Gtk já está
carregada como 4.0) — o ícone nunca aparecia mesmo com tudo instalado.
Agora o indicador vive em multilut_tray.py --serve (processo separado,
GTK3), gerenciado pelo app via multilut_extra. Cobertura: alvos D-Bus,
assinatura do menu, gerência de PID (start/stop com processos reais),
checagem de binding em processo limpo e integração no controller via AST.
"""

import ast
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

import multilut_core as core
import multilut_extra as extra
import multilut_tray as tray

CONTROLLER_SRC = Path(__file__).resolve().parent.parent / "multilut_controller.py"
TRAY_SRC = Path(__file__).resolve().parent.parent / "multilut_tray.py"


class SandboxTestCase(unittest.TestCase):
    """Estado isolado por teste (XDG_STATE_HOME em tempdir)."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)
        self._env = mock.patch.dict(
            "os.environ", {"XDG_STATE_HOME": str(self.tmp / "state")}, clear=False
        )
        self._env.start()
        self.addCleanup(self._env.stop)


def _spawn_marker_child(ignore_term: bool = False):
    """Processo real com "multilut_tray" no cmdline (como o auxiliar)."""
    code = "import time\n"
    if ignore_term:
        code += "import signal\nsignal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
    code += "time.sleep(30)\n"
    return subprocess.Popen(
        [sys.executable, "-c", code, "multilut_tray", "--serve"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


class AppActionTargetTests(unittest.TestCase):
    def test_alvos_do_app_padrao(self):
        name, path = tray.app_action_target()
        self.assertEqual(name, "com.felipesantiago.MultiLUTController")
        self.assertEqual(path, "/com/felipesantiago/MultiLUTController")

    def test_derivacao_de_id_customizado(self):
        self.assertEqual(tray.app_action_target("a.b.C"), ("a.b.C", "/a/b/C"))


class EntriesSignatureTests(unittest.TestCase):
    def test_mesma_entrada_mesma_assinatura(self):
        entries = tray.build_menu_entries([(3, "Nome")], pilot_on=True)
        self.assertEqual(tray.entries_signature(entries), tray.entries_signature(entries))

    def test_mudanca_de_piloto_muda_a_assinatura(self):
        base = [(3, "Nome")]
        ligado = tray.entries_signature(tray.build_menu_entries(base, pilot_on=True))
        desligado = tray.entries_signature(tray.build_menu_entries(base, pilot_on=False))
        self.assertNotEqual(ligado, desligado)

    def test_assinatura_e_hashavel(self):
        entries = tray.build_menu_entries([(1, "A"), (2, "B")], pilot_on=True)
        self.assertIsInstance(hash(tray.entries_signature(entries)), int)


class UsoDoAuxiliarTests(unittest.TestCase):
    def test_main_sem_serve_orienta_e_sai_com_codigo_de_uso(self):
        self.assertEqual(tray.main([]), tray.EXIT_USAGE)

    def test_constantes_de_saida(self):
        self.assertEqual(tray.EXIT_NO_BINDING, 3)
        self.assertEqual(tray.EXIT_NO_SESSION_BUS, 4)


class TrayBindingStatusTests(SandboxTestCase):
    def _completed(self, returncode: int):
        return subprocess.CompletedProcess([], returncode, "", "")

    def test_binding_presente(self):
        with mock.patch.object(
            extra.subprocess, "run", return_value=self._completed(0)
        ) as run_mock:
            ok, detail = extra.tray_binding_status()
        self.assertTrue(ok)
        self.assertIn("libayatana", detail)
        self.assertEqual(run_mock.call_args.args[0][2], extra.TRAY_BINDING_CHECK)

    def test_binding_ausente_orienta_a_instalacao(self):
        with mock.patch.object(
            extra.subprocess, "run", return_value=self._completed(1)
        ):
            ok, detail = extra.tray_binding_status()
        self.assertFalse(ok)
        self.assertIn("libayatana-appindicator", detail)

    def test_falha_de_execucao_e_marcada_como_ausente(self):
        with mock.patch.object(
            extra.subprocess, "run", side_effect=FileNotFoundError("python")
        ):
            ok, detail = extra.tray_binding_status()
        self.assertFalse(ok)
        self.assertIn("não deu para verificar", detail)


class PidFileTests(SandboxTestCase):
    def test_arquivos_no_estado_xdg(self):
        self.assertEqual(extra.tray_pid_file().parent, core.app_state_dir())
        self.assertEqual(extra.tray_pid_file().name, "tray.pid")
        self.assertEqual(extra.tray_log_file().name, "tray.log")

    def test_caminho_customizado(self):
        self.assertEqual(
            extra.tray_pid_file(self.tmp / "outro"), self.tmp / "outro" / "tray.pid"
        )


class TrayProcessRunningTests(SandboxTestCase):
    def test_sem_pid_file(self):
        self.assertFalse(extra.tray_process_running())

    def test_pid_file_corrompido(self):
        pid_file = extra.tray_pid_file()
        pid_file.parent.mkdir(parents=True, exist_ok=True)
        pid_file.write_text("não é um pid\n", encoding="utf-8")
        self.assertFalse(extra.tray_process_running(pid_file))

    def test_pid_morto(self):
        out = subprocess.run(
            [sys.executable, "-c", "import os; print(os.getpid())"],
            capture_output=True,
            text=True,
        )
        pid_file = extra.tray_pid_file()
        pid_file.parent.mkdir(parents=True, exist_ok=True)
        pid_file.write_text(f"{out.stdout.strip()}\n", encoding="utf-8")
        self.assertFalse(extra.tray_process_running(pid_file))

    def test_processo_auxiliar_vivo(self):
        child = _spawn_marker_child()
        self.addCleanup(self._reap, child)
        pid_file = extra.tray_pid_file()
        pid_file.parent.mkdir(parents=True, exist_ok=True)
        pid_file.write_text(f"{child.pid}\n", encoding="utf-8")
        self.assertTrue(extra.tray_process_running(pid_file))

    def test_pid_reutilizado_por_outro_programa_nao_engana(self):
        # processo vivo, mas sem "multilut_tray" no cmdline
        child = subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(30)"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        self.addCleanup(self._reap, child)
        pid_file = extra.tray_pid_file()
        pid_file.parent.mkdir(parents=True, exist_ok=True)
        pid_file.write_text(f"{child.pid}\n", encoding="utf-8")
        self.assertFalse(extra.tray_process_running(pid_file))

    @staticmethod
    def _reap(child):
        child.kill()
        child.wait()


class StartTrayProcessTests(SandboxTestCase):
    def test_ja_em_execucao_nao_spawna_nada(self):
        pid_file = extra.tray_pid_file()
        pid_file.parent.mkdir(parents=True, exist_ok=True)
        pid_file.write_text("1\n", encoding="utf-8")
        with mock.patch.object(
            extra, "tray_process_running", return_value=True
        ), mock.patch.object(extra.subprocess, "Popen") as popen_mock:
            ok, detail = extra.start_tray_process()
        self.assertTrue(ok)
        self.assertEqual(detail, extra.TRAY_RUNNING_DETAIL)
        popen_mock.assert_not_called()

    def test_sem_binding_nao_spawna(self):
        with mock.patch.object(
            extra, "tray_binding_status", return_value=(False, "instale libayatana")
        ), mock.patch.object(extra.subprocess, "Popen") as popen_mock:
            ok, detail = extra.start_tray_process()
        self.assertFalse(ok)
        self.assertIn("libayatana", detail)
        popen_mock.assert_not_called()

    def test_script_ausente(self):
        with mock.patch.object(
            extra, "tray_binding_status", return_value=(True, "ok")
        ):
            ok, detail = extra.start_tray_process(app_dir=self.tmp / "vazio")
        self.assertFalse(ok)
        self.assertIn("multilut_tray.py não encontrado", detail)

    def test_sucesso_grava_o_pid_e_log(self):
        fake = mock.Mock(pid=4711)
        with mock.patch.object(
            extra, "tray_binding_status", return_value=(True, "ok")
        ), mock.patch.object(extra.subprocess, "Popen", return_value=fake) as popen_mock:
            ok, detail = extra.start_tray_process()
        self.assertTrue(ok)
        self.assertEqual(detail, extra.TRAY_STARTED_DETAIL)
        args, kwargs = popen_mock.call_args
        self.assertIn("--serve", args[0])
        self.assertTrue(any(str(a).endswith("multilut_tray.py") for a in args[0]))
        self.assertTrue(kwargs.get("start_new_session"))
        self.assertEqual(extra.tray_pid_file().read_text(encoding="utf-8").strip(), "4711")
        self.assertTrue(extra.tray_log_file().exists())

    def test_falha_do_spawn_e_reportada(self):
        with mock.patch.object(
            extra, "tray_binding_status", return_value=(True, "ok")
        ), mock.patch.object(
            extra.subprocess, "Popen", side_effect=OSError("sem memória")
        ):
            ok, detail = extra.start_tray_process()
        self.assertFalse(ok)
        self.assertIn("Não foi possível iniciar o indicador", detail)


class StopTrayProcessTests(SandboxTestCase):
    def _write_pid(self, pid: int) -> Path:
        pid_file = extra.tray_pid_file()
        pid_file.parent.mkdir(parents=True, exist_ok=True)
        pid_file.write_text(f"{pid}\n", encoding="utf-8")
        return pid_file

    def test_sem_pid_file(self):
        self.assertTrue(extra.stop_tray_process())
        self.assertFalse(extra.tray_pid_file().exists())

    def test_pid_file_corrompido(self):
        pid_file = extra.tray_pid_file()
        pid_file.parent.mkdir(parents=True, exist_ok=True)
        pid_file.write_text("lixo\n", encoding="utf-8")
        self.assertTrue(extra.stop_tray_process(pid_file=pid_file))

    def test_pid_ja_morto_limpa_o_arquivo(self):
        pid_file = self._write_pid(2_000_000_000)
        self.assertTrue(extra.stop_tray_process(pid_file=pid_file))
        self.assertFalse(pid_file.exists())

    def test_parada_real_com_sigterm(self):
        child = _spawn_marker_child()
        self.addCleanup(self._reap, child)
        pid_file = self._write_pid(child.pid)
        self.assertTrue(extra.stop_tray_process(pid_file=pid_file, timeout=2.0))
        for _ in range(40):
            if child.poll() is not None:
                break
            time.sleep(0.05)
        self.assertIsNotNone(child.poll(), "o auxiliar deveria ter saído com SIGTERM")
        self.assertFalse(pid_file.exists())

    def test_processo_stubborn_recebe_sigkill(self):
        child = _spawn_marker_child(ignore_term=True)
        self.addCleanup(self._reap, child)
        pid_file = self._write_pid(child.pid)
        self.assertTrue(extra.stop_tray_process(pid_file=pid_file, timeout=0.3))
        for _ in range(40):
            if child.poll() is not None:
                break
            time.sleep(0.05)
        self.assertIsNotNone(child.poll(), "SIGKILL deveria encerrar o auxiliar")
        self.assertFalse(pid_file.exists())

    @staticmethod
    def _reap(child):
        child.kill()
        child.wait()


class AuxiliarAstTestCase(unittest.TestCase):
    """Estrutura do processo auxiliar (sem PyGObject no ambiente)."""

    @classmethod
    def setUpClass(cls):
        cls.tree = ast.parse(TRAY_SRC.read_text(encoding="utf-8"))

    def _method(self, class_name: str | None, method_name: str):
        for node in ast.walk(self.tree):
            if class_name is not None:
                if not (isinstance(node, ast.ClassDef) and node.name == class_name):
                    continue
                scope = node
            else:
                scope = self.tree
            for item in ast.walk(scope):
                if (
                    isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef))
                    and item.name == method_name
                ):
                    return item
        raise AssertionError(f"{class_name}.{method_name} não encontrado")

    def test_serve_exige_gtk3(self):
        serve = self._method(None, "serve")
        corpo = ast.dump(serve)
        self.assertIn("'Gtk'", corpo)
        self.assertIn("'3.0'", corpo)
        self.assertNotIn("'4.0'", corpo)

    def test_serve_assiste_o_app_por_dbus(self):
        serve = self._method(None, "serve")
        corpo = ast.dump(serve)
        self.assertIn("bus_watch_name", corpo)
        self.assertIn("main_quit", corpo)
        proxy = self._method(None, "_actions_proxy")
        self.assertIn("DBusActionGroup", ast.dump(proxy))

    def test_serve_reconstroi_o_menu_em_poll(self):
        serve = self._method(None, "serve")
        corpo = ast.dump(serve)
        self.assertIn("timeout_add_seconds", corpo)
        self.assertIn("auto_map_switch", corpo)
        self.assertIn("unix_signal_add", corpo)

    def test_menu_e_de_widgets_sem_new_from_model(self):
        update = self._method("TrayIcon", "update")
        corpo = ast.dump(update)
        self.assertIn("MenuItem", corpo)
        self.assertIn("set_menu", corpo)
        self.assertNotIn("new_from_model", corpo)


class ControllerAstTestCase(unittest.TestCase):
    """Integração no aplicativo: o app só gerencia o processo auxiliar."""

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

    def _self_attrs(self, method) -> set:
        return {
            node.attr
            for node in ast.walk(method)
            if isinstance(node, ast.Attribute)
            and isinstance(node.value, ast.Name)
            and node.value.id == "self"
        }

    def _extra_attrs(self, method) -> set:
        return {
            node.attr
            for node in ast.walk(method)
            if isinstance(node, ast.Attribute)
            and isinstance(node.value, ast.Name)
            and node.value.id == "extra"
        }

    def test_controller_nao_importa_mais_o_modulo_da_bandeja(self):
        for node in ast.walk(self.tree):
            if isinstance(node, ast.Import):
                self.assertNotIn(
                    "multilut_tray",
                    {alias.name for alias in node.names},
                    "o processo GTK4 não pode importar o módulo GTK3 da bandeja",
                )

    def test_controller_nao_consulta_tray_supported_inprocess(self):
        corpo = ast.dump(self.tree)
        self.assertNotIn("tray_supported", corpo)

    def test_setup_tray_gerencia_o_processo_auxiliar(self):
        setup = self._method("MultiLUTApplication", "setup_tray")
        attrs = self._self_attrs(setup)
        self.assertIn("_ensure_tray_process", attrs)
        self.assertIn("_schedule_tray_environment", attrs)
        self.assertIn("stop_tray_process", self._extra_attrs(setup))

    def test_subida_do_auxiliar_fora_da_ui_thread(self):
        ensure = self._method("MultiLUTApplication", "_ensure_tray_process")
        self.assertTrue(
            any(
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "Thread"
                for node in ast.walk(ensure)
            ),
            "o spawn deve rodar em thread, sem travar a UI",
        )
        thread = self._method("MultiLUTApplication", "_tray_process_thread")
        self.assertIn("start_tray_process", self._extra_attrs(thread))

    def test_anuncio_marca_o_estado_da_bandeja(self):
        announce = self._method("MultiLUTApplication", "_announce_tray_process")
        self.assertIn("_tray_running", self._self_attrs(announce))

    def test_fechar_a_janela_preserva_o_modo_bandeja(self):
        close = self._method("MultiLUTWindow", "on_close_request")
        self.assertIn("_tray_running", ast.dump(close))

    def test_sair_encerra_o_auxiliar(self):
        quit_method = self._method("MultiLUTApplication", "on_app_quit")
        self.assertIn("stop_tray_process", self._extra_attrs(quit_method))

    def test_refresh_autocura_o_processo(self):
        refresh = self._method("MultiLUTApplication", "_refresh_tray")
        self.assertIn("tray_process_running", self._extra_attrs(refresh))
        self.assertIn("_ensure_tray_process", self._self_attrs(refresh))


if __name__ == "__main__":
    unittest.main()
