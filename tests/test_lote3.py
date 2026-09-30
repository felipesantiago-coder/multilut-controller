#!/usr/bin/env python3
"""Fundações do lote 3: piloto automático por mapa e atalho global."""

from pathlib import Path
import tempfile
import unittest
from unittest import mock

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


class HomeSandboxTestCase(unittest.TestCase):
    """Base que redireciona o HOME para um diretório temporário."""

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

    def write_shader(self, profile: int = 14) -> Path:
        target = self.home / ".config/vkBasalt/reshade-shaders/Shaders"
        target.mkdir(parents=True, exist_ok=True)
        path = target / "MultiLUT_Insurgency_Optimized.fx"
        path.write_text(
            SHADER.replace(
                "#define ACTIVE_LUT_PROFILE 14",
                f"#define ACTIVE_LUT_PROFILE {profile}",
            ),
            encoding="utf-8",
        )
        return path


class MapLineTests(unittest.TestCase):
    def test_loading_map_quoted(self):
        self.assertEqual(core.parse_map_token('Loading map "market"'), "market")

    def test_loading_map_quoted_com_prefixo_de_log(self):
        # formato real: servidor TF2/CS e cliente GoldSrc (qconsole.log)
        self.assertEqual(
            core.parse_map_token('L 03/01/2016 - 23:44:28: Loading map "ctf_2fort"'),
            "ctf_2fort",
        )

    def test_host_newgame(self):
        self.assertEqual(
            core.parse_map_token("Host_NewGame on map sinjar_coop"), "sinjar_coop"
        )

    def test_host_newgame_sem_prefixo_log_real_nwi(self):
        # formato real de servidor Insurgency/Day of Infamy (condebug)
        self.assertEqual(
            core.parse_map_token(
                "---- Host_NewGame ----\nHost_NewGame on map breville"
            ),
            "breville",
        )

    def test_mapchange_to(self):
        # formato real: L 04/18/2020 - 04:00:03: -------- Mapchange to breville --------
        self.assertEqual(
            core.parse_map_token(
                "L 04/18/2020 - 04:00:03: -------- Mapchange to sinjar --------"
            ),
            "sinjar",
        )

    def test_loading_map_sem_aspas(self):
        self.assertEqual(
            core.parse_map_token("] Loading map market_coop"), "market_coop"
        )

    def test_host_changelevel(self):
        self.assertEqual(
            core.parse_map_token("Host_Changelevel( buhriz, heights, stuff )"),
            "heights",
        )

    def test_console_map_command(self):
        self.assertEqual(core.parse_map_token("map revolt"), "revolt")
        self.assertIsNone(core.parse_map_token("maps list here"))
        self.assertIsNone(core.parse_map_token("remap of something"))

    def test_banner_do_cliente_map_colon(self):
        # formato real do cliente Insurgency com -condebug: banner de abertura
        # do console.log tem a linha 'Map: <mapa>' (caso do usuário, mapa tell)
        self.assertEqual(core.parse_map_token("Map: tell"), "tell")
        self.assertEqual(core.parse_map_token("Map: sinjar_coop"), "sinjar_coop")
        self.assertEqual(core.parse_map_token("map: market"), "market")

    def test_banner_do_cliente_nao_casa_ruido(self):
        # linhas do mesmo log que mencionam 'map' mas não são o banner
        self.assertIsNone(
            core.parse_map_token(
                "env_cubemap used on world geometry without rebuilding map."
            )
        )
        self.assertIsNone(core.parse_map_token("Server Number: 1"))
        self.assertIsNone(core.parse_map_token("Map: "))

    def test_noise_lines(self):
        self.assertIsNone(core.parse_map_token("SV_Activate: players 8"))
        self.assertIsNone(core.parse_map_token(""))
        self.assertIsNone(core.parse_map_token("Loading resources done"))


class MapMatchTests(unittest.TestCase):
    def test_exact_name(self):
        profile = core.match_map_profile("market")
        self.assertIsNotNone(profile)
        self.assertEqual(profile.id, 17)

    def test_variant_suffix(self):
        self.assertEqual(core.match_map_profile("sinjar_night").id, 8)
        self.assertEqual(core.match_map_profile("market_coop").id, 17)
        self.assertEqual(core.match_map_profile("buhriz-day").id, 1)

    def test_dry_canal_slug(self):
        profile = core.match_map_profile("drycanal_coop")
        self.assertIsNotNone(profile)
        self.assertEqual(profile.name, "Dry Canal")

    def test_case_and_quotes(self):
        self.assertEqual(core.match_map_profile('"Verticality"').id, 10)

    def test_unknown_and_empty(self):
        self.assertIsNone(core.match_map_profile("de_dust2"))
        self.assertIsNone(core.match_map_profile(""))
        self.assertIsNone(core.match_map_profile(None))
        self.assertIsNone(core.match_map_profile("gm_construct"))

    def test_only_map_profiles_match(self):
        profile = core.match_map_profile("buhriz")
        self.assertEqual(profile.category, "Mapa")


