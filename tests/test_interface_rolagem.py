#!/usr/bin/env python3
"""Regressão da interface: rolagem vertical nas abas e janela <= 1150x700.

Tela de referência: 1366x768 (área útil ~640-700px com painéis). Sem
PyGObject no ambiente, a estrutura do multilut_controller.py é verificada
via AST (o arquivo compila, mas o GTK não é instanciado), seguindo a
prática dos demais testes de usarem apenas o que roda sem GTK.
"""

import ast
import unittest
from pathlib import Path

import multilut_extra as extra

ROOT = Path(__file__).resolve().parent.parent
CONTROLLER_SRC = ROOT / "multilut_controller.py"


def _parse_controller() -> ast.Module:
    return ast.parse(CONTROLLER_SRC.read_text(encoding="utf-8"))


def _method(tree: ast.Module, class_name: str, method_name: str):
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            for item in node.body:
                if (
                    isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef))
                    and item.name == method_name
                ):
                    return item
    raise AssertionError(f"{class_name}.{method_name} não encontrado")


class ClampWindowSizeTests(unittest.TestCase):
    """multilut_extra.clamp_window_size: piso 420x400, teto 1150x700."""

    def test_identidade_dentro_dos_limites(self):
        self.assertEqual(extra.clamp_window_size(1100, 680), (1100, 680))
        self.assertEqual(extra.clamp_window_size(1040, 700), (1040, 700))

    def test_teto_1150x700(self):
        self.assertEqual(extra.WINDOW_MAX_W, 1150)
        self.assertEqual(extra.WINDOW_MAX_H, 700)
        self.assertEqual(
            extra.clamp_window_size(2000, 1200),
            (extra.WINDOW_MAX_W, extra.WINDOW_MAX_H),
        )

    def test_estado_salvo_de_monitor_maior_cabe_na_referencia(self):
        # config guardada numa tela grande não pode abrir fora de 1366x768
        self.assertEqual(extra.clamp_window_size(1400, 900), (1150, 700))

    def test_piso_420x400(self):
        self.assertEqual(extra.WINDOW_MIN_W, 420)
        self.assertEqual(extra.WINDOW_MIN_H, 400)
        self.assertEqual(
            extra.clamp_window_size(0, 0),
            (extra.WINDOW_MIN_W, extra.WINDOW_MIN_H),
        )


class GeometriaReferenciaTests(unittest.TestCase):
    """O tamanho padrão da janela cabe na tela de referência 1366x768."""

    REF_W, REF_H = 1366, 768

    def test_padrao_dentro_do_teto_1150x700(self):
        self.assertLessEqual(extra.WINDOW_DEFAULT_W, extra.WINDOW_MAX_W)
        self.assertLessEqual(extra.WINDOW_DEFAULT_H, extra.WINDOW_MAX_H)

    def test_padrao_cabe_na_area_util_de_1366x768(self):
        usable_w = int(self.REF_W * 0.92)  # mesmo fator de _fit_size_to_monitor
        usable_h = int(self.REF_H * 0.92)
        self.assertLessEqual(extra.WINDOW_DEFAULT_W, usable_w)
        self.assertLessEqual(extra.WINDOW_DEFAULT_H, usable_h)

    def test_minimo_nao_excede_o_padrao(self):
        self.assertLessEqual(extra.WINDOW_MIN_W, extra.WINDOW_DEFAULT_W)
        self.assertLessEqual(extra.WINDOW_MIN_H, extra.WINDOW_DEFAULT_H)


class EstruturaAbasTests(unittest.TestCase):
    """Cada aba do ViewStack nasce dentro de um Gtk.ScrolledWindow."""

    def setUp(self):
        self.tree = _parse_controller()

    def _call_attrs(self, node):
        for child in ast.walk(node):
            if isinstance(child, ast.Call) and isinstance(child.func, ast.Attribute):
                yield child

    def test_cada_aba_do_viewstack_e_envolvida_em_scrolledwindow(self):
        init = _method(self.tree, "MultiLUTWindow", "__init__")
        paginas = [
            call
            for call in self._call_attrs(init)
            if call.func.attr == "add_titled"
        ]
        self.assertEqual(len(paginas), 4, "O ViewStack deve ter 4 abas")
        for call in paginas:
            primeiro = call.args[0]
            self.assertTrue(
                isinstance(primeiro, ast.Call)
                and isinstance(primeiro.func, ast.Attribute)
                and primeiro.func.attr == "_wrap_scrolled",
                f"aba '{call.args[1].value}' não está envolvida em _wrap_scrolled",
            )

    def test_wrap_scrolled_policy_never_automatic_e_filho_vexpand(self):
        wrap = _method(self.tree, "MultiLUTWindow", "_wrap_scrolled")
        cria_scroller = False
        set_child = False
        vexpand_true = False
        policy_args = None
        for call in self._call_attrs(wrap):
            if call.func.attr == "ScrolledWindow":
                cria_scroller = True
            elif call.func.attr == "set_policy":
                policy_args = [
                    a.attr for a in call.args if isinstance(a, ast.Attribute)
                ]
            elif call.func.attr == "set_vexpand":
                vexpand_true = bool(
                    call.args
                    and isinstance(call.args[0], ast.Constant)
                    and call.args[0].value is True
                )
            elif call.func.attr == "set_child":
                set_child = True
        self.assertTrue(cria_scroller, "_wrap_scrolled deve criar Gtk.ScrolledWindow")
        self.assertEqual(
            policy_args,
            ["NEVER", "AUTOMATIC"],
            "policy deve ser (NEVER, AUTOMATIC): sem rolagem horizontal",
        )
        self.assertTrue(vexpand_true, "o filho deve receber vexpand=True")
        self.assertTrue(set_child, "o filho deve ser anexado ao scroller")

    def test_tamanho_padrao_vem_das_constantes_testaveis(self):
        init = _method(self.tree, "MultiLUTWindow", "__init__")
        nomes = {
            node.attr
            for node in ast.walk(init)
            if isinstance(node, ast.Attribute)
            and isinstance(node.value, ast.Name)
            and node.value.id == "extra"
            and node.attr in {"WINDOW_DEFAULT_W", "WINDOW_DEFAULT_H"}
        }
        self.assertEqual(nomes, {"WINDOW_DEFAULT_W", "WINDOW_DEFAULT_H"})

    def test_fit_size_aplica_o_clamp_puro(self):
        fit = _method(self.tree, "MultiLUTWindow", "_fit_size_to_monitor")
        chamadas = [
            call.func.attr
            for call in self._call_attrs(fit)
            if isinstance(call.func.value, ast.Name)
            and call.func.value.id == "extra"
        ]
        self.assertIn("clamp_window_size", chamadas)

    def test_sem_largura_fixa_de_420px_no_dropdown(self):
        for call in self._call_attrs(self.tree):
            if (
                call.func.attr == "set_size_request"
                and len(call.args) == 2
                and all(isinstance(a, ast.Constant) for a in call.args)
                and call.args[0].value == 420
                and call.args[1].value == -1
            ):
                self.fail(
                    "set_size_request(420, -1) voltou ao código "
                    "(dropdown de instalação deve ser responsivo)"
                )


if __name__ == "__main__":
    unittest.main()
