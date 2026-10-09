"""Запись из окна — ручка-поправка MIC (`mic.trim`) на подделке ядра: слияние значений, общий темп с опросом, эфир,
предохранитель, расхождение чтения назад, журнал и `sc3 undo`, ручка в QML.

Без экрана (offscreen), без SC3, OBS и PipeWire: сессия опроса — настоящий `device.Sc3` поверх поддельного
транспорта (opensc3/app/fake.py), так что `write.apply`, `Sc3.pace` и чтение назад — настоящий код. Журнал — во
временной папке (не `writes.jsonl` владельца). Пропускается, если нет PySide6.
"""
import contextlib
import importlib.util
import io
import itertools
import json
import logging
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from opensc3 import protocol as P
from opensc3 import reader as R
from opensc3 import write as W
from opensc3.model import Live
from tests.test_app_backend import spin, wait_until

HAVE_QT = importlib.util.find_spec("PySide6") is not None
app = None


def setUpModule():
    global app
    if not HAVE_QT:
        raise unittest.SkipTest("нет PySide6 (sudo pacman -S pyside6)")
    logging.getLogger("opensc3.app").setLevel(logging.ERROR)
    from PySide6.QtQuick import QQuickWindow  # noqa: F401 — корень Main.qml как QQuickWindow
    from PySide6.QtWidgets import QApplication

    from opensc3.app.headless import prepare
    app = QApplication.instance()
    if app is None:
        prepare(gpu=False)
        app = QApplication([])


def write_frames(core) -> list[tuple[int, int, float, str]]:
    """Кадры записи (LEN > 0, не имя узла), ушедшие в поддельный SC3."""
    return [a for a in core.acp if a[1] and a[0] != P.NAMES]


class WriteCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        self.journal = self.dir / "writes.jsonl"

    def visible(self, scenario="write", *, live_interval=0.2):
        """Окно показано, идёт опрос, поправка MIC прочитана."""
        from opensc3.app.backend import Backend
        from opensc3.app.fake import FakeCore
        core = FakeCore(scenario)
        core.journal = self.journal
        b = Backend(core, live_interval=live_interval)
        self.addCleanup(b.stop)
        b.set_window_visible(True)
        b.start()
        self.assertTrue(wait_until(lambda: b.property("polling") and not b.property("unknown").get("trimMic")))
        return core, b

    def after_poll_read(self, core) -> None:
        """Сразу после очередного чтения опроса: до следующего слота ~0,5 с."""
        n = len(core.poll_reads)
        self.assertTrue(wait_until(lambda: len(core.poll_reads) > n))

    def written(self, b, timeout=6.0) -> bool:
        return wait_until(lambda: not b.property("trimMicPending"), timeout=timeout)


