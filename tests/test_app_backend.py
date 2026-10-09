"""Бэкенд окна на подделке ядра: когда читается SC3, куда идёт mute, в каких потоках ввод-вывод.

Без экрана (QT_QPA_PLATFORM=offscreen), без SC3, OBS и PipeWire. Пропускается, если нет PySide6.
"""
import importlib.util
import itertools
import logging
import threading
import time
import unittest

from opensc3 import reader as R
from opensc3.app import poll

HAVE_QT = importlib.util.find_spec("PySide6") is not None
app = None


def setUpModule():
    global app
    if not HAVE_QT:
        raise unittest.SkipTest("нет PySide6 (sudo pacman -S pyside6)")
    logging.getLogger("opensc3.app").setLevel(logging.ERROR)  # отказы подделки ожидаемы — без шума в выводе
    from PySide6.QtWidgets import QApplication

    from opensc3.app.headless import prepare
    app = QApplication.instance()
    if app is None:
        prepare(gpu=False)
        app = QApplication([])


def spin(seconds: float) -> None:
    from PySide6.QtCore import QCoreApplication, QEventLoop
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        QCoreApplication.processEvents(QEventLoop.ProcessEventsFlag.AllEvents, 20)
        time.sleep(0.005)


def wait_until(cond, timeout: float = 5.0) -> bool:
    from PySide6.QtCore import QCoreApplication, QEventLoop
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        QCoreApplication.processEvents(QEventLoop.ProcessEventsFlag.AllEvents, 20)
        if cond():
            return True
        time.sleep(0.005)
    return cond()


class BackendCase(unittest.TestCase):
    def make(self, scenario="normal", *, live=None, min_interval=5.0, full_set_first=True):
        from opensc3.app.backend import Backend
        from opensc3.app.fake import FakeCore
        core = FakeCore(scenario, min_interval=min_interval)
        if live is not None:
            core.live = live
        b = Backend(core, live_interval=0.2, full_set_first=full_set_first)
        self.addCleanup(b.stop)
        return core, b

    def visible(self, scenario="normal", **kw):
        """Окно показано до старта (как в main.py): сразу лёгкий опрос."""
        core, b = self.make(scenario, **kw)
        b.set_window_visible(True)
        b.start()
        return core, b


class OnAir(BackendCase):
    def test_on_air_acp_is_never_touched(self):
        from opensc3.model import Live
        for live in (Live.ON, Live.UNKNOWN):
            with self.subTest(live=live):
                core, b = self.visible(live=live)
                b.refresh()
                self.assertTrue(wait_until(lambda core=core: core.live_calls >= 5))
                b.set_window_visible(False)
                b.refresh()                      # скрытое окно: путь полных наборов
                b.set_window_visible(True)
                b.refresh()
                spin(0.3)
                self.assertEqual((core.reads, core.sessions_opened, len(core.poll_reads)), (0, 0, 0))
                self.assertTrue(b.state.acp_note)
                self.assertTrue(b.property("frozen"))
                self.assertFalse(b.property("polling"))

    def test_going_live_stops_poll_and_closes_sc3(self):
        from opensc3.model import Live
        core, b = self.visible()
        self.assertTrue(wait_until(lambda: len(core.poll_reads) >= 2))
        core.live = Live.ON
        self.assertTrue(wait_until(lambda: core.open_sessions == 0 and b.property("frozen")))
        n = len(core.poll_reads)
        spin(1.2)
        self.assertEqual(len(core.poll_reads), n)
        self.assertFalse(b.property("polling"))


