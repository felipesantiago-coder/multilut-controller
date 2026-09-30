#!/usr/bin/env python3
"""Lote final: atlas v1.8, status do vkBasalt.conf e hash de arquivos."""

from pathlib import Path
import tempfile
import unittest

import multilut_core as core
import multilut_extra as extra


class AtlasTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.bundle_texture = Path(__file__).resolve().parent.parent / (
            "bundle/Textures/MultiLut_Insurgency_Optimized.png"
        )

    def tearDown(self):
        self.temp.cleanup()

    def test_lut_row_follows_profile_id_until_16(self):
        for profile_id in range(0, 17):
            self.assertEqual(core.lut_row_for_profile(profile_id), profile_id)

    def test_lut_row_mapping_from_shader(self):
        self.assertEqual(core.lut_row_for_profile(17), 3)
        self.assertEqual(core.lut_row_for_profile(18), 12)
        self.assertEqual(core.lut_row_for_profile(19), 13)
        self.assertEqual(core.lut_row_for_profile(20), 5)
        self.assertEqual(core.lut_row_for_profile(21), 2)
        self.assertEqual(core.lut_row_for_profile(22), 1)
        self.assertEqual(core.lut_row_for_profile(23), 3)
        self.assertEqual(core.lut_row_for_profile(24), 13)

    def test_atlas_size_matches_shader_constants(self):
        self.assertEqual(core.ATLAS_SIZE, (1024, 544))

    def test_validate_texture_accepts_bundle_atlas(self):
        if not self.bundle_texture.is_file():
            self.skipTest("atlas do bundle indisponível")
        valid, message = core.validate_texture(self.bundle_texture)
        self.assertTrue(valid, message)
        self.assertIn("v1.8", message)

    def test_validate_texture_missing_file(self):
        valid, message = core.validate_texture(self.root / "ausente.png")
        self.assertFalse(valid)
        self.assertIn("não encontrado", message)

    def test_validate_texture_rejects_non_png(self):
        fake = self.root / "fake.png"
        fake.write_bytes(b"not a png" * 10)
        valid, message = core.validate_texture(fake)
        self.assertFalse(valid)
        self.assertIn("não é um PNG", message)

    def test_validate_texture_rejects_wrong_dimensions(self):
        # Cabeçalho PNG válido (IHDR) com dimensões erradas: 64x64.
        signature = b"\x89PNG\r\n\x1a\n"
        fake = self.root / "wrong.png"
        fake.write_bytes(
            signature
            + (13).to_bytes(4, "big")
            + b"IHDR"
            + (64).to_bytes(4, "big")
            + (64).to_bytes(4, "big")
            + bytes([8, 6, 0, 0, 0])
            + b"\x00\x00\x00\x00"
        )
        valid, message = core.validate_texture(fake)
        self.assertFalse(valid)
        self.assertIn("geometria inesperada", message)

    def test_validate_texture_rejects_truncated_header(self):
        fake = self.root / "truncado.png"
        fake.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 5)
        valid, _message = core.validate_texture(fake)
        self.assertFalse(valid)


class FileHashTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def test_equal_content_equal_hash(self):
        a = self.root / "a.txt"
        b = self.root / "b.txt"
        a.write_text("conteudo", encoding="utf-8")
        b.write_text("conteudo", encoding="utf-8")
        self.assertEqual(core.file_hash(a), core.file_hash(b))

    def test_different_content_different_hash(self):
        a = self.root / "a.txt"
        c = self.root / "c.txt"
        a.write_text("conteudo", encoding="utf-8")
        c.write_text("outro", encoding="utf-8")
        self.assertNotEqual(core.file_hash(a), core.file_hash(c))

    def test_missing_file_returns_none(self):
        self.assertIsNone(core.file_hash(self.root / "ausente.txt"))


class VkBasaltConfigStatusTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def test_missing_config_is_info(self):
        state, detail = extra.vkbasalt_config_status(self.root / "vkBasalt.conf")
        self.assertEqual(state, "info")

    def test_effects_with_multilut_is_ok(self):
        conf = self.root / "vkBasalt.conf"
        conf.write_text(
            "effects = aurburn.shader,MultiLUT_Insurgency_Optimized\n"
            "toggleKey = F3\n",
            encoding="utf-8",
        )
        state, detail = extra.vkbasalt_config_status(conf)
        self.assertEqual(state, "ok")
        self.assertIn("MultiLUT", detail)

    def test_effects_without_multilut_warns(self):
        conf = self.root / "vkBasalt.conf"
        conf.write_text("effects = clarity.fx\n", encoding="utf-8")
        state, detail = extra.vkbasalt_config_status(conf)
        self.assertEqual(state, "warn")
        self.assertIn("clarity.fx", detail)

    def test_empty_effects_warns(self):
        conf = self.root / "vkBasalt.conf"
        conf.write_text("# sem effects\n", encoding="utf-8")
        state, _detail = extra.vkbasalt_config_status(conf)
        self.assertEqual(state, "warn")


if __name__ == "__main__":
    unittest.main()
