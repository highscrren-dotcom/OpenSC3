"""Представление окна и трея (opensc3/app/view.py): без Qt, без устройства."""
import pathlib
import re
import unittest

from opensc3.app import view
from opensc3.model import AppState, AudioState, Channel, Link, Live, Sc3State

ROOT = pathlib.Path(__file__).resolve().parent.parent
DEMO = ROOT / "design" / "panel" / "scenes" / "DemoState.qml"
# их считает бэкенд, а не qml_state: опрос, уровни, предохранитель записи и ждущая запись ручки MIC
BACKEND_ONLY = {"busy", "polling", "levelIn", "levelOut", "writeEnabled", "trimMicPending"}


def demo_names() -> set[str]:
    text = DEMO.read_text()
    return set(re.findall(r"^\s*(?:readonly\s+)?property\s+\w+\s+(\w+)", text, re.MULTILINE))


def reader_like(**kw) -> Sc3State:
    """То, что сейчас умеет reader.read_state: ползунки Mic и Line In, Mute микрофона, ELECTRIC, голос выкл."""
    base = {"link": Link.CONNECTED, "firmware": "V22", "read_at": 0.0, "mic": Channel(fader=0.8, muted=False),
            "line_in": Channel(fader=0.52), "voice": "", "electric_key": "C"}
    base.update(kw)
    return Sc3State(**base)


class Shape(unittest.TestCase):
    def test_same_shape_as_demo_state(self):
        """Макеты и окно рисуют одни компоненты: у DemoState.qml и бэкенда одинаковые свойства."""
        props = set(view.qml_state(AppState(), 0.0)) | BACKEND_ONLY
        self.assertEqual(props, demo_names())


class Unknown(unittest.TestCase):
    def test_nothing_known_by_default(self):
        p = view.qml_state(AppState(), 0.0)
        self.assertEqual(p["link"], "disconnected")
        self.assertFalse(p["connected"])
        for name in ("faderMic", "faderLineIn", "faderHeadphone", "faderLineOut", "muteMic", "voice",
                     "electricKey", "trimMic", "trimLineIn", "micMonitor", "phantom"):
            self.assertTrue(p["unknown"].get(name), name)
        self.assertEqual(p["dsp"], {})          # ни одного выдуманного числа для ящиков
        self.assertEqual(p["profiles"], [])

    def test_reader_state(self):
        p = view.qml_state(AppState(sc3=reader_like(), live=Live.OFF), 0.0)
        self.assertTrue(p["connected"])
        self.assertAlmostEqual(p["faderMic"], 0.8)
        self.assertEqual(p["electricKey"], "C")
        self.assertEqual(p["voice"], "")
        for name in ("faderMic", "faderLineIn", "muteMic", "voice", "electricKey"):
            self.assertNotIn(name, p["unknown"])
        for name in ("faderHeadphone", "faderLineOut", "muteLineIn", "micMonitor", "trimMic"):
            self.assertIn(name, p["unknown"])

    def test_voice_as_printed(self):
        p = view.qml_state(AppState(sc3=reader_like(voice="monster")), 0.0)
        self.assertEqual(p["voice"], "Monster")
        p = view.qml_state(AppState(sc3=reader_like(voice=None)), 0.0)
        self.assertEqual(p["voice"], "")
        self.assertTrue(p["unknown"]["voice"])


class Guess(unittest.TestCase):
    def test_guessed_mute_marked(self):
        guessed = Channel(fader=0.8, muted=True, muted_guess=True)
        p = view.qml_state(AppState(sc3=reader_like(mic=guessed, line_in=guessed)), 0.0)
        self.assertEqual(p["guess"], {"muteMic": True, "muteLineIn": True})
        self.assertTrue(p["muteMic"])
        p = view.qml_state(AppState(sc3=reader_like(mic=Channel(fader=0.0))), 0.0)
        self.assertEqual(p["guess"], {})
        self.assertTrue(p["unknown"]["muteMic"])     # ноль громкости: mute неизвестен
        st = AppState(sc3=reader_like(mic=guessed), audio=AudioState(present=True, pw_muted=False))
        self.assertIn("заглушён на корпусе (по догадке)", view.tray_tooltip(st, 0.0))


class Live_(unittest.TestCase):
    def test_unknown_live_freezes_like_on_air(self):
        for live, on_air, frozen in ((Live.OFF, False, False), (Live.ON, True, True), (Live.UNKNOWN, False, True)):
            p = view.qml_state(AppState(live=live), 0.0)
            self.assertEqual((p["live"], p["onAir"], p["frozen"]), (live.value, on_air, frozen))

    def test_on_air_time(self):
        st = AppState(live=Live.ON, live_since=1000.0)
        self.assertEqual(view.qml_state(st, 1000.0 + 5025)["onAirTime"], "1:23:45")
        self.assertEqual(view.qml_state(AppState(live=Live.ON), 5.0)["onAirTime"], "")


class Meter(unittest.TestCase):
    def test_db_to_level(self):
        self.assertEqual(view.db_to_level(None), 0.0)
        self.assertEqual(view.db_to_level(-100.0), 0.0)
        self.assertEqual(view.db_to_level(0.0), 1.0)
        self.assertAlmostEqual(view.db_to_level(-27.0), 0.5)

    def test_ballistics(self):
        self.assertEqual(view.meter_step(0.2, 0.9, 0.04), 0.9)           # вверх — сразу
        down = view.meter_step(0.9, 0.0, 0.04)
        self.assertTrue(0.0 < down < 0.9)                               # вниз — плавно
        self.assertEqual(view.meter_step(0.9, 0.0, 10.0), 0.0)

    def test_levels_from_audio(self):
        st = AppState(audio=AudioState(present=True, to_pc_db=0.0, from_pc_db=None))
        self.assertEqual(view.levels(st), (1.0, 0.0))


class Tray(unittest.TestCase):
    def st(self, link=Link.CONNECTED, live=Live.OFF, pw=False, hw=False):
        return AppState(sc3=reader_like(link=link, mic=Channel(fader=0.8, muted=hw)), live=live,
                        audio=AudioState(present=True, pw_muted=pw))

    def test_icons(self):
        self.assertEqual(view.tray_icon(self.st(link=Link.DISCONNECTED, pw=True)), "disconnected")
        self.assertEqual(view.tray_icon(self.st()), "connected")
        self.assertEqual(view.tray_icon(self.st(pw=True)), "muted")
        self.assertEqual(view.tray_icon(self.st(hw=True)), "muted")
        self.assertEqual(view.tray_icon(self.st(live=Live.ON)), "onair")
        self.assertEqual(view.tray_icon(self.st(live=Live.ON, pw=True)), "onair-muted")
        self.assertEqual(view.tray_icon(self.st(live=Live.UNKNOWN)), "connected")  # не красим догадкой
        self.assertEqual(view.tray_icon(self.st(link=Link.NO_ACCESS)), "connected")

    def test_icon_files_exist(self):
        png = ROOT / "opensc3" / "app" / "icons" / "png"
        for name in ("connected", "muted", "disconnected", "onair", "onair-muted"):
            for size in (22, 32):
                for theme in ("dark", "light"):
                    for suffix in ("", "@2x"):
                        self.assertTrue((png / f"sc3-{name}-{size}-{theme}{suffix}.png").is_file())

    def test_tooltip(self):
        tip = view.tray_tooltip(self.st(live=Live.ON, pw=True), 0.0)
        self.assertIn("SC3 подключён", tip)
        self.assertIn("PipeWire", tip)
        self.assertIn("в эфире", tip)


if __name__ == "__main__":
    unittest.main()