class ConsoleTailTests(unittest.TestCase):
    def test_feed_returns_complete_lines(self):
        tail = core.ConsoleTail()
        self.assertEqual(tail.feed(b"first line\nsecond "), ["first line"])
        lines = tail.feed(b"line\nthird\n")
        self.assertEqual(lines, ["second line", "third"])
        self.assertEqual(tail.offset, len(b"first line\nsecond line\nthird\n"))

    def test_utf8_and_crlf(self):
        tail = core.ConsoleTail()
        lines = tail.feed('Loading map "panj"\r\nok\r\n'.encode("utf-8"))
        self.assertEqual(lines, ['Loading map "panj"', "ok"])

    def test_reset_for_truncated_log(self):
        tail = core.ConsoleTail()
        tail.feed(b"old content\n")
        tail.reset()
        self.assertEqual(tail.offset, 0)
        self.assertEqual(tail.feed(b'Loading map "tell"\n'), ['Loading map "tell"'])

    def test_map_tokens(self):
        tail = core.ConsoleTail()
        lines = tail.feed(
            b"junk\n" b'Loading map "market"\n' b"more junk\n" b"Host_NewGame on map market\n"
        )
        self.assertEqual(tail.map_tokens(lines), ["market", "market"])

    def test_log_real_do_cliente_insurgency(self):
        # caso real do usuário (aba Sistema: piloto 'ok' mas nada trocava):
        # o único sinal de mapa no console.log do cliente é o banner 'Map: tell'
        log = (
            b"Insurgency\n"
            b"Map: tell\n"
            b"Players: 1 (0 bots) / 32 humans\n"
            b"Build: 9810\n"
            b"Server Number: 1\n"
            b"\n"
            b"\n"
            b"env_cubemap used on world geometry without rebuilding map."
            b" . ignoring: maps/window/ir_window06_mask\n"
            b"ShaderAPIDX8::CreateD3DTexture: D3DERR_INVALIDCALL\n"
            b"SignalXWriteOpportunity(3)\n"
            b'Attempted to precache unknown particle system "blood_dismember_limb"!\n'
            b"[CWorkshopItem] gm260923bbb [3807102970] installed!\n"
            b"Skipping existing file scripts/theaters/gm260923b_push.theater.\n"
            b"The server is using sv_pure 0.  (Enforcing consistency for select files only)\n"
        )
        tail = core.ConsoleTail()
        tokens = tail.map_tokens(tail.feed(log))
        self.assertEqual(tokens, ["tell"])
        profile = core.match_map_profile(tokens[-1])
        self.assertEqual(profile.id, 22)
        self.assertEqual(profile.name, "Tell")

    def test_empty_feed(self):
        tail = core.ConsoleTail()
        self.assertEqual(tail.feed(b""), [])


class NextProfileTests(unittest.TestCase):
    def test_forward_and_wrap(self):
        self.assertEqual(core.next_profile_id(14), 15)
        self.assertEqual(core.next_profile_id(24), 0)
        self.assertEqual(core.next_profile_id(0, 1), 1)

    def test_backward_and_wrap(self):
        self.assertEqual(core.next_profile_id(14, -1), 13)
        self.assertEqual(core.next_profile_id(0, -1), 24)

    def test_steps(self):
        self.assertEqual(core.next_profile_id(0, 3), 3)
        self.assertEqual(core.next_profile_id(24, 2), 1)

    def test_invalid(self):
        with self.assertRaises(core.MultiLUTError):
            core.next_profile_id(25)
        with self.assertRaises(core.MultiLUTError):
            core.next_profile_id(-1)


class HotkeyApplyTests(HomeSandboxTestCase):
    def test_hotkey_cycle_applies_next_profile(self):
        shader = self.write_shader(profile=14)
        previous = core.set_active_profile(shader, core.next_profile_id(14))
        self.assertEqual(previous, 14)
        self.assertEqual(core.read_active_profile(shader), 15)
        core.append_history(
            {
                "profile_id": 15,
                "profile_name": core.PROFILE_BY_ID[15].name,
                "origin": "hotkey",
            }
        )
        entries = core.read_history(limit=5)
        self.assertEqual(entries[0]["origin"], "hotkey")


class ConfigToggleTests(HomeSandboxTestCase):
    def test_auto_map_switch_defaults_off(self):
        self.assertFalse(bool(core.load_config().get("auto_map_switch")))

    def test_global_shortcut_defaults_off(self):
        self.assertFalse(bool(core.load_config().get("global_shortcut")))


if __name__ == "__main__":
    unittest.main()
