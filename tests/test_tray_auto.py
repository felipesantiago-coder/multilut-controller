#!/usr/bin/env python3
"""Automação do indicador de bandeja: o app busca sozinho o que falta.

Cobre os helpers puros de multilut_extra (estado da extensão AppIndicator,
ensure_tray_environment, item do doctor) e a integração na janela via AST
(sem PyGObject no ambiente).
"""

import ast
import subprocess
import unittest
from pathlib import Path
from unittest import mock

import multilut_extra as extra
import multilut_tray as tray

CONTROLLER_SRC = Path(__file__).resolve().parent.parent / "multilut_controller.py"
UUID = extra.GNOME_APPINDICATOR_UUID


def _completed(returncode: int = 0, stdout: str = "", stderr: str = ""):
    return subprocess.CompletedProcess([], returncode, stdout, stderr)


class ShellExtensionUuidsTests(unittest.TestCase):
    def test_lista_vazia_padrao_gsettings(self):
        self.assertEqual(extra._shell_extension_uuids("@as []"), [])

    def test_lista_com_uuids(self):
        raw = "['appindicatorsupport@rgcjonas.gmail.com', 'dash-to-dock@micxgx.gmail.com']"
        self.assertEqual(
            extra._shell_extension_uuids(raw),
            ["appindicatorsupport@rgcjonas.gmail.com", "dash-to-dock@micxgx.gmail.com"],
        )

    def test_aceita_aspas_duplas_e_espacos(self):
        self.assertEqual(
            extra._shell_extension_uuids('  [ "a@x", "b@y" ]  '),
            ["a@x", "b@y"],
        )


class GnomeAppIndicatorStatusTests(unittest.TestCase):
    def _run_desktop(self, desktop: str):
        return mock.patch.dict(
            "os.environ", {"XDG_CURRENT_DESKTOP": desktop}, clear=False
        )

    def test_nao_gnome_quando_desktop_outra_shell(self):
        with self._run_desktop("KDE"), mock.patch.object(
            extra, "subprocess"
        ) as subprocess_mock:
            state, detail = extra.gnome_appindicator_status()
        self.assertEqual(state, "no-gnome")
        subprocess_mock.run.assert_not_called()

    def test_missing_quando_info_falha(self):
        with self._run_desktop("GNOME"), mock.patch.object(
            extra.subprocess,
            "run",
            return_value=_completed(returncode=1),
        ) as run_mock:
            state, detail = extra.gnome_appindicator_status()
        self.assertEqual(state, "missing")
        self.assertIn(UUID, detail)
        self.assertEqual(run_mock.call_args_list[0].args[0][:2],
                         ["gnome-extensions", "info"])

    def test_enabled_quando_na_lista_de_ativas(self):
        with self._run_desktop("GNOME"), mock.patch.object(
            extra.subprocess,
            "run",
            side_effect=[
                _completed(0),
                _completed(0, stdout=f"['{UUID}']"),
                _completed(0, stdout="@as []"),
            ],
        ):
            state, _ = extra.gnome_appindicator_status()
        self.assertEqual(state, "enabled")

    def test_enabled_quando_enabled_extensions_vazio_e_nao_desativada(self):
        # regra do GNOME Shell: '@as []' significa "todas exceto desativadas"
        with self._run_desktop("GNOME"), mock.patch.object(
            extra.subprocess,
            "run",
            side_effect=[
                _completed(0),
                _completed(0, stdout="@as []"),
                _completed(0, stdout="@as []"),
            ],
        ):
            state, _ = extra.gnome_appindicator_status()
        self.assertEqual(state, "enabled")

    def test_disabled_quando_apenas_na_lista_de_desativadas(self):
        with self._run_desktop("GNOME"), mock.patch.object(
            extra.subprocess,
            "run",
            side_effect=[
                _completed(0),
                _completed(0, stdout="@as []"),
                _completed(0, stdout=f"['{UUID}']"),
            ],
        ):
            state, detail = extra.gnome_appindicator_status()
        self.assertEqual(state, "disabled")
        self.assertIn("desativada", detail)

    def test_unknown_sem_gnome_extensions(self):
        with self._run_desktop("GNOME"), mock.patch.object(
            extra.subprocess,
            "run",
            side_effect=FileNotFoundError("gnome-extensions"),
        ):
            state, _ = extra.gnome_appindicator_status()
        self.assertEqual(state, "unknown")