class Coalesce(WriteCase):
    def test_turning_writes_only_the_last_value_once(self):
        core, b = self.visible()
        self.assertAlmostEqual(b.property("trimMic"), 2.5, places=2)
        self.after_poll_read(core)
        for db in (3.0, 3.5, 4.0, 4.26):           # крутят ручку: просьбы сливаются, шаг — 0,5 дБ
            b.setMicTrim(db)
        self.assertTrue(b.property("trimMicPending"))
        self.assertEqual(b.property("trimMic"), 4.5)   # пока пишется — показывает просьбу
        self.assertTrue(self.written(b))
        self.assertEqual(core.writes, [(R.MIC_TRIM, 2, W.q12(4.5))])   # ровно один кадр — последнее значение
        self.assertEqual([(a[0], a[1]) for a in write_frames(core)], [(R.MIC_TRIM, 3)])
        self.assertAlmostEqual(b.state.sc3.mic.trim_db, 4.5, places=2)  # модель — прочитанное назад
        self.assertAlmostEqual(b.property("trimMic"), 4.5, places=2)
        self.assertEqual(b.property("acpNote"), "")
        # сеанс записи — тот же путь, что у CLI: типы узлов, снимок, кадр, чтение назад
        w = next(i for i, a in enumerate(core.acp) if a[1] and a[0] == R.MIC_TRIM)
        self.assertEqual([(a[0], a[1]) for a in core.acp[w - 2: w + 2]],
                         [(P.NAMES, 1), (R.MIC_TRIM, 0), (R.MIC_TRIM, 3), (R.MIC_TRIM, 0)])
        self.assertNotIn("MainThread", {a[3] for a in core.acp})       # ввод-вывод — в рабочем потоке

    def test_tempo_shared_with_poll(self):
        """Вместе с опросом — не больше одного обращения к ACP за 0,5 с: каждое обращение сеанса записи (типы,
        снимок, кадр, чтение назад) занимает свой слот, и опрос после записи тоже ждёт."""
        core, b = self.visible()
        for db in (4.0, 1.0):
            self.after_poll_read(core)
            b.setMicTrim(db)
            self.assertTrue(self.written(b))
        n = len(core.acp)
        self.assertTrue(wait_until(lambda: len(core.acp) >= n + 3))    # опрос продолжается
        times = [a[2] for a in core.acp]
        gaps = [y - x for x, y in itertools.pairwise(times)]
        self.assertGreaterEqual(min(gaps), 0.499, gaps)
        self.assertEqual(len(core.writes), 2)
        self.assertEqual(core.sessions_opened, 1)                      # одна сессия на опрос и запись


class Locked(WriteCase):
    def test_on_air_nothing_is_written(self):
        """Эфир: окно под замком (просьба отклоняется сразу), а если эфир начался между просьбой и слотом —
        `write.apply` спрашивает OBS сам и не шлёт ни одного кадра."""
        core, b = self.visible()
        core.live = Live.ON
        self.assertTrue(wait_until(lambda: b.property("frozen")))
        b.setMicTrim(5.0)
        self.assertFalse(b.property("trimMicPending"))
        self.assertIn("эфир", b.property("acpNote"))
        spin(0.6)
        self.assertEqual((core.writes, write_frames(core)), ([], []))

    def test_live_starts_before_the_slot(self):
        core, b = self.visible(live_interval=30.0)      # окно ещё не знает об эфире: статус — раз в 30 с
        self.after_poll_read(core)
        core.live = Live.ON
        calls = core.live_calls
        n = len(core.acp)
        b.setMicTrim(5.0)
        self.assertTrue(self.written(b))
        self.assertGreater(core.live_calls, calls)        # спросили OBS заново перед сеансом
        self.assertEqual((core.writes, write_frames(core)), ([], []))
        self.assertEqual(core.acp[n:], [])                # ни чтения, ни записи — и опрос закрыт сразу
        self.assertTrue(wait_until(lambda: core.open_sessions == 0))
        self.assertIn("эфир", b.property("acpNote"))
        self.assertAlmostEqual(b.property("trimMic"), 2.5, places=2)   # ручка — на прочитанном

    def test_fuse_off_nothing_is_written(self):
        from opensc3.app.backend import WRITE_OFF
        core, b = self.visible("normal")                  # предохранитель по умолчанию выключен
        self.assertFalse(b.property("writeEnabled"))
        b.setMicTrim(3.0)
        self.assertEqual(b.property("acpNote"), WRITE_OFF)
        self.assertFalse(b.property("trimMicPending"))
        b._trimRequest.emit(3.0, time.monotonic())        # мимо проверки окна — рабочий поток откажет сам
        spin(1.2)
        self.assertEqual((core.writes, write_frames(core)), ([], []))
        self.assertEqual(b.property("trimMic"), 0.0)
        self.assertFalse(self.journal.exists())

    def test_fuse_is_kept_in_settings(self):
        from opensc3.app.backend import Backend
        from opensc3.app.core import WRITE_KEY
        core, b = self.visible("normal")
        b.setWriteEnabled(True)
        self.assertTrue(b.property("writeEnabled"))
        self.assertIs(core.settings().value(WRITE_KEY, False, type=bool), True)
        b.setMicTrim(1.0)
        self.assertTrue(self.written(b))
        self.assertEqual(core.writes, [(R.MIC_TRIM, 2, W.q12(1.0))])
        b.setWriteEnabled(False)
        b2 = Backend(core, live_interval=0.2)             # следующий запуск окна
        self.addCleanup(b2.stop)
        self.assertFalse(b2.property("writeEnabled"))