class Poll(BackendCase):
    """Лёгкий опрос (решение 9): видимое окно, эфир OFF."""

    def test_one_read_per_half_second_even_with_refresh(self):
        core, b = self.visible()
        self.assertTrue(wait_until(lambda: b.property("polling")))
        for _ in range(3):                       # «Обновить» в первые секунды — поглощается полным набором
            b.refresh()
            spin(0.45)
        start = poll.Plan(dsp=True).queue                       # голос, нота, узлы обработки голоса, остаток набора
        self.assertTrue(wait_until(lambda: len(core.poll_reads) >= len(start) + 1, timeout=10))
        ctrls = [r[0] for r in core.poll_reads]
        self.assertEqual(ctrls[:len(start) + 1], [*start, R.ADC1])  # по одному чтению на слот
        times = [r[1] for r in core.poll_reads]
        gaps = [b_ - a for a, b_ in itertools.pairwise(times)]
        self.assertGreaterEqual(min(gaps), 0.499, gaps)       # не больше одного чтения за 0,5 с
        self.assertLess(max(gaps), 0.6, gaps)                 # и без пропусков
        self.assertEqual(core.reads, 0)                       # ни одного полного набора пачкой
        self.assertEqual(core.sessions_opened, 1)             # одно открытие на весь опрос
        self.assertAlmostEqual(b.property("faderMic"), round(0.8 * 4092) / 4092)
        self.assertAlmostEqual(b.property("faderLineIn"), 16 / 31)
        self.assertEqual((b.property("electricKey"), b.property("voice")), ("C", ""))
        self.assertNotIn("voice", b.property("unknown"))
        self.assertTrue(b.property("polling"))
        self.assertEqual(b.property("acpNote"), "")

    def test_cycle_order(self):
        core, _ = self.visible(full_set_first=False)
        self.assertTrue(wait_until(lambda: len(core.poll_reads) >= 5, timeout=6))
        # и без полного набора голос, нота и узлы обработки голоса — первыми (их мог поменять CLI или кнопка)
        self.assertEqual([r[0] for r in core.poll_reads[:5]], [R.PITCH, R.AUTOTUNE, *R.DSP_NODES])
        self.assertTrue(wait_until(lambda: len(core.poll_reads) >= 8, timeout=4))
        self.assertEqual([r[0] for r in core.poll_reads[5:8]], list(R.POLL_CYCLE[:3]))

    def test_hidden_window_closes_sc3(self):
        core, b = self.visible(full_set_first=False)
        self.assertTrue(wait_until(lambda: core.open_sessions == 1 and core.poll_reads))
        b.set_window_visible(False)
        self.assertTrue(wait_until(lambda: core.open_sessions == 0))
        n = len(core.poll_reads)
        spin(1.2)
        self.assertEqual(len(core.poll_reads), n)
        self.assertFalse(b.property("polling"))
        b.set_window_visible(True)               # показали снова — опрос сразу, без полного набора
        self.assertTrue(wait_until(lambda: core.open_sessions == 1 and len(core.poll_reads) > n))

    def test_three_failures_stop_until_reconnect(self):
        from opensc3.model import Link
        core, b = self.visible(full_set_first=False, min_interval=0.5)
        self.assertTrue(wait_until(lambda: len(core.poll_reads) >= 1))
        core.fail_reads = 3
        self.assertTrue(wait_until(lambda: core.open_sessions == 0, timeout=4))
        self.assertIn("3 неудачи", b.property("acpNote"))
        self.assertEqual(b.property("link"), "error")
        n, opened = len(core.poll_reads), core.sessions_opened
        b.refresh()
        spin(1.0)
        self.assertEqual((len(core.poll_reads), core.sessions_opened), (n, opened))  # до переподключения — нет
        core.plug(Link.DISCONNECTED)
        self.assertTrue(wait_until(lambda: b.property("link") == "disconnected"))
        core.plug(Link.CONNECTED)
        self.assertTrue(wait_until(lambda: core.sessions_opened == opened + 1 and b.property("polling")))
        self.assertEqual(b.property("link"), "connected")

    def test_busy_says_so_and_retries(self):
        from opensc3.app.core import SC3_BUSY
        core, b = self.make()
        core.busy = True
        b.set_window_visible(True)
        b.start()
        self.assertTrue(wait_until(lambda: b.property("acpNote") == SC3_BUSY))
        self.assertEqual(core.sessions_opened, 0)
        core.busy = False                        # CLI отпустил SC3 — следующий тик статуса эфира открывает
        self.assertTrue(wait_until(lambda: b.property("polling") and b.property("acpNote") == ""))

    def test_reads_and_io_are_not_in_main_thread(self):
        core, b = self.visible(full_set_first=False)
        self.assertTrue(wait_until(lambda: len(core.poll_reads) >= 2))
        main = threading.main_thread().name
        self.assertNotIn(main, {r[2] for r in core.poll_reads})
        b.toggleMicMute()
        self.assertTrue(wait_until(lambda: core.mute_calls))
        self.assertNotEqual(core.mute_calls[0][2], main)


class HiddenWindow(BackendCase):
    """Окно скрыто (в трее): SC3 не опрашивается, полный набор — только по событию и не чаще раза в 5 с."""

    def test_refresh_twice_second_refused_by_guard(self):
        from opensc3.model import Live
        core, b = self.make(live=Live.UNKNOWN)  # старт под замком: стартовый набор не состоится
        b.start()
        self.assertTrue(wait_until(lambda: core.live_calls >= 2))
        core.live = Live.OFF
        self.assertTrue(wait_until(lambda: b.state.live is Live.OFF))
        self.assertEqual(core.reads, 0)
        b.refresh()
        self.assertTrue(wait_until(lambda: core.reads == 1 and not b.property("busy") and b.state.sc3.read_at))
        b.refresh()
        self.assertTrue(wait_until(lambda: b.state.acp_note.startswith("рано")))
        spin(0.3)
        self.assertEqual(core.reads, 1)

    def test_no_poll_while_hidden(self):
        core, b = self.make()
        b.start()
        self.assertTrue(wait_until(lambda: core.reads == 1))
        spin(1.2)                    # статус эфира за это время спрошен раз шесть
        self.assertGreaterEqual(core.live_calls, 5)
        self.assertEqual((core.reads, core.sessions_opened, len(core.poll_reads)), (1, 0, 0))
        self.assertNotIn("MainThread", core.read_threads)

    def test_reconnect_reads_again_and_unplug_forgets(self):
        from opensc3.model import Link
        core, b = self.make("disconnected", min_interval=0.5)
        b.start()
        self.assertTrue(wait_until(lambda: core.probes >= 1))
        spin(0.3)
        self.assertEqual(core.reads, 0)
        self.assertEqual(b.property("link"), "disconnected")
        core.plug(Link.CONNECTED)                       # событие hotplug → probe → набор чтений
        self.assertTrue(wait_until(lambda: b.property("connected") and not b.property("unknown").get("faderMic")))
        self.assertEqual(core.reads, 1)
        self.assertAlmostEqual(b.property("faderMic"), 0.8)
        core.plug(Link.DISCONNECTED)
        self.assertTrue(wait_until(lambda: b.property("link") == "disconnected"))
        self.assertTrue(b.property("unknown").get("faderMic"))

    def test_foreign_firmware(self):
        for visible in (False, True):
            with self.subTest(visible=visible):
                core, b = self.make("foreign")
                b.set_window_visible(visible)
                b.start()
                self.assertTrue(wait_until(lambda b=b: b.property("link") == "foreign"))
                self.assertFalse(b.property("connected"))
                spin(0.5)
                self.assertEqual((core.open_sessions, len(core.poll_reads)), (0, 0))


