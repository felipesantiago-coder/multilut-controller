#!/usr/bin/env python3
"""Fundações do lote 7: análise das LUTs no doctor e brilho DDC/CI por mapa."""

from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import multilut_core as core
import multilut_extra as extra

try:
    import numpy as np  # noqa: E402
    from PIL import Image  # noqa: E402

    import multilut_atlas as atlas  # noqa: E402

    NUMPY_OK = True
except (ImportError, ValueError):  # pragma: no cover
    NUMPY_OK = False


class Lote7TestCase(unittest.TestCase):
    """Sandbox de HOME + XDG_STATE_HOME por teste."""

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


class DdcParsingTests(Lote7TestCase):
    def test_formato_brief_padrao(self):
        out = "VCP 10 C B 50 100\n"
        self.assertEqual(extra.parse_ddc_brightness(out), 50)

    def test_maximo_nao_100(self):
        out = "VCP 10 C B 35 70\n"
        self.assertEqual(extra.parse_ddc_brightness(out), 50)

    def test_valor_unico(self):
        self.assertEqual(extra.parse_ddc_brightness("VCP 10 C B 77\n"), 77)

    def test_lixo_e_vazio(self):
        self.assertIsNone(extra.parse_ddc_brightness(""))
        self.assertIsNone(extra.parse_ddc_brightness("sem numeros aqui"))
        self.assertIsNone(extra.parse_ddc_brightness(None))

    def test_fora_do_intervalo(self):
        self.assertEqual(extra.parse_ddc_brightness("VCP 10 C B 250 100\n"), 100)


class FakeDdc:
    """Runner/getter falsos de ddcutil para os testes do controlador."""

    def __init__(self, current: int = 80, fail: bool = False):
        self.current = current
        self.fail = fail
        self.set_calls: list[int] = []
        self.get_calls = 0

    def getter(self) -> int | None:
        self.get_calls += 1
        return self.current

    def runner(self, argv: list[str]):
        self.set_calls.append(int(argv[-1]))
        return mock.Mock(returncode=1 if self.fail else 0)


class BrightnessControllerTests(Lote7TestCase):
    def test_desligado_nao_toca_no_ddc_e_restaura(self):
        fake = FakeDdc()
        controller = extra.BrightnessController(runner=fake.runner, getter=fake.getter)
        config = {"ddc": {"enabled": False, "levels": {"tell": 40}}}
        self.assertIsNone(controller.apply_for_map(config, "tell"))
        self.assertEqual(fake.set_calls, [])

    def test_aplica_nivel_e_captura_original_uma_vez(self):
        fake = FakeDdc(current=80)
        controller = extra.BrightnessController(runner=fake.runner, getter=fake.getter)
        config = {"ddc": {"enabled": True, "levels": {"tell": 40, "sinjar": 90}}}
        message = controller.apply_for_map(config, "tell")
        self.assertIn("40%", message)
        self.assertEqual(fake.set_calls, [40])
        self.assertEqual(controller.original, 80)
        self.assertTrue(controller.modified)
        controller.apply_for_map(config, "sinjar")
        self.assertEqual(fake.set_calls, [40, 90])
        self.assertEqual(fake.get_calls, 1)  # original capturado uma única vez

    def test_mapa_sem_nivel_restaura_original(self):
        fake = FakeDdc(current=80)
        controller = extra.BrightnessController(runner=fake.runner, getter=fake.getter)
        config = {"ddc": {"enabled": True, "levels": {"tell": 40}}}
        controller.apply_for_map(config, "tell")
        self.assertEqual(fake.set_calls, [40])
        message = controller.apply_for_map(config, "buhriz")
        self.assertIn("restaurado para 80", message)
        self.assertEqual(fake.set_calls, [40, 80])
        self.assertFalse(controller.modified)
        # sem modificação pendente, nada a fazer
        self.assertIsNone(controller.apply_for_map(config, "buhriz"))
        self.assertEqual(fake.set_calls, [40, 80])

    def test_nivel_padrao_e_limites(self):
        fake = FakeDdc()
        controller = extra.BrightnessController(runner=fake.runner, getter=fake.getter)
        config = {"ddc": {"enabled": True, "default_level": 150}}
        controller.apply_for_map(config, "tell")
        self.assertEqual(fake.set_calls, [100])

    def test_falha_no_setvcp_nao_marca_modificado(self):
        fake = FakeDdc(fail=True)
        controller = extra.BrightnessController(runner=fake.runner, getter=fake.getter)
        config = {"ddc": {"enabled": True, "levels": {"tell": 40}}}
        self.assertIsNone(controller.apply_for_map(config, "tell"))
        self.assertFalse(controller.modified)
        self.assertIsNone(controller.restore())

    def test_restore_sem_modificacao(self):
        fake = FakeDdc()
        controller = extra.BrightnessController(runner=fake.runner, getter=fake.getter)
        self.assertIsNone(controller.restore())


