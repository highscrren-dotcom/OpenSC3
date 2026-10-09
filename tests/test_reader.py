"""Набор чтений → Sc3State на поддельном SC3. Тела блоков и узлов — синтетические (решение 5)."""
import struct
import unittest

from opensc3 import protocol as P
from opensc3.device import Sc3
from opensc3.model import KEYS, VOICES, Link
from opensc3.reader import ELECTRIC_KEYS, PANEL_ORDER, SDK_CIRCLE, VOICE_PITCH, line_in_fader, read_state
from tests.fake import FakeTransport

Sc3.DELAY = 0


def adc1(mute=0, vol=2112):
    return b"\xff" + struct.pack("<10H", 3, mute, vol, vol, 7, 0, 0, 0, 0, 1)


QUERY = b"\xff" + struct.pack("<HHBHH", 100, 160, 0, 320, 320)  # загрузка 160/320 = 0,5
QUIET = {0xB6: [1, 0, 132 * 16], 0x85: [0, -40], 0x86: [0, ord("C"), ord("u"), 0]}


def fake(nodes=None, blocks=None, **kw):
    return FakeTransport(nodes={**QUIET, **(nodes or {})}, blocks={0x02: QUERY, 0x07: adc1(), **(blocks or {})}, **kw)


class Reader(unittest.TestCase):
    def test_quiet_panel(self):
        t = fake(blocks={0x07: adc1(mute=1, vol=2112)})
        st = read_state(Sc3(t), now=1234.5)
        self.assertEqual((st.link, st.firmware, st.read_at), (Link.CONNECTED, "V22", 1234.5))
        self.assertAlmostEqual(st.dsp_load, 0.5)
        self.assertAlmostEqual(st.mic.fader, 2112 / 4092)
        self.assertIs(st.mic.muted, False)  # громкость > 0 — не заглушено; флаг mute в 0x07 не значит ничего
        self.assertFalse(st.mic.muted_guess)
        self.assertIsNone(st.mic.trim_db)
        self.assertAlmostEqual(st.line_in.fader, 16 / 31)
        self.assertIs(st.line_in.muted, False)  # MUTE LINE IN тоже обнуляет громкость, а она > 0
        self.assertIsNone(st.mic_monitor)
        self.assertTrue(st.headphone.locked and st.line_out.locked)
        self.assertEqual((st.voice, st.electric_key), ("", ""))

    def test_minimum_reads_only(self):
        t = fake()
        read_state(Sc3(t), now=0)
        self.assertEqual([f[2] for f in t.sent], [0x00, 0x02, 0x07, 0xB6, 0x85, 0x86])
        self.assertTrue(all(f[3] == 0 for f in t.sent), "только чтения (LEN = 0)")

    def test_muted_zero_is_just_zero(self):
        """MUTE и «ползунок внизу» в одном чтении одинаковы: громкость 0, mute неизвестен."""
        st = read_state(Sc3(fake(blocks={0x07: adc1(vol=0)}, nodes={0xB6: [1, 0, 0]})), now=0)
        self.assertEqual((st.mic.fader, st.mic.muted, st.line_in.fader, st.line_in.muted), (0.0, None, 0.0, None))
        st = read_state(Sc3(fake(nodes={0xB6: [1, 0, 50]})), now=0)  # меньше полуступени: ступень 0, но не MUTE
        self.assertEqual((st.line_in.fader, st.line_in.muted), (0.0, False))

    def test_voices_by_pitch(self):
        self.assertEqual(set(VOICE_PITCH), set(VOICES))
        self.assertEqual(len(set(VOICE_PITCH.values())), len(VOICES))  # сдвиги различимы
        cases = {-55: "male", 45: "female", -100: "robot", -120: "monster", 100: "baby", -40: "elder"}
        for pitch, name in cases.items():
            st = read_state(Sc3(fake({0x85: [1, pitch]})), now=0)
            self.assertEqual((st.link, st.voice), (Link.CONNECTED, name), pitch)
        self.assertIsNone(read_state(Sc3(fake({0x85: [1, 7]})), now=0).voice)   # не из пресетов
        self.assertEqual(read_state(Sc3(fake({0x85: [0, 100]})), now=0).voice, "")  # выкл., высота от Baby

    def test_electric_keys_as_on_panel(self):
        self.assertEqual(PANEL_ORDER, KEYS)
        self.assertEqual(len(SDK_CIRCLE), 12)
        # a, A, b, D, e — проверено на устройстве 08.10; остальное — та же позиция по строкам панели
        for letter, key in (("a", "A"), ("A", "Bb"), ("b", "B"), ("B", "C"), ("C", "Db"), ("d", "D"), ("D", "Ab"),
                            ("e", "G"), ("E", "Gb"), ("F", "F"), ("g", "E"), ("G", "Eb")):
            self.assertEqual(ELECTRIC_KEYS[letter], key)
            st = read_state(Sc3(fake({0x86: [1, ord(letter), ord("n"), 1]})), now=0)
            self.assertEqual(st.electric_key, key, letter)
        st = read_state(Sc3(fake({0x86: [1, ord("X"), ord("n"), 1]})), now=0)
        self.assertIsNone(st.electric_key)  # хроматический — не точка на корпусе
        self.assertEqual(read_state(Sc3(fake({0x86: [0, ord("a"), ord("n"), 1]})), now=0).electric_key, "")

    def test_faders_clamped(self):
        st = read_state(Sc3(fake(blocks={0x07: adc1(vol=0x3FFF)}, nodes={0xB6: [1, 0, 0]})), now=0)
        self.assertEqual((st.mic.fader, st.line_in.fader), (1.0, 0.0))
        self.assertEqual(line_in_fader(132 * 31), 1.0)
        self.assertEqual(line_in_fader(9999), 1.0)
        self.assertEqual(line_in_fader(-5), 0.0)

    def test_foreign_build(self):
        t = fake(version=bytes.fromhex("31000101012205"))
        st = read_state(Sc3(t), now=0)
        self.assertEqual((st.link, st.firmware, st.read_at), (Link.FOREIGN, None, None))
        self.assertEqual([f[2] for f in t.sent], [0x00])  # после чужой сборки — ни одного чтения

    def test_foreign_descriptor(self):
        bad = bytes.fromhex("0600ff0aaa55a1018501750896000109018102960001090291 02c0".replace(" ", ""))
        t = fake(desc=bad)
        self.assertEqual(read_state(Sc3(t), now=0).link, Link.FOREIGN)
        self.assertEqual(t.sent, [])

    def test_no_version_reply_is_error_not_foreign(self):
        self.assertEqual(read_state(Sc3(fake(silent={0x00})), now=0).link, Link.ERROR)

    def test_failed_read_is_error_without_values(self):
        for kw in ({"silent": {0x86}}, {"broken": {0x07}}, {"silent": {0x02}}):
            st = read_state(Sc3(fake(**kw)), now=5)
            self.assertEqual((st.link, st.read_at, st.mic.fader, st.voice), (Link.ERROR, None, None, None), kw)

    def test_stops_at_first_failure(self):
        t = fake(silent={0x07})
        self.assertEqual(read_state(Sc3(t), now=0).link, Link.ERROR)
        self.assertEqual({f[2] for f in t.sent}, {0x00, 0x02, 0x07})  # дальше 0x07 не пошли

    def test_short_bodies_are_error(self):
        st = read_state(Sc3(fake(blocks={0x02: b"\xff\x01"})), now=0)
        self.assertEqual(st.link, Link.ERROR)
        st = read_state(Sc3(fake(nodes={0xB6: [1]})), now=0)
        self.assertEqual(st.link, Link.ERROR)
        st = read_state(Sc3(fake(nodes={0x85: [1]})), now=0)  # голос вкл., а сдвига нет
        self.assertEqual(st.link, Link.ERROR)

    def test_frames_pass_whitelist(self):
        t = fake()
        read_state(Sc3(t), now=0)
        for f in t.sent:
            P.check_frame(f)


if __name__ == "__main__":
    unittest.main()