class Mute(BackendCase):
    def test_mute_goes_to_pipewire_off_air_and_on_air(self):
        from opensc3.model import Live
        for live in (Live.OFF, Live.ON):
            with self.subTest(live=live):
                core, b = self.make(live=live)
                b.start()
                self.assertTrue(wait_until(lambda b=b: b.property("audioPresent")))
                b.toggleMicMute()
                self.assertTrue(wait_until(lambda b=b: b.property("pipewireMute")))
                self.assertEqual([(c[0], c[1]) for c in core.mute_calls], [(41, True)])
                b.setMicMute(False)
                self.assertTrue(wait_until(lambda b=b: not b.property("pipewireMute")))
                self.assertEqual([(c[0], c[1]) for c in core.mute_calls], [(41, True), (41, False)])
                self.assertFalse(b.property("muteMic"))  # аппаратный Mute не тронут: записи в SC3 нет

    def test_mute_without_pipewire_nodes(self):
        core, b = self.make("disconnected")
        b.start()
        spin(0.3)
        b.toggleMicMute()
        self.assertTrue(wait_until(lambda: "PipeWire" in b.state.acp_note))
        self.assertEqual(core.mute_calls, [])


class Levels(BackendCase):
    def test_levels_only_while_window_visible(self):
        _, b = self.make()
        b.start()
        b.set_window_visible(True)
        self.assertTrue(wait_until(lambda: b.property("levelOut") > 0.3))
        b.set_window_visible(False)
        self.assertTrue(wait_until(lambda: b.property("levelOut") == 0.0 and b.property("levelIn") == 0.0))


class TrayMenu(BackendCase):
    """Меню и значок трея по состоянию. Значок не показывается (без show() он нигде не регистрируется)."""

    @staticmethod
    def drop_tray(tray) -> None:
        """Удалить трей сейчас (до бэкенда — его родителя), а не отложенным событием, которое переживёт тест."""
        from PySide6.QtCore import QCoreApplication, QEvent
        tray.deleteLater()
        QCoreApplication.sendPostedEvents(tray, QEvent.Type.DeferredDelete)

    def test_tray_follows_state_and_mutes_through_pipewire(self):
        from opensc3.app.tray import Tray
        core, b = self.make()
        calls = []
        tray = Tray(b, show_window=lambda: calls.append("show"), toggle_window=lambda: calls.append("toggle"),
                    quit_app=lambda: calls.append("quit"), visible=False)
        self.addCleanup(self.drop_tray, tray)
        self.assertFalse(tray.icon.icon().isNull())
        self.assertFalse(tray.mute.isEnabled())          # узлов PipeWire ещё не видели
        b.start()
        self.assertTrue(wait_until(lambda: tray.mute.isEnabled()))
        tray.mute.trigger()                              # «Заглушить микрофон» → PipeWire
        self.assertTrue(wait_until(lambda: tray.mute.isChecked() and b.property("pipewireMute")))
        self.assertEqual([(c[0], c[1]) for c in core.mute_calls], [(41, True)])
        self.assertIn("PipeWire", tray.icon.toolTip())
        texts = [a.text() for a in tray.menu.actions() if not a.isSeparator()]
        self.assertEqual(texts, ["Профилей пока нет", "Заглушить микрофон", "Открыть окно SC3", "Выход"])
        self.assertFalse(tray.menu.actions()[0].isEnabled())


class Shape(BackendCase):
    def test_backend_has_every_demo_state_property(self):
        from PySide6.QtCore import QObject

        from tests.test_app_view import demo_names
        _, b = self.make()
        meta = b.metaObject()
        first = QObject.staticMetaObject.propertyCount()   # objectName — от QObject
        names = {meta.property(i).name() for i in range(first, meta.propertyCount())}
        self.assertEqual(names, demo_names())
        for slot in ("refresh()", "toggleMicMute()"):
            self.assertGreaterEqual(meta.indexOfMethod(slot), 0, slot)


if __name__ == "__main__":
    unittest.main()
