#!/usr/bin/env python3
"""Refinamentos finais: migração do histórico (XDG_STATE_HOME) e CLI (doctor/next/history)."""

from pathlib import Path
import contextlib
import io
import json
import tempfile
import unittest
from unittest import mock

import multilut_core as core
import multilut_ctl as ctl


SHADER = """#ifndef ACTIVE_LUT_PROFILE
    #define ACTIVE_LUT_PROFILE 14
#endif
#define fLUT_TextureName \"MultiLut_Insurgency_Optimized.png\"
uniform float fLUT_DeepShadowRecovery = 0.5;
uniform float fLUT_SceneBrightness = 0.0;
uniform float fLUT_ColorSeparation = 0.1;
technique MultiLUT { pass Test { } }
"""


def _write_shader(directory: Path, profile: int = 14) -> Path:
    text = SHADER.replace(
        "#define ACTIVE_LUT_PROFILE 14", f"#define ACTIVE_LUT_PROFILE {profile}"
    )
    path = directory / "MultiLUT_Insurgency_Optimized.fx"
    path.write_text(text, encoding="utf-8")
    return path


class HomeSandboxTestCase(unittest.TestCase):
    """Base que redireciona o HOME para um diretório temporário."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.home = Path(self._tmp.name)
        home_patcher = mock.patch("pathlib.Path.home", new=lambda: self.home)
        home_patcher.start()
        self.addCleanup(home_patcher.stop)


class StateDirTests(HomeSandboxTestCase):
    def test_default_state_dir(self):
        self.assertEqual(
            core.app_state_dir(),
            self.home / ".local/state/multilut-controller",
        )

    def test_xdg_state_home_env_is_honored(self):
        with mock.patch.dict(
            "os.environ", {"XDG_STATE_HOME": str(self.home / "estado")}
        ):
            self.assertEqual(
                core.history_path(),
                self.home / "estado/multilut-controller/history.jsonl",
            )

    def test_empty_env_falls_back_to_default(self):
        with mock.patch.dict("os.environ", {"XDG_STATE_HOME": "   "}):
            self.assertEqual(
                core.history_path(),
                self.home / ".local/state/multilut-controller/history.jsonl",
            )


class HistoryMigrationTests(HomeSandboxTestCase):
    def test_append_moves_legacy_file(self):
        legacy = self.home / ".config/multilut-controller/history.jsonl"
        legacy.parent.mkdir(parents=True, exist_ok=True)
        legacy.write_text(
            json.dumps({"profile_id": 3, "profile_name": "Antigo", "origin": "cli"})
            + "\n",
            encoding="utf-8",
        )
        core.append_history({"profile_id": 4, "origin": "manual"})
        target = self.home / ".local/state/multilut-controller/history.jsonl"
        self.assertTrue(target.is_file())
        self.assertFalse(legacy.exists())  # movido, não copiado
        entries = core.read_history(limit=10)
        self.assertEqual([entry["profile_id"] for entry in entries], [4, 3])

    def test_read_falls_back_to_legacy_when_move_fails(self):
        legacy = self.home / ".config/multilut-controller/history.jsonl"
        legacy.parent.mkdir(parents=True, exist_ok=True)
        legacy.write_text(
            json.dumps({"profile_id": 7, "profile_name": "Legado", "origin": "cli"})
            + "\n",
            encoding="utf-8",
        )
        with mock.patch("pathlib.Path.replace", side_effect=OSError("ro")):
            entries = core.read_history(limit=10)
        self.assertEqual(entries[0]["profile_id"], 7)
        self.assertTrue(legacy.exists())  # permanece legível no lugar antigo

    def test_migration_skips_when_target_exists(self):
        target = self.home / ".local/state/multilut-controller/history.jsonl"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            json.dumps({"profile_id": 9, "origin": "manual"}) + "\n",
            encoding="utf-8",
        )
        legacy = self.home / ".config/multilut-controller/history.jsonl"
        legacy.parent.mkdir(parents=True, exist_ok=True)
        legacy.write_text(
            json.dumps({"profile_id": 3, "origin": "cli"}) + "\n",
            encoding="utf-8",
        )
        core.append_history({"profile_id": 10, "origin": "manual"})
        entries = core.read_history(limit=10)
        # o legado é ignorado quando o arquivo novo já existe
        self.assertEqual([entry["profile_id"] for entry in entries], [10, 9])
        self.assertTrue(legacy.exists())

    def test_clear_removes_state_file_and_migrates_first(self):
        legacy = self.home / ".config/multilut-controller/history.jsonl"
        legacy.parent.mkdir(parents=True, exist_ok=True)
        legacy.write_text(
            json.dumps({"profile_id": 2, "origin": "cli"}) + "\n",
            encoding="utf-8",
        )
        core.clear_history()
        self.assertFalse(legacy.exists())
        self.assertFalse(
            (self.home / ".local/state/multilut-controller/history.jsonl").exists()
        )


class CliNextTests(HomeSandboxTestCase):
    def test_next_applies_next_profile_and_records_history(self):
        shader = _write_shader(Path(self.home), profile=14)
        self.assertEqual(ctl.main(["next", "--shader", str(shader)]), 0)
        self.assertEqual(core.read_active_profile(shader), 15)
        entries = core.read_history()
        self.assertEqual(entries[0]["origin"], "cli")
        self.assertEqual(entries[0]["profile_id"], 15)
        self.assertEqual(entries[0]["previous"], 14)

    def test_next_wraps_around_from_last_to_first(self):
        shader = _write_shader(Path(self.home), profile=24)
        self.assertEqual(ctl.main(["next", "--shader", str(shader)]), 0)
        self.assertEqual(core.read_active_profile(shader), 0)

    def test_next_anterior_goes_back(self):
        shader = _write_shader(Path(self.home), profile=0)
        self.assertEqual(
            ctl.main(["next", "--anterior", "--shader", str(shader)]), 0
        )
        self.assertEqual(core.read_active_profile(shader), 24)

    def test_next_without_history_flag(self):
        shader = _write_shader(Path(self.home), profile=5)
        self.assertEqual(
            ctl.main(["next", "--no-history", "--shader", str(shader)]), 0
        )
        self.assertEqual(core.read_active_profile(shader), 6)
        self.assertEqual(core.read_history(), [])


class CliHistoryTests(HomeSandboxTestCase):
    def test_history_empty_message(self):
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            self.assertEqual(ctl.main(["history"]), 0)
        self.assertIn("Histórico vazio", buffer.getvalue())

    def test_history_lists_recent_first_with_origin(self):
        core.append_history({"profile_id": 1, "profile_name": "Buhriz", "origin": "cli"})
        core.append_history(
            {
                "profile_id": 14,
                "profile_name": "Competitivo neutro",
                "origin": "Piloto automatico",
            }
        )
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            self.assertEqual(ctl.main(["history", "--limit", "5"]), 0)
        out = buffer.getvalue()
        self.assertIn("14 — Competitivo neutro", out)
        self.assertIn("Piloto automatico", out)
        # mais recente primeiro: o índice de 14 vem antes do de 01
        self.assertLess(out.index("14 —"), out.index("01 —"))

    def test_history_handles_non_integer_profile_id(self):
        core.append_history({"profile_id": "x", "profile_name": "Corrompido"})
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            self.assertEqual(ctl.main(["history"]), 0)
        self.assertIn("Corrompido", buffer.getvalue())


class CliDoctorTests(HomeSandboxTestCase):
    def _install_shader(self, profile: int = 14) -> Path:
        """Shader no caminho padrão (~/.config/vkBasalt) para o diagnóstico."""
        target = self.home / ".config/vkBasalt/reshade-shaders/Shaders"
        target.mkdir(parents=True, exist_ok=True)
        return _write_shader(target, profile=profile)

    def test_doctor_json_reports_structured_items(self):
        self._install_shader()
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            code = ctl.main(["doctor", "--json"])
        data = json.loads(buffer.getvalue())
        self.assertIsInstance(data, list)
        self.assertTrue(data)
        titles = {item["title"] for item in data}
        self.assertIn("Shader MultiLUT", titles)
        for item in data:
            self.assertIn(item["state"], {"ok", "warn", "fail", "info"})
            self.assertTrue(str(item["detail"]).strip())
        self.assertIn(code, {0, 1})
        # com o shader instalado no caminho padrão, o item dele é "ok"
        shader_item = next(item for item in data if item["title"] == "Shader MultiLUT")
        self.assertEqual(shader_item["state"], "ok")

    def test_doctor_text_has_labels_and_conclusion(self):
        self._install_shader()
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            ctl.main(["doctor"])
        out = buffer.getvalue()
        self.assertIn("[ok   ]", out)
        self.assertIn("Diagnóstico concluído", out)


if __name__ == "__main__":
    unittest.main()
