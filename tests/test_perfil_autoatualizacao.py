#!/usr/bin/env python3
"""Perfil ativo verdadeiro + autoatualização sem ação do usuário.

Dois pedidos no mesmo fluxo: (1) a janela/bandeja pararam de mostrar
corretamente qual perfil está aplicado — o daemon escreve por fora e a
gravação atômica nem sempre dispara o monitor de arquivo; (2) a atualização
deve ser recebida e aplicada sozinha, sem diálogo nem clique. Verificação
estrutural via AST (sem PyGObject) + constantes puras.
"""

import argparse
import ast
import unittest
from pathlib import Path
from unittest import mock

import multilut_core as core
import multilut_extra as extra

CONTROLLER_SRC = Path(__file__).resolve().parent.parent / "multilut_controller.py"


class RecheckConstanteTests(unittest.TestCase):
    """Intervalo da reverificação automática de atualizações."""

    def test_intervalo_de_reverificacao(self):
        self.assertEqual(core.UPDATE_RECHECK_SECONDS, 1800)  # 30 min
        self.assertGreater(core.UPDATE_RECHECK_SECONDS, 6)  # não é o tique inicial


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


class PerfilAtivoTests(ControllerAstTestCase):
    """A exibição segue o shader (verdade), não o que a janela aplicou."""

    def test_init_guarda_o_ultimo_perfil_visto(self):
        init = self._method("MultiLUTWindow", "__init__")
        self.assertIn("_last_seen_active", self._self_attrs(init))

    def test_tique_de_jogo_chama_a_sincronizacao(self):
        metodo = self._method("MultiLUTWindow", "refresh_game_status")
        self.assertIn("sync_active_profile", self._self_attrs(metodo))

    def test_sync_relê_o_shader_e_compara_com_o_visto(self):
        metodo = self._method("MultiLUTWindow", "sync_active_profile")
        corpo = ast.dump(metodo)
        self.assertIn("read_active_profile", corpo)
        self.assertIn("_last_seen_active", corpo)
        self.assertIn("shader_valid", corpo)

    def test_sync_reaponta_exibicao_e_bandeja(self):
        metodo = self._method("MultiLUTWindow", "sync_active_profile")
        self.assertIn("refresh_shader_status", self._self_attrs(metodo))
        # o menu da bandeja é atualizado via application._refresh_tray(...)
        self.assertIn("_refresh_tray", ast.dump(metodo))

    def test_refresh_shader_status_registra_o_visto(self):
        metodo = self._method("MultiLUTWindow", "refresh_shader_status")
        self.assertIn("_last_seen_active", ast.dump(metodo))

    def test_notificacao_externa_nao_duplica_com_daemon(self):
        metodo = self._method("MultiLUTWindow", "refresh_shader_status")
        guardado = False
        for node in ast.walk(metodo):
            if isinstance(node, ast.If) and "_daemon_pilot_active" in ast.dump(node.test):
                for filho in node.body:
                    if any(
                        isinstance(c, ast.Call)
                        and isinstance(c.func, ast.Attribute)
                        and c.func.attr == "_notify_profile_change"
                        for c in ast.walk(filho)
                    ):
                        guardado = True
        self.assertTrue(
            guardado,
            "_notify_profile_change deve ficar sob 'not self._daemon_pilot_active'",
        )


