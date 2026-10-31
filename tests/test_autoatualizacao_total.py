#!/usr/bin/env python3
"""Autoatualização total: nenhuma etapa manual, em nenhum modo de uso.

A promessa "o app recebe atualizações sozinho" só é verdadeira quando:
(1) o daemon 24/7 também verifica e aplica — a janela pode nunca ser
aberta; (2) quem aplica registra a geração do código e os demais processos
se reiniciam sozinhos ao perceber o código novo no disco; (3) janela e
daemon nunca puxam ao mesmo tempo (lock compartilhado no estado do app);
(4) o install.sh também registra a geração, fechando o bootstrap. Cobre o
core com tempdir, o tique do daemon com mocks e a janela via AST.
"""

import ast
import os
import tempfile
import time
import types
import unittest
from pathlib import Path
from unittest import mock

import multilut_core as core
import multilut_daemon as daemon

REPO = Path(__file__).resolve().parent.parent
DAEMON_SRC = REPO / "multilut_daemon.py"
CONTROLLER_SRC = REPO / "multilut_controller.py"


class SandboxStateTestCase(unittest.TestCase):
    """Tempdir + XDG_STATE_HOME isolado; geração do processo repinada."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)
        patcher = mock.patch.dict(
            os.environ, {"XDG_STATE_HOME": str(self.tmp / "state")}
        )
        patcher.start()
        self.addCleanup(patcher.stop)
        core.reset_process_generation_cache()
        self.addCleanup(core.reset_process_generation_cache)


class ContratoAutoatualizacaoTests(unittest.TestCase):
    """Constantes que sustentam o fluxo automático."""

    def test_reverificacao_de_rotina_em_30_minutos(self):
        self.assertEqual(core.UPDATE_RECHECK_SECONDS, 1800)

    def test_lock_tem_tempo_de_validade_sensato(self):
        self.assertGreater(core.UPDATE_LOCK_STALE_SECONDS, 60)
        self.assertLessEqual(core.UPDATE_LOCK_STALE_SECONDS, 3600)


class GeracaoTests(SandboxStateTestCase):
    """A geração do código é o passo de mão entre janela, daemon e install.sh."""

    def test_geracao_comeca_vazia_no_estado_do_app(self):
        self.assertEqual(core.read_update_generation(), "")
        self.assertEqual(
            core.update_generation_path().parent, core.app_state_dir()
        )

    def test_escreve_e_le_a_geracao(self):
        core.write_update_generation("abc1234")
        self.assertEqual(core.read_update_generation(), "abc1234")

    def test_processo_pina_a_geracao_no_arranque(self):
        self.assertEqual(core.process_update_generation(), "")
        core.write_update_generation("novo123")
        # o processo segue na geração antiga até ser reiniciado
        self.assertEqual(core.process_update_generation(), "")
        core.reset_process_generation_cache()
        self.assertEqual(core.process_update_generation(), "novo123")

    def test_check_for_updates_reporta_processo_velho(self):
        with mock.patch.object(core, "local_git_head", return_value="aaa111"), \
             mock.patch.object(core, "git_remote_head", return_value="aaa111"), \
             mock.patch.object(
                 core, "fetch_latest_release", return_value=None
             ):
            em_dia = core.check_for_updates()
            self.assertEqual(em_dia["status"], "current")
            self.assertFalse(em_dia["stale_process"])
            core.write_update_generation("bbb222")
            atualizado = core.check_for_updates()
        self.assertEqual(atualizado["status"], "current")  # repositório em dia
        self.assertTrue(atualizado["stale_process"])  # ...mas o processo é velho

    def test_apply_update_git_registra_a_nova_geracao(self):
        stub = types.SimpleNamespace(returncode=0, stdout="", stderr="")
        with mock.patch.object(
            core, "local_git_head", side_effect=["velho111", "novo222"]
        ), mock.patch.object(core, "subprocess") as sub:
            sub.run.return_value = stub
            result = core.apply_update(repo=self.tmp)
        self.assertTrue(result["ok"])
        self.assertEqual(result["new_head"], "novo222")
        self.assertEqual(core.read_update_generation(), "novo222")

    def test_apply_update_sem_mudanca_nao_registra_geracao(self):
        stub = types.SimpleNamespace(returncode=0, stdout="", stderr="")
        with mock.patch.object(
            core, "local_git_head", side_effect=["mesmo1", "mesmo1"]
        ), mock.patch.object(core, "subprocess") as sub:
            sub.run.return_value = stub
            result = core.apply_update(repo=self.tmp)
        self.assertTrue(result["ok"])
        self.assertEqual(core.read_update_generation(), "")


class LockTests(SandboxStateTestCase):
    """Janela e daemon nunca puxam ao mesmo tempo; lock velho não trava."""

    def test_ciclo_completo_do_lock(self):
        self.assertTrue(core.acquire_update_lock())
        path = core.update_lock_path()
        self.assertTrue(path.is_file())
        self.assertIn(str(os.getpid()), path.read_text(encoding="utf-8"))
        self.assertFalse(core.acquire_update_lock())  # segundo perde
        core.release_update_lock()
        self.assertFalse(path.exists())
        self.assertTrue(core.acquire_update_lock())  # e volta a ser livre
        core.release_update_lock()

    def test_lock_velho_e_roubado(self):
        self.assertTrue(core.acquire_update_lock())
        path = core.update_lock_path()
        velho = time.time() - (core.UPDATE_LOCK_STALE_SECONDS + 600)
        os.utime(path, (velho, velho))
        self.assertTrue(core.acquire_update_lock())  # rouba o lock órfão
        self.assertIn(
            str(os.getpid()), path.read_text(encoding="utf-8")
        )
        core.release_update_lock()

    def test_lock_fresco_nao_e_roubado(self):
        self.assertTrue(core.acquire_update_lock())
        path = core.update_lock_path()
        recente = time.time() - 60
        os.utime(path, (recente, recente))
        self.assertFalse(core.acquire_update_lock())
        core.release_update_lock()

    def test_release_sem_lock_nao_falha(self):
        core.release_update_lock()  # não deve levantar
        self.assertFalse(core.update_lock_path().exists())


class UpdateTickTests(SandboxStateTestCase):
    """O tique do daemon: verifica, aplica e pede o próprio religar."""

    def setUp(self) -> None:
        super().setUp()
        self.pilot = types.SimpleNamespace(restart_requested=False)

    def test_config_desligado_nem_verifica(self):
        with mock.patch.object(
            core, "load_config", return_value={"check_updates": False}
        ), mock.patch.object(
            core, "check_for_updates", side_effect=AssertionError("não verificar")
        ):
            self.assertEqual(daemon.update_tick(self.pilot), "idle")
        self.assertFalse(self.pilot.restart_requested)

    def test_processo_velho_reinicia_sem_tocar_na_rede(self):
        core.process_update_generation()  # pin: ""
        core.write_update_generation("codigo-novo")
        with mock.patch.object(
            core, "load_config", return_value={"check_updates": True}
        ), mock.patch.object(
            core, "check_for_updates", side_effect=AssertionError("sem rede")
        ):
            self.assertEqual(daemon.update_tick(self.pilot), "restart")
        self.assertTrue(self.pilot.restart_requested)

    def test_em_dia_fica_ocioso(self):
        with mock.patch.object(
            core, "load_config", return_value={"check_updates": True}
        ), mock.patch.object(
            core, "check_for_updates", return_value={"status": "current"}
        ), mock.patch.object(
            core, "apply_update", side_effect=AssertionError("nada a aplicar")
        ):
            self.assertEqual(daemon.update_tick(self.pilot), "idle")
        self.assertFalse(self.pilot.restart_requested)

    def test_disponivel_aplica_e_reinicia(self):
        with mock.patch.object(
            core, "load_config", return_value={"check_updates": True}
        ), mock.patch.object(
            core, "check_for_updates", return_value={"status": "available"}
        ), mock.patch.object(
            core, "apply_update",
            return_value={"ok": True, "old_head": "aaa", "new_head": "bbb"},
        ):
            self.assertEqual(daemon.update_tick(self.pilot), "restart")
        self.assertTrue(self.pilot.restart_requested)
        self.assertFalse(core.update_lock_path().exists())  # lock solto no fim

    def test_falha_na_aplicacao_fica_ocioso_e_solta_o_lock(self):
        with mock.patch.object(
            core, "load_config", return_value={"check_updates": True}
        ), mock.patch.object(
            core, "check_for_updates", return_value={"status": "available"}
        ), mock.patch.object(
            core, "apply_update",
            return_value={"ok": False, "old_head": "aaa", "new_head": "aaa"},
        ):
            self.assertEqual(daemon.update_tick(self.pilot), "idle")
        self.assertFalse(self.pilot.restart_requested)
        self.assertFalse(core.update_lock_path().exists())

    def test_lock_ocupado_nao_aplica_e_nao_solta_o_lock_alheio(self):
        with mock.patch.object(
            core, "load_config", return_value={"check_updates": True}
        ), mock.patch.object(
            core, "check_for_updates", return_value={"status": "available"}
        ), mock.patch.object(
            core, "acquire_update_lock", return_value=False
        ), mock.patch.object(
            core, "release_update_lock"
        ) as solta, mock.patch.object(
            core, "apply_update", side_effect=AssertionError("sem lock não aplica")
        ):
            self.assertEqual(daemon.update_tick(self.pilot), "busy")
        solta.assert_not_called()

    def test_lock_do_daemon_cobre_o_daemon(self):
        """O lock usado pelo tique é o mesmo arquivo compartilhado."""
        self.assertTrue(core.acquire_update_lock())
        with mock.patch.object(
            core, "load_config", return_value={"check_updates": True}
        ), mock.patch.object(
            core, "check_for_updates", return_value={"status": "available"}
        ):
            # sem mockar acquire: o lock real criado acima manda no resultado
            self.assertEqual(daemon.update_tick(self.pilot), "busy")
        core.release_update_lock()


class DaemonAgendamentoTests(unittest.TestCase):
    """O daemon 24/7 agenda a verificação fora do loop e sai para religar."""

    @classmethod
    def setUpClass(cls):
        cls.tree = ast.parse(DAEMON_SRC.read_text(encoding="utf-8"))

    def test_update_tick_e_funcao_de_modulo(self):
        nomes = {
            node.name
            for node in self.tree.body
            if isinstance(node, ast.FunctionDef)
        }
        self.assertIn("update_tick", nomes)

    def test_main_agenda_e_religa_pelo_systemd(self):
        main = next(
            node
            for node in self.tree.body
            if isinstance(node, ast.FunctionDef) and node.name == "main"
        )
        corpo = ast.dump(main)
        self.assertIn("watch_updates", corpo)
        self.assertIn("update_tick", corpo)
        self.assertIn("UPDATE_RECHECK_SECONDS", corpo)
        self.assertIn("timeout_add_seconds", corpo)
        self.assertIn("Thread", corpo)  # rede fora do loop principal
        self.assertIn("worker", corpo)
        self.assertIn("process_update_generation", corpo)  # pin no arranque
        self.assertIn("restart_requested", corpo)  # sai com falha p/ systemd


class ControllerAstTestCase(unittest.TestCase):
    """Árvore do controller parseada uma vez; busca de métodos por nome."""

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


class JanelaStaleProcessTests(ControllerAstTestCase):
    """A janela percebe código novo aplicado por fora e se reinicia."""

    def test_init_pina_a_geracao_do_processo(self):
        init = self._method("MultiLUTWindow", "__init__")
        self.assertIn("process_update_generation", ast.dump(init))

    def test_anuncio_trata_processo_velho_reiniciando(self):
        metodo = self._method("MultiLUTWindow", "_announce_update")
        corpo = ast.dump(metodo)
        self.assertIn("stale_process", corpo)
        self.assertIn("restart_application", self._self_attrs(metodo))
        self.assertIn("_update_requested", corpo)

    def test_aplicacao_usa_o_lock_compartilhado(self):
        metodo = self._method("MultiLUTWindow", "_update_apply_thread")
        usados = {
            node.attr
            for node in ast.walk(metodo)
            if isinstance(node, ast.Attribute)
            and isinstance(node.value, ast.Name)
            and node.value.id == "core"
        }
        self.assertIn("acquire_update_lock", usados)
        self.assertIn("release_update_lock", usados)

    def test_lock_ocupado_reagenda_a_verificacao(self):
        busy = self._method("MultiLUTWindow", "_update_apply_busy")
        self.assertIn("_update_applying", self._self_attrs(busy))
        self.assertIn("_recheck_after_busy", self._self_attrs(busy))
        recheck = self._method("MultiLUTWindow", "_recheck_after_busy")
        self.assertIn("_updates_thread", ast.dump(recheck))


if __name__ == "__main__":
    unittest.main()
