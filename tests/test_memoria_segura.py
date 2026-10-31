#!/usr/bin/env python3
"""Memória segura: o monitor em segundo plano não pode faminto o jogo.

O "Engine Error: Out of memory" do jogo passou a ocorrer com o daemon
rodando 24/7. Cobre os vetores de RAM: orçamento por dreno do console.log,
teto do buffer parcial (linhas só com "\\r"), guardião de memória do daemon
(RSS → collect/restart) e teto de memória na unit systemd.
"""

import ast
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import multilut_core as core
import multilut_extra as extra

REPO = Path(__file__).resolve().parent.parent
DAEMON_SRC = REPO / "multilut_daemon.py"
CONTROLLER_SRC = REPO / "multilut_controller.py"


class SandboxTestCase(unittest.TestCase):
    """Tempdir por teste (sem tocar em HOME real)."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)


class OrcamentoDrenoTests(unittest.TestCase):
    """O pico de leitura por evento fica em 4 MB (não mais 32 MB)."""

    def test_bloco_e_quantidade_definidos(self):
        self.assertEqual(core.CONSOLE_READ_BLOCK, 262144)  # 256 KB
        self.assertEqual(core.CONSOLE_DRAIN_BLOCKS, 16)

    def test_orcamento_por_dreno_cabe_em_4mb(self):
        total = core.CONSOLE_DRAIN_BLOCKS * core.CONSOLE_READ_BLOCK
        self.assertEqual(total, 4 * 1024 * 1024)
        self.assertLess(total, 32 * 1024 * 1024)  # teto antigo

    def test_teto_do_buffer_parcial_definido(self):
        self.assertEqual(core.CONSOLE_BUFFER_LIMIT, 1024 * 1024)
        self.assertEqual(core.CONSOLE_BUFFER_KEEP, 64 * 1024)
        self.assertLess(core.CONSOLE_BUFFER_KEEP, core.CONSOLE_BUFFER_LIMIT)


class ConsoleTailTetoTests(unittest.TestCase):
    """Linhas só com "\\r" (progresso do motor) não inflam o buffer."""

    def test_buffer_nao_passa_do_teto(self):
        tail = core.ConsoleTail()
        bloco = b"Carregando recursos ... 47%\r" * 400  # sem "\n"
        total = 0
        for _ in range(200):  # ~2,2 MB de progresso sem uma linha completa
            total += len(bloco)
            tail.feed(bloco)
        self.assertGreater(total, core.CONSOLE_BUFFER_LIMIT)
        self.assertLessEqual(len(tail._buffer), core.CONSOLE_BUFFER_LIMIT)
        self.assertEqual(tail.offset, total)  # nada é relido

    def test_linhas_normais_seguem_funcionando_apos_o_teto(self):
        tail = core.ConsoleTail()
        tail.feed(b"progresso 50%\r" * 120000)  # ~1,8 MB sem "\n"
        self.assertLessEqual(len(tail._buffer), core.CONSOLE_BUFFER_LIMIT)
        tail.feed(b"ok\n")  # fecha a linha parcial misturada com lixo velho
        tokens = tail.map_tokens(tail.feed(b'Map: tell\n'))
        self.assertEqual(tokens, ["tell"])

    def test_feed_vazio_e_reset_preservados(self):
        tail = core.ConsoleTail()
        self.assertEqual(tail.feed(b""), [])
        tail.feed(b"x\n")
        tail.reset()
        self.assertEqual(tail.offset, 0)
        self.assertEqual(tail._buffer, b"")


class GuardiaoMemoriaTests(SandboxTestCase):
    """Política pura do guardião: ok / collect / restart."""

    def test_limite_definidos(self):
        self.assertEqual(extra.DAEMON_MEM_SOFT_KIB, 96 * 1024)
        self.assertEqual(extra.DAEMON_MEM_HARD_KIB, 176 * 1024)
        self.assertLess(extra.DAEMON_MEM_HARD_KIB, 192 * 1024)  # MemoryMax da unit

    def test_sem_leitura_de_rss_nada_faz(self):
        self.assertEqual(extra.daemon_memory_policy(None), "ok")

    def test_abaixo_do_suave_e_ok(self):
        self.assertEqual(extra.daemon_memory_policy(1024), "ok")
        self.assertEqual(extra.daemon_memory_policy(extra.DAEMON_MEM_SOFT_KIB - 1), "ok")

    def test_no_suave_ate_antes_do_duro_e_collect(self):
        self.assertEqual(extra.daemon_memory_policy(extra.DAEMON_MEM_SOFT_KIB), "collect")
        self.assertEqual(extra.daemon_memory_policy(extra.DAEMON_MEM_HARD_KIB - 1), "collect")

    def test_no_duro_e_restart(self):
        self.assertEqual(extra.daemon_memory_policy(extra.DAEMON_MEM_HARD_KIB), "restart")
        self.assertEqual(extra.daemon_memory_policy(extra.DAEMON_MEM_HARD_KIB * 4), "restart")

    def test_le_vmrss_do_status(self):
        proc = Path(tempfile.mkdtemp(dir=self.tmp))
        (proc / "777").mkdir(parents=True)
        (proc / "777" / "status").write_text(
            "Name:\tpython3\nThreads:\t3\nVmRSS:\t 45056 kB\nVmPeak:\t 60000 kB\n",
            encoding="utf-8",
        )
        self.assertEqual(extra.read_process_rss_kib(pid=777, proc_root=proc), 45056)

    def test_sem_status_retorna_none(self):
        self.assertIsNone(extra.read_process_rss_kib(pid=1, proc_root=self.tmp))

    def test_vmrss_malformado_retorna_none(self):
        proc = Path(tempfile.mkdtemp(dir=self.tmp))
        (proc / "9").mkdir(parents=True)
        (proc / "9" / "status").write_text("VmRSS:\tnao-e-numero kB\n", encoding="utf-8")
        self.assertIsNone(extra.read_process_rss_kib(pid=9, proc_root=proc))

    def test_leitura_real_do_processo(self):
        rss = extra.read_process_rss_kib()  # /proc/self/status neste sandbox
        self.assertTrue(rss is None or (isinstance(rss, int) and rss > 0))


class MemoryTickTests(unittest.TestCase):
    """Tique do guardião no daemon (sem GLib; política via extra)."""

    def setUp(self) -> None:
        import multilut_daemon as daemon_mod

        self.daemon_mod = daemon_mod
        self.pilot = daemon_mod.DaemonPilot()

    def test_ok_nao_muda_nada(self):
        with mock.patch.object(extra, "read_process_rss_kib", return_value=2048):
            self.assertEqual(self.daemon_mod.memory_tick(self.pilot), "ok")
        self.assertFalse(self.pilot.restart_requested)

    def test_limite_suave_roda_o_coletor(self):
        with mock.patch.object(
            extra, "read_process_rss_kib", return_value=extra.DAEMON_MEM_SOFT_KIB + 1
        ), mock.patch.object(self.daemon_mod.gc, "collect") as collect_mock:
            self.assertEqual(self.daemon_mod.memory_tick(self.pilot), "collect")
            collect_mock.assert_called_once_with()
        self.assertFalse(self.pilot.restart_requested)

    def test_limite_duro_marca_o_reinicio(self):
        with mock.patch.object(
            extra, "read_process_rss_kib", return_value=extra.DAEMON_MEM_HARD_KIB + 1
        ), mock.patch.object(self.daemon_mod.gc, "collect") as collect_mock:
            self.assertEqual(self.daemon_mod.memory_tick(self.pilot), "restart")
            collect_mock.assert_not_called()
        self.assertTrue(self.pilot.restart_requested)


class SandboxUnitTestCase(unittest.TestCase):
    """HOME + XDG sandbox (mesmo padrão de test_daemon_auto)."""

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


class UnitTetoMemoriaTests(SandboxUnitTestCase):
    """A unit do systemd nasce com teto de RAM e atualiza unidades antigas."""

    def test_template_tem_os_tetos(self):
        self.assertIn("MemoryHigh=96M", extra.DAEMON_UNIT_TEMPLATE)
        self.assertIn("MemoryMax=192M", extra.DAEMON_UNIT_TEMPLATE)
        self.assertIn("Restart=on-failure", extra.DAEMON_UNIT_TEMPLATE)

    def test_instalacao_nova_ja_vai_com_os_tetos(self):
        ok, _detail = extra.ensure_daemon_unit(
            app_dir=self.app_dir, unit_dir=self.unit_dir
        )
        self.assertTrue(ok)
        content = extra.daemon_unit_path(self.unit_dir).read_text(encoding="utf-8")
        self.assertIn("MemoryMax=192M", content)
        self.assertIn(str(self.app_dir), content)

    def test_unidade_antiga_e_atualizada_e_servico_reiniciado(self):
        self.unit_dir.mkdir(parents=True, exist_ok=True)
        unit = extra.daemon_unit_path(self.unit_dir)
        unit.write_text(
            "[Service]\nExecStart=/usr/bin/python3 antigo\nRestart=on-failure\n",
            encoding="utf-8",
        )
        with mock.patch.object(
            extra, "daemon_running", return_value=True
        ), mock.patch.object(
            extra, "daemon_systemctl", return_value=(True, "")
        ) as sys_mock:
            ok, detail = extra.ensure_daemon_unit(
                app_dir=self.app_dir, unit_dir=self.unit_dir
            )
        self.assertTrue(ok)
        self.assertIn("atualizado", detail)
        content = unit.read_text(encoding="utf-8")
        self.assertIn("MemoryMax=192M", content)
        self.assertIn(str(self.app_dir), content)
        acoes = [call.args[0] for call in sys_mock.call_args_list]
        self.assertIn("restart", acoes)

    def test_unidade_antiga_com_daemon_parado_nao_reinicia(self):
        self.unit_dir.mkdir(parents=True, exist_ok=True)
        extra.daemon_unit_path(self.unit_dir).write_text(
            "[Service]\nExecStart=x\n", encoding="utf-8"
        )
        with mock.patch.object(
            extra, "daemon_running", return_value=False
        ), mock.patch.object(
            extra, "daemon_systemctl", return_value=(True, "")
        ) as sys_mock:
            ok, detail = extra.ensure_daemon_unit(
                app_dir=self.app_dir, unit_dir=self.unit_dir
            )
        self.assertTrue(ok)
        self.assertIn("atualizado", detail)
        acoes = [call.args[0] for call in sys_mock.call_args_list]
        self.assertNotIn("restart", acoes)
        self.assertIn("daemon-reload", acoes)

    def test_unidade_corrente_nao_e_reescrita(self):
        extra.ensure_daemon_unit(app_dir=self.app_dir, unit_dir=self.unit_dir)
        unit = extra.daemon_unit_path(self.unit_dir)
        antes = unit.read_text(encoding="utf-8")
        ok, detail = extra.ensure_daemon_unit(
            app_dir=self.app_dir, unit_dir=self.unit_dir
        )
        self.assertTrue(ok)
        self.assertEqual(detail, "Serviço já instalado.")
        self.assertEqual(unit.read_text(encoding="utf-8"), antes)


class DoctorMemoriaTests(SandboxUnitTestCase):
    """O doctor mostra o consumo de RAM do daemon e o teto."""

    def test_doctor_mostra_ram_do_daemon_ativo(self):
        with mock.patch.object(
            extra, "query_daemon", return_value={"pid": 4321, "rss_kib": 45056}
        ):
            items = {item["title"]: item for item in extra.diagnostic_report()}
        detail = items["Daemon (piloto sem janela)"]["detail"]
        self.assertIn("ativo (pid 4321)", detail)
        self.assertIn("RAM 44 MB de um teto de 192 MB", detail)

    def test_doctor_sem_rss_nao_inventa_numero(self):
        with mock.patch.object(
            extra, "query_daemon", return_value={"pid": 4321}
        ):
            items = {item["title"]: item for item in extra.diagnostic_report()}
        detail = items["Daemon (piloto sem janela)"]["detail"]
        self.assertNotIn("RAM", detail)


class IntegracaoDrenoTests(unittest.TestCase):
    """Verificação estrutural (AST) dos drenos, sem PyGObject."""

    @classmethod
    def setUpClass(cls):
        cls.daemon_tree = ast.parse(DAEMON_SRC.read_text(encoding="utf-8"))
        cls.controller_tree = ast.parse(CONTROLLER_SRC.read_text(encoding="utf-8"))

    def _method(self, tree, class_name: str, method_name: str):
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef) and node.name == class_name:
                for item in node.body:
                    if (
                        isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef))
                        and item.name == method_name
                    ):
                        return item
        raise AssertionError(f"{class_name}.{method_name} não encontrado")

    def _core_attrs(self, method) -> set:
        return {
            node.attr
            for node in ast.walk(method)
            if isinstance(node, ast.Attribute)
            and isinstance(node.value, ast.Name)
            and node.value.id == "core"
        }

    def _dreno_orcado(self, method, label: str) -> None:
        usados = self._core_attrs(method)
        self.assertIn("CONSOLE_DRAIN_BLOCKS", usados, label)
        self.assertIn("CONSOLE_READ_BLOCK", usados, label)
        for node in ast.walk(method):
            if isinstance(node, ast.Constant) and node.value in (128, 262144):
                self.fail(f"{label}: literal {node.value!r} hardcoded no dreno")
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "extend"
            ):
                self.fail(f"{label}: acumula linhas em lista com .extend()")

    def test_dreno_do_daemon_usa_o_orcamento(self):
        metodo = self._method(self.daemon_tree, "DaemonPilot", "_drain_console_log")
        self._dreno_orcado(metodo, "daemon")

    def test_dreno_da_janela_usa_o_orcamento(self):
        metodo = self._method(
            self.controller_tree, "MultiLUTWindow", "_drain_console_log"
        )
        self._dreno_orcado(metodo, "janela")

    def test_fresh_console_limitado_em_ambos(self):
        for tree, classe, label in (
            (self.daemon_tree, "DaemonPilot", "daemon"),
            (self.controller_tree, "MultiLUTWindow", "janela"),
        ):
            metodo = self._method(tree, classe, "_apply_fresh_console")
            self.assertIn("CONSOLE_READ_BLOCK", self._core_attrs(metodo), label)

    def test_daemon_agenda_o_guardiao_e_sai_com_falha(self):
        main = None
        for node in self.daemon_tree.body:
            if isinstance(node, ast.FunctionDef) and node.name == "main":
                main = node
                break
        self.assertIsNotNone(main, "main do daemon não encontrada")
        corpo = ast.dump(main)
        self.assertIn("watch_memory", corpo)
        self.assertIn("timeout_add_seconds", corpo)
        self.assertIn("restart_requested", corpo)

    def test_daemon_tem_tique_do_guardiao_como_funcao_de_modulo(self):
        nomes = {
            node.name
            for node in ast.walk(self.daemon_tree)
            if isinstance(node, ast.FunctionDef)
        }
        self.assertIn("memory_tick", nomes)


if __name__ == "__main__":
    unittest.main()