class EnsureTrayEnvironmentTests(unittest.TestCase):
    def test_binding_ausente_orienta_o_comando(self):
        with mock.patch.object(
            extra, "tray_binding_status", return_value=(False, extra.TRAY_BINDING_HINT)
        ):
            ok, detail = extra.ensure_tray_environment()
        self.assertFalse(ok)
        self.assertIn("libayatana-appindicator", detail)
        self.assertIn("install.sh", detail)

    def test_ativa_extensao_desativada_e_confirma(self):
        with mock.patch.object(
            extra, "tray_binding_status", return_value=(True, "binding ok")
        ), mock.patch.object(
            extra,
            "gnome_appindicator_status",
            side_effect=[("disabled", "desativada"), ("enabled", "ativa")],
        ), mock.patch.object(
            extra, "_gnome_extension_enable", return_value=(True, "")
        ) as enable_mock:
            ok, detail = extra.ensure_tray_environment()
        self.assertTrue(ok)
        self.assertEqual(detail, "extensão AppIndicator ativada agora")
        enable_mock.assert_called_once_with()

    def test_falha_de_ativacao_e_reportada(self):
        with mock.patch.object(
            extra, "tray_binding_status", return_value=(True, "binding ok")
        ), mock.patch.object(
            extra,
            "gnome_appindicator_status",
            side_effect=[("disabled", "desativada"), ("disabled", "desativada")],
        ), mock.patch.object(
            extra, "_gnome_extension_enable", return_value=(False, "erro do shell")
        ):
            ok, detail = extra.ensure_tray_environment()
        self.assertFalse(ok)
        self.assertIn("não consegui ativar", detail)

    def test_extensao_ausente_orienta_instalacao(self):
        with mock.patch.object(
            extra, "tray_binding_status", return_value=(True, "binding ok")
        ), mock.patch.object(
            extra,
            "gnome_appindicator_status",
            return_value=("missing", f"extensão AppIndicator não instalada ({UUID})"),
        ):
            ok, detail = extra.ensure_tray_environment()
        self.assertFalse(ok)
        self.assertIn(UUID, detail)

    def test_tudo_certo_e_silenciosamente_ok(self):
        with mock.patch.object(
            extra, "tray_binding_status", return_value=(True, "binding ok")
        ), mock.patch.object(
            extra,
            "gnome_appindicator_status",
            return_value=("enabled", "ativa"),
        ):
            ok, detail = extra.ensure_tray_environment()
        self.assertTrue(ok)
        self.assertIn("indicador pronto", detail)


class TrayBindingStatusTests(unittest.TestCase):
    def test_consistente_com_tray_supported(self):
        ok, detail = extra.tray_binding_status()
        self.assertIsInstance(ok, bool)
        self.assertTrue(detail)
        self.assertEqual(ok, tray.tray_supported())


class DiagnosticoTrayTests(unittest.TestCase):
    def test_doctor_tem_item_do_indicador(self):
        items = {item["title"]: item for item in extra.diagnostic_report()}
        self.assertIn("Ícone na bandeja (indicador)", items)
        bandeja = items["Ícone na bandeja (indicador)"]
        self.assertIn(bandeja["state"], {"ok", "info", "warn"})

    def test_doctor_sem_binding_avisa_com_o_comando(self):
        with mock.patch.object(
            extra, "tray_binding_status", return_value=(False, extra.TRAY_BINDING_HINT)
        ):
            state, detail = extra.tray_doctor_status()
        self.assertEqual(state, "warn")
        self.assertIn("libayatana-appindicator-gtk3", detail)

    def test_doctor_extensao_desativada_aponta_automacao(self):
        with mock.patch.object(
            extra, "tray_binding_status", return_value=(True, "binding ok")
        ), mock.patch.object(
            extra,
            "gnome_appindicator_status",
            return_value=("disabled", "extensão AppIndicator instalada, mas desativada"),
        ):
            state, detail = extra.tray_doctor_status()
        self.assertEqual(state, "info")
        self.assertIn("ativa sozinho", detail)


class IntegracaoInterfaceTests(unittest.TestCase):
    """A aplicação garante o ambiente do indicador (AST, sem PyGObject)."""

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

    def test_setup_tray_agenda_a_verificacao_nos_dois_caminhos(self):
        setup = self._method("MultiLUTApplication", "setup_tray")
        attrs = {
            node.attr for node in ast.walk(setup) if isinstance(node, ast.Attribute)
        }
        self.assertIn("_schedule_tray_environment", attrs)

    def test_thread_chama_ensure_tray_environment(self):
        thread = self._method("MultiLUTApplication", "_tray_environment_thread")
        attrs = {
            node.attr
            for node in ast.walk(thread)
            if isinstance(node, ast.Attribute)
            and isinstance(node.value, ast.Name)
            and node.value.id == "extra"
        }
        self.assertIn("ensure_tray_environment", attrs)

    def test_verificacao_roda_fora_da_main_loop(self):
        agenda = self._method("MultiLUTApplication", "_schedule_tray_environment")
        usa_thread = any(
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "Thread"
            for node in ast.walk(agenda)
        )
        self.assertTrue(usa_thread, "a garantia deve rodar em thread, sem travar a UI")

    def test_verificacao_unica_por_sessao(self):
        agenda = self._method("MultiLUTApplication", "_schedule_tray_environment")
        corpo = ast.dump(agenda)
        self.assertIn("_tray_env_done", corpo)


if __name__ == "__main__":
    unittest.main()
