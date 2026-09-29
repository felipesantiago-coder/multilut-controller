#!/usr/bin/env python3

from pathlib import Path
import tempfile
import unittest

import multilut_aim as aim


def sample_session(**overrides) -> dict:
    session = {
        "timestamp": "2026-01-01T12:00:00+00:00",
        "mode": "flick",
        "targets": 20,
        "misses": 2,
        "avg_reaction_ms": 420.0,
        "best_reaction_ms": 280.0,
        "targets_per_minute": 38.0,
        "duration_s": 31.6,
    }
    session.update(overrides)
    return session


class CrosshairConfigTests(unittest.TestCase):
    def test_defaults_when_empty(self):
        config = aim.normalize_crosshair_config(None)
        self.assertEqual(config, aim.CROSSHAIR_DEFAULTS)

    def test_clamps_out_of_range_values(self):
        config = aim.normalize_crosshair_config(
            {"length": 900, "thickness": 0, "gap": -5, "opacity": 7, "dot_size": 99}
        )
        self.assertEqual(config["length"], 40)
        self.assertEqual(config["thickness"], 1)
        self.assertEqual(config["gap"], 0)
        self.assertEqual(config["opacity"], 1.0)
        self.assertEqual(config["dot_size"], 6)

    def test_rejects_bad_color_and_bools(self):
        config = aim.normalize_crosshair_config({"color": "green", "dot": "sim"})
        self.assertEqual(config["color"], aim.CROSSHAIR_DEFAULTS["color"])
        self.assertTrue(config["dot"])

    def test_accepts_valid_hex_color(self):
        config = aim.normalize_crosshair_config({"color": "#FF00AA"})
        self.assertEqual(config["color"], "#ff00aa")

    def test_reads_from_app_config(self):
        self.assertEqual(
            aim.crosshair_config_from_config({"crosshair": {"gap": 12}})["gap"], 12
        )
        self.assertEqual(aim.crosshair_config_from_config({}), aim.CROSSHAIR_DEFAULTS)

    def test_hex_to_rgb(self):
        self.assertAlmostEqual(aim.hex_to_rgb("#FFFFFF")[0], 1.0)
        self.assertEqual(aim.hex_to_rgb("sem cor"), (0.0, 1.0, 0.4))


class SessionStorageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "training_history.json"

    def tearDown(self):
        self.temp.cleanup()

    def test_validation_rejects_bad_sessions(self):
        self.assertTrue(aim.validate_training_session("não sou dicionário"))
        self.assertTrue(aim.validate_training_session(sample_session(mode="agressivo")))
        self.assertTrue(aim.validate_training_session(sample_session(targets=0)))
        self.assertTrue(aim.validate_training_session(sample_session(avg_reaction_ms=-1)))
        self.assertEqual(aim.validate_training_session(sample_session()), [])

    def test_append_and_load_roundtrip(self):
        stored = aim.append_training_session(sample_session(), self.path)
        sessions = aim.load_training_sessions(self.path)
        self.assertEqual(len(sessions), 1)
        self.assertEqual(sessions[0]["mode"], "flick")
        self.assertEqual(sessions[0]["avg_reaction_ms"], 420.0)
        self.assertEqual(stored["targets"], 20)

    def test_append_fills_missing_timestamp(self):
        session = sample_session(timestamp=None)
        del session["timestamp"]
        stored = aim.append_training_session(session, self.path)
        self.assertIsInstance(stored["timestamp"], str)
        self.assertIn("T", stored["timestamp"])

    def test_append_rejects_invalid_session(self):
        with self.assertRaises(aim.MultiLUTError):
            aim.append_training_session({"mode": "flick"}, self.path)
        self.assertEqual(aim.load_training_sessions(self.path), [])

    def test_history_is_capped(self):
        for index in range(aim.MAX_SESSIONS + 50):
            aim.append_training_session(sample_session(avg_reaction_ms=index), self.path)
        sessions = aim.load_training_sessions(self.path)
        self.assertEqual(len(sessions), aim.MAX_SESSIONS)
        self.assertEqual(sessions[-1]["avg_reaction_ms"], aim.MAX_SESSIONS + 49)

    def test_filter_by_mode(self):
        aim.append_training_session(sample_session(), self.path)
        self.assertEqual(len(aim.load_training_sessions(self.path, mode="flick")), 1)
        self.assertEqual(len(aim.load_training_sessions(self.path, mode="tracking")), 0)

    def test_clear_history(self):
        aim.append_training_session(sample_session(), self.path)
        aim.clear_training_sessions(self.path)
        self.assertEqual(aim.load_training_sessions(self.path), [])

    def test_load_corrupted_file_returns_empty(self):
        self.path.write_text("{ quebrado", encoding="utf-8")
        self.assertEqual(aim.load_training_sessions(self.path), [])

    def test_accuracy_helper(self):
        self.assertAlmostEqual(aim.session_accuracy(sample_session(targets=18, misses=2)), 90.0)
        self.assertEqual(aim.session_accuracy(sample_session(targets=0, misses=0)), 0.0)


class StatisticsTests(unittest.TestCase):
    def test_summary_weighted_means(self):
        sessions = [
            sample_session(targets=10, misses=0, avg_reaction_ms=300.0, targets_per_minute=40.0),
            sample_session(targets=30, misses=10, avg_reaction_ms=500.0, targets_per_minute=20.0),
        ]
        summary = aim.summarize_sessions(sessions)
        self.assertEqual(summary["rounds"], 2)
        self.assertEqual(summary["total_targets"], 40)
        self.assertEqual(summary["total_misses"], 10)
        self.assertAlmostEqual(summary["avg_reaction_ms"], 450.0)  # 30*500 + 10*300 / 40
        self.assertAlmostEqual(summary["best_reaction_ms"], 280.0)
        self.assertAlmostEqual(summary["avg_accuracy"], 81.25)  # (100*10 + 75*30) / 40
        self.assertAlmostEqual(summary["avg_targets_per_minute"], 25.0)

    def test_summary_empty(self):
        summary = aim.summarize_sessions([])
        self.assertEqual(summary["rounds"], 0)
        self.assertEqual(summary["avg_reaction_ms"], 0.0)
        self.assertEqual(summary["best_reaction_ms"], 0.0)

    def test_moving_average(self):
        values = [10.0, 20.0, 30.0, 40.0]
        self.assertEqual(aim.moving_average(values, 2), [10.0, 15.0, 25.0, 35.0])
        self.assertEqual(aim.moving_average(values, 10), [10.0, 15.0, 20.0, 25.0])
        with self.assertRaises(ValueError):
            aim.moving_average(values, 0)
        self.assertEqual(aim.moving_average([], 3), [])


if __name__ == "__main__":
    unittest.main()