class AutoatualizacaoTests(ControllerAstTestCase):
    """A atualização é recebida e aplicada sozinha, sem diálogo nem clique."""

    def test_init_tem_as_flags_do_fluxo(self):
        init = self._method("MultiLUTWindow", "__init__")
        attrs = self._self_attrs(init)
        self.assertIn("_update_applying", attrs)
        self.assertIn("_auto_update_flow", attrs)

    def test_init_agenda_a_reverificacao_periodica(self):
        init = self._method("MultiLUTWindow", "__init__")
        corpo = ast.dump(init)
        self.assertIn("_check_updates_periodic", corpo)
        self.assertIn("UPDATE_RECHECK_SECONDS", corpo)

    def test_periodica_verifica_config_e_evita_sobreposicao(self):
        metodo = self._method("MultiLUTWindow", "_check_updates_periodic")
        self.assertIn("_update_applying", self._self_attrs(metodo))
        corpo = ast.dump(metodo)
        self.assertIn("check_updates", corpo)  # chave do config
        self.assertIn("SOURCE_CONTINUE", corpo)

    def test_thread_marca_o_modo_automatico(self):
        metodo = self._method("MultiLUTWindow", "_updates_thread")
        self.assertIn("_update_requested", ast.dump(metodo))

    def test_anuncio_aceita_modo_automatico(self):
        metodo = self._method("MultiLUTWindow", "_announce_update")
        self.assertIn("auto", [a.arg for a in metodo.args.args])
        # consome o pedido manual para as próximas verificações voltarem a ser automáticas
        self.assertIn("_update_requested", ast.dump(metodo))

    def test_ramo_auto_aplica_sem_dialogo(self):
        metodo = self._method("MultiLUTWindow", "_announce_update")
        auto_call = any(
            isinstance(n, ast.Call)
            and isinstance(n.func, ast.Attribute)
            and n.func.attr == "_start_update_apply"
            and any(
                k.arg == "auto"
                and isinstance(k.value, ast.Constant)
                and k.value.value is True
                for k in n.keywords
            )
            for n in ast.walk(metodo)
        )
        self.assertTrue(auto_call, "o ramo auto deve chamar _start_update_apply(auto=True)")
        # o diálogo continua existindo, mas só para verificação manual
        dialogos = [
            n
            for n in ast.walk(metodo)
            if isinstance(n, ast.Call)
            and isinstance(n.func, ast.Attribute)
            and n.func.attr == "show_update_dialog"
        ]
        self.assertEqual(len(dialogos), 1)
        self.assertFalse(
            any(
                isinstance(n, ast.If) and "auto" in ast.dump(n.test)
                and any(
                    isinstance(c, ast.Call)
                    and isinstance(c.func, ast.Attribute)
                    and c.func.attr == "show_update_dialog"
                    for c in ast.walk(n)
                )
                for n in ast.walk(metodo)
            ),
            "show_update_dialog não pode rodar dentro do ramo auto",
        )

    def test_aplicacao_marca_as_flags(self):
        metodo = self._method("MultiLUTWindow", "_start_update_apply")
        attrs = self._self_attrs(metodo)
        self.assertIn("_update_applying", attrs)
        self.assertIn("_auto_update_flow", attrs)

    def test_conclusao_religa_o_daemon_e_reinicia(self):
        metodo = self._method("MultiLUTWindow", "_update_apply_done")
        attrs = self._self_attrs(metodo)
        self.assertIn("_update_applying", attrs)
        self.assertIn("restart_application", attrs)
        self.assertIn("_confirm_restart", attrs)
        # o daemon em serviço roda código antigo até religar
        extra_attrs = {
            node.attr
            for node in ast.walk(metodo)
            if isinstance(node, ast.Attribute)
            and isinstance(node.value, ast.Name)
            and node.value.id == "extra"
        }
        self.assertIn("daemon_systemctl", extra_attrs)

    def test_reinicio_preserva_o_modo_bandeja(self):
        metodo = self._method("MultiLUTWindow", "restart_application")
        corpo = ast.dump(metodo)
        self.assertIn("is_visible", corpo)
        self.assertIn("--minimized", corpo)


class DaemonRestartCliTests(unittest.TestCase):
    """multilut-ctl daemon restart: stop + start (religa com o código atual)."""

    def test_restart_para_e_religa(self):
        import multilut_ctl

        with mock.patch.object(
            extra, "daemon_stop", return_value=(True, "encerrando")
        ) as stop_mock, mock.patch.object(
            extra,
            "daemon_start",
            return_value=(True, "Daemon iniciado (piloto ativo sem janela)."),
        ) as start_mock, mock.patch("builtins.print"):
            rc = multilut_ctl.cmd_daemon(argparse.Namespace(acao="restart"))
        self.assertEqual(rc, 0)
        stop_mock.assert_called_once_with()
        start_mock.assert_called_once_with()

    def test_restart_reporta_falha_do_reinicio(self):
        import multilut_ctl

        with mock.patch.object(
            extra, "daemon_stop", return_value=(True, "encerrando")
        ), mock.patch.object(
            extra, "daemon_start", return_value=(False, "O daemon não respondeu após o início.")
        ), mock.patch("builtins.print"):
            rc = multilut_ctl.cmd_daemon(argparse.Namespace(acao="restart"))
        self.assertEqual(rc, 1)


if __name__ == "__main__":
    unittest.main()