@unittest.skipUnless(NUMPY_OK, "numpy/Pillow indisponíveis")
class AtlasAnalysisTests(Lote7TestCase):
    def _write_atlas(self, path: Path, corrupt_row: int | None = None) -> Path:
        identity_strip = atlas.strip_image_from_cube(
            {"size": atlas.ATLAS_TILE, "table": atlas.identity_table()}
        )
        image = Image.new("RGB", (atlas.STRIP_WIDTH, core.ATLAS_ROWS * core.ATLAS_TILE))
        for row in range(core.ATLAS_ROWS):
            if corrupt_row == row:
                strip = Image.new("RGB", (atlas.STRIP_WIDTH, atlas.ATLAS_TILE), (10, 10, 10))
            else:
                strip = identity_strip
            image.paste(strip, (0, row * atlas.ATLAS_TILE))
        image.save(path)
        return path

    def test_atlas_identidade_tem_notas_10_com_aviso(self):
        target = self._write_atlas(self.home / "atlas.png")
        report = atlas.analyze_atlas(target)
        self.assertEqual(len(report["rows"]), core.ATLAS_ROWS)
        for row in report["rows"]:
            self.assertEqual(row["score"], 10)
            self.assertTrue(any("identidade" in note for note in row["notes"]))
            self.assertLess(row["mean_dev"], 1.0)

    def test_linha_corrompida_recebe_nota_baixa(self):
        target = self._write_atlas(self.home / "atlas.png", corrupt_row=5)
        report = atlas.analyze_atlas(target)
        broken = report["rows"][5]
        self.assertLessEqual(broken["score"], 5)
        self.assertTrue(broken["flat"])
        self.assertTrue(any("corrupção" in note for note in broken["notes"]))
        # demais linhas continuam íntegras
        self.assertEqual(report["rows"][3]["score"], 10)

    def test_status_doctor_avisa_sobre_corrompida(self):
        target = self._write_atlas(self.home / "atlas.png", corrupt_row=5)
        with mock.patch.object(
            core, "default_texture_path", return_value=target
        ):
            state, detail = extra.atlas_analysis_status()
        self.assertEqual(state, "warn")
        self.assertIn("linha 5", detail)
        self.assertIn("5/10", detail)

    def test_status_sem_atlas(self):
        with mock.patch.object(
            core,
            "default_texture_path",
            return_value=self.home / "inexistente.png",
        ):
            state, detail = extra.atlas_analysis_status()
        self.assertEqual(state, "info")

    def test_itens_novos_no_diagnostico(self):
        titles = {item["title"] for item in extra.diagnostic_report()}
        self.assertIn("Atlas — análise das LUTs", titles)
        self.assertIn("Brilho DDC/CI por mapa", titles)


@unittest.skipIf(
    __import__("importlib").util.find_spec("multilut_daemon") is None,
    "multilut_daemon indisponível",
)
class DaemonBrightnessTests(Lote7TestCase):
    def test_daemon_aplica_brilho_no_mapa(self):
        import multilut_daemon as daemon_mod

        recorded: list[tuple] = []

        class Recorder(extra.BrightnessController):
            def apply_for_map(self, config, token):
                recorded.append((token, dict(config).get("ddc")))
                return f"Brilho aplicado ({token})"

        with mock.patch.object(extra, "BrightnessController", Recorder):
            pilot = daemon_mod.DaemonPilot()
        self.assertIsInstance(pilot.brightness, Recorder)
        core.save_config(
            {
                "auto_map_switch": True,
                "ddc": {"enabled": True, "levels": {"tell": 55}},
            }
        )
        with mock.patch.object(pilot, "resolve_shader", return_value=None):
            pilot.apply_map_token("tell")
        self.assertEqual(recorded, [("tell", {"enabled": True, "levels": {"tell": 55}})])

    def test_watch_restaura_com_jogo_fechado(self):
        import multilut_daemon as daemon_mod

        fake = FakeDdc(current=70)
        pilot = daemon_mod.DaemonPilot()
        pilot.brightness = extra.BrightnessController(
            runner=fake.runner, getter=fake.getter
        )
        pilot.brightness.original = 70
        pilot.brightness.modified = True
        notify = mock.patch.object(pilot, "_notify")
        with notify as notify_mock:
            with mock.patch.object(core, "is_game_running", return_value=False):
                self.assertTrue(pilot._watch_game_for_brightness())
        self.assertFalse(pilot.brightness.modified)
        self.assertEqual(fake.set_calls, [70])
        self.assertTrue(notify_mock.called)
        # jogo aberto: nada acontece
        pilot.brightness.modified = True
        with mock.patch.object(core, "is_game_running", return_value=True):
            pilot._watch_game_for_brightness()
        self.assertTrue(pilot.brightness.modified)


class CliBrightnessTests(Lote7TestCase):
    def setUp(self) -> None:
        super().setUp()
        import multilut_ctl

        self.ctl = multilut_ctl

    def test_enable_set_default_clear_show(self):
        parser = self.ctl.build_parser()
        args = parser.parse_args(["brightness", "enable", "on"])
        self.assertEqual(args.func(args), 0)
        config = core.load_config()
        self.assertTrue(config["ddc"]["enabled"])
        args = parser.parse_args(["brightness", "set", "Tell", "55"])
        self.assertEqual(args.func(args), 0)
        args = parser.parse_args(["brightness", "default", "70"])
        self.assertEqual(args.func(args), 0)
        config = core.load_config()
        self.assertEqual(config["ddc"]["levels"]["tell"], 55)
        self.assertEqual(config["ddc"]["default_level"], 70)
        args = parser.parse_args(["brightness", "set", "tell", "300"])
        args.func(args)
        self.assertEqual(core.load_config()["ddc"]["levels"]["tell"], 100)
        args = parser.parse_args(["brightness", "clear", "TELL"])
        self.assertEqual(args.func(args), 0)
        self.assertNotIn("tell", core.load_config()["ddc"]["levels"])
        args = parser.parse_args(["brightness", "clear", "tell"])
        self.assertEqual(args.func(args), 1)


if __name__ == "__main__":
    unittest.main()