class Mismatch(WriteCase):
    def test_readback_mismatch_rolls_back_and_says_so(self):
        core, b = self.visible()
        core.trim_stuck = True                            # подтверждает, а значение не меняет
        self.after_poll_read(core)
        b.setMicTrim(6.0)
        self.assertTrue(self.written(b))
        note = b.property("acpNote")
        self.assertIn("поправка MIC не записана", note)
        self.assertIn("прочитал +2,5 дБ", note)
        self.assertIn("всё записанное вернул", note)
        self.assertEqual(core.writes, [(R.MIC_TRIM, 2, W.q12(6.0)), (R.MIC_TRIM, 2, W.q12(2.5))])  # кадр и откат
        self.assertAlmostEqual(b.property("trimMic"), 2.5, places=2)  # ручка — к прочитанному
        n = len(core.poll_reads)
        self.assertTrue(wait_until(lambda: len(core.poll_reads) > n))
        self.assertEqual(core.poll_reads[n][0], R.MIC_TRIM)          # и поправка перечитана в ближайшем слоте
        rows = [json.loads(x) for x in self.journal.read_text().splitlines()]
        self.assertEqual([r["op"] for r in rows], ["intent", "write", "intent", "rollback"])
        self.assertTrue(all(r["what"] == "window mic.trim" for r in rows))


class Journal(WriteCase):
    def test_window_write_is_journaled_and_cli_undo_restores_it(self):
        from opensc3 import cli
        from opensc3.app.fake import FakeAcp
        from opensc3.device import Sc3
        core, b = self.visible()
        self.after_poll_read(core)
        b.setMicTrim(-3.0)
        self.assertTrue(self.written(b))
        self.assertEqual(core.sc3_nodes[R.MIC_TRIM][2], W.q12(-3.0))
        rows = [json.loads(x) for x in self.journal.read_text().splitlines()]
        self.assertEqual([(r["op"], r.get("before"), r.get("value")) for r in rows],
                         [("intent", W.q12(2.5), W.q12(-3.0)), ("write", W.q12(2.5), W.q12(-3.0)), ("end", None, None)])
        self.assertEqual({r["what"] for r in rows}, {"window mic.trim"})
        b.stop()                                          # окно отпустило SC3 — CLI может его открыть
        self.assertEqual(core.open_sessions, 0)
        stamps = iter(self.dir / f"acp-last-{k}" for k in range(10))
        out = io.StringIO()
        with mock.patch("opensc3.obs.live_status", return_value=(Live.OFF, None)), \
                mock.patch("opensc3.guard.default_stamp", side_effect=lambda: next(stamps)), \
                mock.patch.object(W, "default_journal", return_value=self.journal), \
                mock.patch.object(cli, "_open", lambda: Sc3(FakeAcp(core))), \
                mock.patch("time.sleep"), contextlib.redirect_stdout(out):
            self.assertEqual(cli.main(["undo"]), 0)
            self.assertIn("window mic.trim", out.getvalue())   # сухой прогон называет сеанс окна
            self.assertEqual(cli.main(["undo", "--write"]), 0)
        self.assertEqual(core.sc3_nodes[R.MIC_TRIM][2], W.q12(2.5))   # `sc3 undo` вернул как было


