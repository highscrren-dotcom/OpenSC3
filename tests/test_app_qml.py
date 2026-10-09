"""QML окна без экрана: Main.qml на подделке ядра во всех состояниях и кадры макетов (design/panel) с DemoState —
ноль предупреждений QML. Платформа offscreen: окна никуда не выводятся, значка трея нет.
Пропускается, если нет PySide6.
"""
import importlib.util
import logging
import pathlib
import unittest

from tests.test_app_backend import spin, wait_until

HAVE_QT = importlib.util.find_spec("PySide6") is not None
ROOT = pathlib.Path(__file__).resolve().parent.parent
APP_QML = ROOT / "opensc3" / "app" / "qml"
SCENE = ROOT / "design" / "panel" / "scenes" / "Window.qml"
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


def destroy(obj) -> None:
    """Удалить QObject сейчас, а не «когда-нибудь»: deleteLater + доставка отложенных удалений."""
    from PySide6.QtCore import QCoreApplication, QEvent
    obj.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


class QmlProblems:
    """Собирает предупреждения QML (как design/panel/render.py) на время блока with."""

    def __enter__(self):
        from PySide6.QtCore import QtMsgType, qInstallMessageHandler
        self.problems: list[str] = []
        quiet = (QtMsgType.QtDebugMsg, QtMsgType.QtInfoMsg)

        def handler(mode, ctx, msg):
            from_qml = (ctx.file or "").endswith(".qml") or ".qml:" in msg or (ctx.category or "") in ("qml", "js")
            if from_qml and mode not in quiet:
                self.problems.append(msg)

        self._previous = qInstallMessageHandler(handler)
        return self

    def __exit__(self, *exc):
        from PySide6.QtCore import qInstallMessageHandler
        qInstallMessageHandler(self._previous)


class WindowCase(unittest.TestCase):
    """Main.qml на подделке ядра (offscreen); тестов здесь нет — только открытие."""

    def open(self, scenario: str):
        from PySide6.QtCore import QUrl
        from PySide6.QtQml import QQmlApplicationEngine

        from opensc3.app.backend import Backend
        from opensc3.app.fake import FakeCore
        core = FakeCore(scenario)
        backend = Backend(core, live_interval=0.2)
        engine = QQmlApplicationEngine()
        engine.setInitialProperties({"sc3": backend})
        engine.load(QUrl.fromLocalFile(str(APP_QML / "Main.qml")))
        self.assertTrue(engine.rootObjects(), "Main.qml не загрузился")
        window = engine.rootObjects()[0]

        def close():
            window.hide()
            destroy(engine)   # сначала QML, потом бэкенд: иначе привязки увидят sc3 = null
            backend.stop()

        self.addCleanup(close)
        window.visibleChanged.connect(backend.set_window_visible)
        window.show()   # offscreen: никуда не выводится; как в main.py — до старта бэкенда
        backend.start()
        return core, backend, window

class MainWindow(WindowCase):
    def test_every_state_without_qml_warnings(self):
        from opensc3.app.fake import SCENARIOS
        for scenario in SCENARIOS:
            with self.subTest(scenario=scenario), QmlProblems() as qml:
                core, _, window = self.open(scenario)
                self.assertTrue(wait_until(lambda core=core: core.live_calls >= 2))
                spin(0.3)
                if scenario in ("normal", "onair", "disconnected"):
                    for section in ("mic", "voice", "electric", ""):   # ящики выезжают с анимацией
                        window.setProperty("section", section)
                        spin(0.4)
                self.assertEqual(qml.problems, [])

    def test_states_reach_qml(self):
        with QmlProblems() as qml:
            core, backend, window = self.open("onair-muted")
            self.assertTrue(wait_until(lambda: backend.property("onAir") and backend.property("pipewireMute")))
            self.assertTrue(backend.property("frozen"))
            self.assertTrue(wait_until(lambda: core.open_sessions == 0))  # эфир: опрос закрыт
            self.assertEqual((core.reads, core.sessions_opened), (0, 1))  # опрос был — до эфира
            self.assertGreater(window.property("fullHeight") / window.property("zoom"), 900)
            self.assertEqual(qml.problems, [])


