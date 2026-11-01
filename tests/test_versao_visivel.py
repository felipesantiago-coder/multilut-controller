#!/usr/bin/env python3
"""Versão visível e verificação transparente de atualizações.

O usuário não conseguia distinguir instalação fresca de instalação velha:
todo rótulo mostrava sempre "v1.9.0" (a constante não subia), a verificação
não deixava nenhum registro de que havia rodado e o clone git gastava API
de releases que este repositório nem publica. Cobertura: `display_version`
com/sem commit, registro e leitura da última verificação no estado do app,
verificação registrando o resultado, clone git sem API, CLI `update check`
e as superfícies da interface que precisam carregar a versão com commit.
"""

import os
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest import mock

import multilut_core as core
import multilut_ctl as ctl
import multilut_extra as extra

REPO = Path(__file__).resolve().parent.parent
CONTROLLER_SRC = REPO / "multilut_controller.py"
EXTRA_SRC = REPO / "multilut_extra.py"


class SandboxStateTestCase(unittest.TestCase):
    """Tempdir + XDG_STATE_HOME isolado (nenhum estado real é tocado)."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)
        patcher = mock.patch.dict(
            os.environ, {"XDG_STATE_HOME": str(self.tmp / "state")}
        )
        patcher.start()
        self.addCleanup(patcher.stop)


class VersaoBaseTests(unittest.TestCase):
    """A versão base precisa subir junto com as correções publicadas."""

    def test_versao_base_saiu_do_1_9_0(self):
        self.assertNotEqual(core.APP_VERSION, "1.9.0")

    def test_versao_tem_tres_componentes(self):
        partes = core.APP_VERSION.split(".")
        self.assertEqual(len(partes), 3)
        self.assertTrue(all(p.isdigit() for p in partes))


class DisplayVersionTests(unittest.TestCase):
    """Versão + commit instalado: prova visível de código fresco."""

    def test_com_commit_inclui_prefixo_de_sete(self):
        with mock.patch.object(
            core, "installed_commit", return_value="abc1234def5678"
        ):
            self.assertEqual(
                core.display_version(), f"{core.APP_VERSION} (abc1234)"
            )

    def test_commit_completo_e_truncado_a_sete(self):
        completo = "a" * 40
        with mock.patch.object(core, "installed_commit", return_value=completo):
            self.assertEqual(
                core.display_version(), f"{core.APP_VERSION} ({'a' * 7})"
            )

    def test_sem_commit_mostra_somente_a_versao(self):
        with mock.patch.object(core, "installed_commit", return_value=None):
            self.assertEqual(core.display_version(), core.APP_VERSION)

    def test_repositorio_e_passado_ao_leitor_de_commit(self):
        destino = Path("/qualquer/diretorio")
        with mock.patch.object(core, "installed_commit", return_value="abc1234") as le:
            resultado = core.display_version(repo=destino)
        le.assert_called_once_with(destino)
        self.assertIn("abc1234", resultado)

    def test_commit_curto_nao_e_alterado(self):
        with mock.patch.object(core, "installed_commit", return_value="abc1234"):
            self.assertEqual(
                core.display_version(), f"{core.APP_VERSION} (abc1234)"
            )


class RegistroUltimaVerificacaoTests(SandboxStateTestCase):
    """O verificador deixa rastro: quando rodou e o que decidiu."""

    def test_caminho_fica_no_estado_do_app(self):
        self.assertEqual(
            core.last_check_path(),
            core.app_state_dir() / core.LAST_CHECK_FILE,
        )

    def test_registra_e_le_de_volta(self):
        core.record_last_check(
            {
                "status": "current",
                "local": "abc1234",
                "remote": "abc1234def5678",
                "message": "Você já está na versão mais recente.",
            }
        )
        record = core.last_check_record()
        self.assertIsNotNone(record)
        self.assertEqual(record["status"], "current")
        self.assertEqual(record["local"], "abc1234")
        self.assertEqual(record["remote"], "abc1234def5678")
        self.assertIn("versão mais recente", record["message"])
        self.assertTrue(record["when"])  # carimbo de tempo presente

    def test_resultado_sem_campos_usa_padrao(self):
        core.record_last_check({})
        record = core.last_check_record()
        self.assertEqual(record["status"], "")
        self.assertIsNone(record["local"])
        self.assertIsNone(record["remote"])
        self.assertEqual(record["message"], "")

    def test_sem_registro_retorna_none(self):
        self.assertIsNone(core.last_check_record())

    def test_arquivo_corrompido_retorna_none(self):
        core.record_last_check({"status": "current"})
        core.last_check_path().write_text("nao-json", encoding="utf-8")
        self.assertIsNone(core.last_check_record())

    def test_json_que_nao_e_objeto_retorna_none(self):
        core.record_last_check({})  # garante o diretório do estado
        core.last_check_path().write_text("[1, 2, 3]", encoding="utf-8")
        self.assertIsNone(core.last_check_record())

    def test_falha_de_disco_nao_levanta(self):
        bloqueio = self.tmp / "arquivo"
        bloqueio.write_text("x", encoding="utf-8")
        with mock.patch.object(core, "last_check_path", return_value=bloqueio):
            core.record_last_check({"status": "current"})  # não pode levantar


class VerificacaoRegistraTests(SandboxStateTestCase):
    """Toda `check_for_updates` deixa o registro no estado do app."""

    def test_verificacao_em_dia_grava_registro(self):
        with mock.patch.object(core, "local_git_head", return_value="abc1234"), \
             mock.patch.object(core, "installed_commit", return_value="abc1234"), \
             mock.patch.object(core, "git_remote_head", return_value="abc1234f"):
            result = core.check_for_updates()
        self.assertEqual(result["status"], "current")
        record = core.last_check_record()
        self.assertEqual(record["status"], "current")
        self.assertEqual(record["local"], "abc1234")
        self.assertEqual(record["remote"], "abc1234f")

    def test_verificacao_com_commits_novos_grava_registro(self):
        with mock.patch.object(core, "local_git_head", return_value="abc1234"), \
             mock.patch.object(core, "installed_commit", return_value="abc1234"), \
             mock.patch.object(core, "git_remote_head", return_value="def5678f"):
            result = core.check_for_updates()
        self.assertEqual(result["status"], "available")
        self.assertEqual(core.last_check_record()["status"], "available")


class CloneGitSemApiTests(SandboxStateTestCase):
    """Clone git decide por ls-remote; API só para instalações sem git."""

    def test_clone_nao_consulta_api_de_release_nem_de_commits(self):
        with mock.patch.object(core, "local_git_head", return_value="abc1234"), \
             mock.patch.object(core, "installed_commit", return_value="abc1234"), \
             mock.patch.object(core, "git_remote_head", return_value="abc1234f"), \
             mock.patch.object(core, "fetch_latest_release") as release, \
             mock.patch.object(core, "fetch_latest_commit") as commits, \
             mock.patch.object(core, "fetch_remote_app_version") as raw:
            result = core.check_for_updates()
        self.assertEqual(result["status"], "current")
        release.assert_not_called()
        commits.assert_not_called()
        raw.assert_not_called()

    def test_instalacao_sem_git_continua_consultando_a_release(self):
        with mock.patch.object(core, "local_git_head", return_value=None), \
             mock.patch.object(core, "installed_commit", return_value=None), \
             mock.patch.object(core, "fetch_latest_commit", return_value=None), \
             mock.patch.object(core, "fetch_remote_app_version", return_value=None), \
             mock.patch.object(core, "fetch_latest_release", return_value=None) as release:
            result = core.check_for_updates()
        self.assertEqual(result["status"], "unknown")
        release.assert_called_once()

    def test_instalacao_sem_git_com_release_nova_detecta(self):
        release = {"tag": "v9.0.0", "name": "Nova", "url": "u"}
        with mock.patch.object(core, "local_git_head", return_value=None), \
             mock.patch.object(core, "installed_commit", return_value="abc1234"), \
             mock.patch.object(core, "fetch_latest_commit", return_value=None), \
             mock.patch.object(core, "fetch_remote_app_version", return_value=None), \
             mock.patch.object(core, "fetch_latest_release", return_value=release):
            result = core.check_for_updates()
        self.assertEqual(result["status"], "available")
        self.assertIn("v9.0.0", result["message"])


class CtlAtualizacaoTests(SandboxStateTestCase):
    """`multilut-ctl update check` mostra a versão com commit."""

    def _rodar(self, result: dict, version: str = "9.9.9 (abc1234)") -> tuple[int, str]:
        argumentos = type("Args", (), {"acao": "check"})()
        with mock.patch.object(core, "check_for_updates", return_value=result), \
             mock.patch.object(core, "display_version", return_value=version):
            saida = StringIO()
            with redirect_stdout(saida):
                codigo = ctl.cmd_update(argumentos)
        return codigo, saida.getvalue()

    def test_em_dia_mostra_versao_com_commit(self):
        result = {"status": "current", "local": "abc1234", "message": "tudo certo"}
        codigo, texto = self._rodar(result)
        self.assertEqual(codigo, 0)
        self.assertIn("versão instalada: 9.9.9 (abc1234)", texto)
        self.assertIn("tudo certo", texto)

    def test_sem_commit_acrescenta_a_marca(self):
        result = {"status": "unknown", "local": None, "message": "falhou"}
        codigo, texto = self._rodar(result)
        self.assertEqual(codigo, 2)
        self.assertIn("(sem git e sem marcação)", texto)

    def test_update_disponivel_recomenda_o_comando(self):
        result = {"status": "available", "local": "abc1234", "message": "ha novos"}
        codigo, texto = self._rodar(result)
        self.assertEqual(codigo, 1)
        self.assertIn("multilut-ctl update apply", texto)


class SuperficiesVisiveisTests(unittest.TestCase):
    """A versão com commit aparece em todas as superfícies do usuário."""

    def setUp(self) -> None:
        self.controller = CONTROLLER_SRC.read_text(encoding="utf-8")
        self.extra = EXTRA_SRC.read_text(encoding="utf-8")

    def test_dialogo_sobre_mostra_versao_com_commit(self):
        self.assertIn("about.set_version(core.display_version())", self.controller)

    def test_cabecalho_do_sistema_mostra_versao_com_commit(self):
        self.assertIn(
            'label=f"MultiLUT Controller {core.display_version()}"', self.controller
        )

    def test_toast_de_em_dia_mostra_versao_com_commit(self):
        self.assertIn(
            'f"Você já está na versão mais recente ({core.display_version()})."',
            self.controller,
        )

    def test_dialogo_de_atualizacao_mostra_versao_com_commit(self):
        self.assertIn(
            'f"Versão instalada: {core.display_version()}.', self.controller
        )

    def test_rotulo_disponivel_usa_a_versao_como_nota_local(self):
        self.assertIn("local_note = core.display_version()", self.controller)

    def test_diagnostico_usa_versao_com_commit(self):
        self.assertIn(
            'f"MultiLUT Controller {core.display_version()} — relatório de '
            'diagnóstico"',
            self.extra,
        )

    def test_diagnostico_mostra_a_ultima_verificacao(self):
        self.assertIn("Última verificação de atualização:", self.extra)
        self.assertIn("core.last_check_record()", self.extra)

    def test_ctl_imprime_a_versao_com_commit(self):
        ctl_src = (REPO / "multilut_ctl.py").read_text(encoding="utf-8")
        self.assertIn("f\"versão instalada: {core.display_version()}", ctl_src)


if __name__ == "__main__":
    unittest.main()