class Knob(unittest.TestCase):
    """Ручка в окне (Main.qml, offscreen): тянут — пишется; предохранитель выключен — подсказка и ни кадра;
    шестерёнка включает предохранитель."""

    def open(self, scenario):
        from PySide6.QtCore import QUrl
        from PySide6.QtQml import QQmlApplicationEngine

        from opensc3.app.backend import Backend
        from opensc3.app.fake import FakeCore
        from tests.test_app_qml import destroy
        core = FakeCore(scenario)
        backend = Backend(core, live_interval=0.2)
        engine = QQmlApplicationEngine()
        engine.setInitialProperties({"sc3": backend})
        engine.load(QUrl.fromLocalFile(str(Path(__file__).resolve().parent.parent / "opensc3" / "app" / "qml"
                                           / "Main.qml")))
        window = engine.rootObjects()[0]

        def close():
            window.hide()
            destroy(engine)
            backend.stop()

        self.addCleanup(close)
        window.visibleChanged.connect(backend.set_window_visible)
        window.setProperty("animations", False)
        window.setWidth(round(window.property("designWidth")))   # 1:1 — координаты сцены = координаты окна
        window.setHeight(round(window.property("fullHeight")))
        window.show()
        backend.start()
        self.assertTrue(wait_until(lambda: backend.property("polling") and not backend.property("unknown").get("trimMic")))
        return core, backend, window

    @staticmethod
    def centre(item):
        from PySide6.QtCore import QPointF
        return item.mapToScene(QPointF(12, item.height() / 2)).toPoint()

    def test_drag_up_writes_once(self):
        from PySide6.QtCore import QPoint, Qt
        from PySide6.QtQuick import QQuickItem
        from PySide6.QtTest import QTest

        from tests.test_app_qml import QmlProblems
        with QmlProblems() as qml:
            core, backend, window = self.open("write")
            knob = window.findChild(QQuickItem, "trimMic")
            at = self.centre(knob)
            n = len(core.poll_reads)                   # тянуть сразу после чтения опроса: до слота ~0,5 с
            self.assertTrue(wait_until(lambda: len(core.poll_reads) > n))
            QTest.mousePress(window, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, at)
            for dy in range(4, 36, 4):                 # вверх на 32 пикселя = 4 шага по 0,5 дБ
                QTest.mouseMove(window, at - QPoint(0, dy))
                spin(0.01)
            QTest.mouseRelease(window, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, at - QPoint(0, 32))
            self.assertEqual(backend.property("trimMic"), 4.5)
            self.assertTrue(wait_until(lambda: not backend.property("trimMicPending"), timeout=6))
            self.assertEqual(core.writes, [(R.MIC_TRIM, 2, W.q12(4.5))])
            self.assertAlmostEqual(knob.property("db"), 4.5, places=2)
            self.assertEqual(qml.problems, [])

    def test_fuse_off_tip_then_gear_switch(self):
        from PySide6.QtCore import QObject, Qt
        from PySide6.QtQuick import QQuickItem
        from PySide6.QtTest import QTest

        from tests.test_app_qml import QmlProblems
        with QmlProblems() as qml:
            core, backend, window = self.open("normal")
            knob = window.findChild(QQuickItem, "trimMic")
            tip = window.findChild(QQuickItem, "trimTip")
            self.assertFalse(tip.isVisible())
            QTest.mousePress(window, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, self.centre(knob))
            QTest.mouseRelease(window, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, self.centre(knob))
            spin(0.05)
            self.assertTrue(tip.isVisible())
            self.assertEqual(tip.property("title"), "Запись в SC3 выключена — включите в настройках")
            spin(0.6)
            self.assertEqual(core.writes, [])
            gear = window.findChild(QQuickItem, "settingsGear")
            QTest.mouseClick(window, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
                             gear.mapToScene(gear.boundingRect().center()).toPoint())
            spin(0.05)
            switch = window.findChild(QObject, "writeSwitch")
            self.assertTrue(switch.isVisible())
            QTest.mouseClick(window, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
                             switch.mapToScene(switch.boundingRect().center()).toPoint())
            self.assertTrue(wait_until(lambda: backend.property("writeEnabled")))
            self.assertEqual(qml.problems, [])


if __name__ == "__main__":
    unittest.main()
