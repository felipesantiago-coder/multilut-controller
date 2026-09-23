#!/usr/bin/env python3

from pathlib import Path
import tempfile
import unittest

import multilut_core as core


SHADER = """#ifndef ACTIVE_LUT_PROFILE
    #define ACTIVE_LUT_PROFILE 14
#endif
#define fLUT_TextureName \"MultiLut_Insurgency_Optimized.png\"
uniform float fLUT_DeepShadowRecovery = 0.5;
uniform float fLUT_SceneBrightness = 0.0;
uniform float fLUT_ColorSeparation = 0.1;
technique MultiLUT { pass Test { } }
"""


class CoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "MultiLUT_Insurgency_Optimized.fx"
        self.path.write_text(SHADER, encoding="utf-8")

    def tearDown(self):
        self.temp.cleanup()

    def test_reads_profile(self):
        self.assertEqual(core.read_active_profile(self.path), 14)

    def test_changes_only_active_profile_and_creates_backup(self):
        previous = core.set_active_profile(self.path, 9)
        self.assertEqual(previous, 14)
        self.assertEqual(core.read_active_profile(self.path), 9)
        self.assertEqual(core.read_active_profile(core.backup_path(self.path)), 14)

    def test_restore(self):
        core.set_active_profile(self.path, 7)
        self.assertEqual(core.restore_backup(self.path), 14)

    def test_rejects_invalid_profile(self):
        with self.assertRaises(core.MultiLUTError):
            core.set_active_profile(self.path, 25)

    def test_accepts_new_map_profile(self):
        previous = core.set_active_profile(self.path, 24)
        self.assertEqual(previous, 14)
        self.assertEqual(core.read_active_profile(self.path), 24)

    def test_validation(self):
        valid, _ = core.validate_shader(self.path)
        self.assertTrue(valid)

    def test_rejects_ambiguous_shader(self):
        self.path.write_text(SHADER + "\n#define ACTIVE_LUT_PROFILE 3\n", encoding="utf-8")
        with self.assertRaises(core.MultiLUTError):
            core.set_active_profile(self.path, 2)

    def test_no_backup_when_profile_is_unchanged(self):
        previous = core.set_active_profile(self.path, 14)
        self.assertEqual(previous, 14)
        self.assertFalse(core.backup_path(self.path).exists())


if __name__ == "__main__":
    unittest.main()