class FaderMirror(WindowCase):
    """Колпачок — зеркало: нажали или тянут — он не едет, всплывает подсказка; ящик MIC не открывается."""

    def test_press_and_drag_cap_shows_tip(self):
        from PySide6.QtCore import QObject, QPoint, QPointF, Qt
        from PySide6.QtQuick import QQuickItem
        from PySide6.QtTest import QTest
        with QmlProblems() as qml:
            _, backend, window = self.open("normal")
            window.setProperty("animations", False)
            self.assertTrue(wait_until(lambda: backend.property("polling")))
            panel = window.findChild(QObject, "sc3Panel")
            for name, tip in (("faderMic", "drag-mic"), ("faderLineOut", "drag-lo")):
                fader = window.findChild(QQuickItem, name)
                cap = fader.property("capItem")
                centre = cap.mapToScene(QPointF(cap.width() / 2, cap.height() / 2)).toPoint()
                QTest.mousePress(window, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, centre)
                spin(0.05)
                self.assertEqual(panel.property("tipId"), tip)
                QTest.mouseMove(window, centre + QPoint(0, -60))   # «тянут» вверх
                spin(0.05)
                QTest.mouseRelease(window, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
                                   centre + QPoint(0, -60))
                spin(0.05)
                self.assertEqual(fader.property("value"), backend.property(name))  # только то, что прочитано
                self.assertEqual(panel.property("tipId"), tip)      # видна ещё несколько секунд
                self.assertEqual(window.property("section"), "")    # ящик MIC не открылся
            self.assertEqual(qml.problems, [])


class Tooltips(unittest.TestCase):
    """Каждая подсказка панели — с живым бэкендом (неизвестные поля, эфир) и без предупреждений."""

    def test_every_tip(self):
        from PySide6.QtCore import QUrl
        from PySide6.QtQml import QQmlComponent, QQmlEngine

        from opensc3.app.backend import Backend
        from opensc3.app.fake import FakeCore
        tips = ["rgb", "48v", "custom", "custom-A", "custom-B", "custom-C", "custom-D", "mute-onair", "mute-pw",
                "key-linein", "key-monitor", "key-lineout", "fader-mic", "fader-linein", "fader-hp", "fader-lo",
                "drag-mic", "drag-linein", "drag-hp", "drag-lo"]
        qml = (b'import QtQuick\nimport "' + APP_QML.as_uri().encode() + b'"\n'
               b"Item { id: root; required property QtObject sc3; property string tip: \"\"\n"
               b"  width: w.width; height: w.height\n"
               b"  Sc3Window { id: w; sc3: root.sc3; animations: false; forcedTip: root.tip; profileOpen: true } }")
        for scenario in ("normal", "disconnected", "onair"):
            with self.subTest(scenario=scenario), QmlProblems() as problems:
                backend = Backend(FakeCore(scenario), live_interval=0.2)
                self.addCleanup(backend.stop)
                engine = QQmlEngine()
                component = QQmlComponent(engine)
                component.setData(qml, QUrl.fromLocalFile(str(ROOT / "tests" / "tips.qml")))
                root = component.createWithInitialProperties({"sc3": backend})
                self.assertIsNotNone(root, [e.toString() for e in component.errors()])
                backend.start()
                spin(0.3)
                for tip in tips:
                    root.setProperty("tip", tip)
                    spin(0.02)
                self.assertEqual(problems.problems, [])
                destroy(root)
                destroy(engine)
                backend.stop()


class MockUps(unittest.TestCase):
    """design/panel/render.py рисует эти же компоненты с DemoState: кадры макетов грузятся чисто."""

    def test_design_frames(self):
        from PySide6.QtCore import QUrl
        from PySide6.QtQml import QQmlComponent, QQmlEngine
        frames = ["panel", "tip-custom", "drawer-mic", "drawer-voice", "drawer-electric", "disconnected",
                  "onair", "onair-muted", "muted", "profiles"]
        for frame in frames:
            with self.subTest(frame=frame), QmlProblems() as qml:
                engine = QQmlEngine()   # своя на кадр: третье создание сцены в одном движке очень медленное
                component = QQmlComponent(engine, QUrl.fromLocalFile(str(SCENE)))
                root = component.createWithInitialProperties({"frame": frame, "software": True})
                self.assertIsNotNone(root, [e.toString() for e in component.errors()])
                spin(0.02)
                self.assertEqual(qml.problems, [])
                destroy(root)
                destroy(engine)


if __name__ == "__main__":
    unittest.main()
