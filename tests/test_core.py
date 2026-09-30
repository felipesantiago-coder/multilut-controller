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

    def test_profiles_alphabetical_preserves_ids(self):
        ordered = core.profiles_alphabetical()
        self.assertEqual(
            sorted(profile.id for profile in ordered),
            sorted(profile.id for profile in core.PROFILES),
        )

    def test_profiles_alphabetical_order(self):
        ordered = core.profiles_alphabetical()
        keys = [core._profile_sort_key(profile) for profile in ordered]
        self.assertEqual(keys, sorted(keys))
        self.assertEqual(ordered[0].name, "Alto contraste competitivo")
        self.assertEqual(ordered[-1].name, "Verticality")


class SectionTests(unittest.TestCase):
    def test_two_sections_in_fixed_order(self):
        sections = core.profiles_by_section()
        self.assertEqual(
            [title for title, _profiles in sections],
            ["Efeitos de mapa", "Efeitos utilitários"],
        )

    def test_sections_cover_every_profile_exactly_once(self):
        ids = [
            profile.id
            for _title, profiles in core.profiles_by_section()
            for profile in profiles
        ]
        self.assertEqual(sorted(ids), sorted(profile.id for profile in core.PROFILES))

    def test_each_section_is_alphabetical(self):
        for _title, profiles in core.profiles_by_section():
            keys = [core._profile_sort_key(profile) for profile in profiles]
            self.assertEqual(keys, sorted(keys))

    def test_map_section_only_has_map_category(self):
        mapas, utilitarios = core.profiles_by_section()
        self.assertTrue(all(profile.category == "Mapa" for profile in mapas[1]))
        self.assertTrue(all(profile.category != "Mapa" for profile in utilitarios[1]))


class MapImageTests(unittest.TestCase):
    """Fotos oficiais dos mapas usadas nos cartões da interface."""

    ASSETS_MAPS = Path(__file__).resolve().parent.parent / "assets" / "maps"

    def test_slug_strips_spaces_and_accents(self):
        dry_canal = next(p for p in core.PROFILES if p.name == "Dry Canal")
        self.assertEqual(core.map_image_slug(dry_canal), "drycanal")

    def test_non_map_profiles_have_no_image(self):
        for profile in core.PROFILES:
            if profile.category != "Mapa":
                self.assertIsNone(core.map_image_slug(profile))

    def test_map_profiles_have_valid_slug(self):
        for profile in core.PROFILES:
            slug = core.map_image_slug(profile)
            if profile.category == "Mapa":
                self.assertTrue(slug)
                self.assertEqual(slug, slug.lower())
                self.assertTrue(slug.isalnum(), slug)
            else:
                self.assertIsNone(slug)

    def test_every_map_profile_has_official_image(self):
        missing = [
            profile.name
            for profile in core.PROFILES
            if profile.category == "Mapa"
            and not (self.ASSETS_MAPS / f"{core.map_image_slug(profile)}.jpg").is_file()
        ]
        self.assertEqual(missing, [], "fotos oficiais ausentes em assets/maps")

    def test_map_images_are_readable_jpeg(self):
        for path in sorted(self.ASSETS_MAPS.glob("*.jpg")):
            with self.subTest(arquivo=path.name):
                self.assertGreater(path.stat().st_size, 10_000, path.name)
                header = path.read_bytes()[:2]
                self.assertEqual(header, b"\xff\xd8", path.name)


if __name__ == "__main__":
    unittest.main()
