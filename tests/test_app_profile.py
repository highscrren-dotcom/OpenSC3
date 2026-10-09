"""Профиль «Подкаст» и «Вернуть как было» из меню окна, «Стоп», эфир посреди сеанса, предохранитель, перечитывание
узлов после кнопки голоса, ящик MIC из прочитанных узлов, подпись профиля в шапке.

Подделка ядра (opensc3/app/fake.py): сессия — настоящий `device.Sc3` поверх поддельного транспорта, так что
`write.apply`, темп `Sc3.pace` и чтение назад — настоящий код. Журнал — во временной папке. Без экрана; пропускается,
если нет PySide6. Сеанс «Подкаста» на подделке — 27 кадров записи, по два слота на кадр (кадр и чтение назад):
около 30 с.
"""
import importlib.util
import itertools
import json
import logging
import tempfile
import unittest
from pathlib import Path

from opensc3 import profiles as PR
from opensc3 import reader as R
from opensc3 import write as W
from opensc3.app import poll
from opensc3.model import Live
from tests.test_app_backend import spin, wait_until

HAVE_QT = importlib.util.find_spec("PySide6") is not None
app = None
PODCAST_S = 60   # с запасом: 27 кадров × 2 слота × 0,5 с + снимок


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


def write_frames(core):
    return [a for a in core.acp if a[1] and a[0] != 0x80]


def find_item(item, name: str):
    """Элемент сцены по objectName — обходом дерева элементов (делегаты Repeater findChild не находит)."""
    if item.objectName() == name:
        return item
    for child in item.childItems():
        if (found := find_item(child, name)) is not None:
            return found
    return None


def journal_rows(path: Path) -> list[dict]:
    return [json.loads(x) for x in path.read_text().splitlines()] if path.exists() else []


class Case(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.journal = Path(tmp.name) / "writes.jsonl"

    def visible(self, scenario="write", *, live_interval=0.2):
        """Окно видно, идёт опрос, узлы обработки голоса прочитаны и подпись профиля решена."""
        from opensc3.app.backend import Backend
        from opensc3.app.fake import FakeCore
        core = FakeCore(scenario)
        core.journal = self.journal
        b = Backend(core, live_interval=live_interval)
        self.addCleanup(b.stop)
        b.set_window_visible(True)
        b.start()
        self.assertTrue(wait_until(lambda: b.property("polling") and b.property("profile") != "", timeout=8))
        return core, b

    def idle(self, b, timeout=PODCAST_S) -> bool:
        return wait_until(lambda: b.property("writeTitle") == "", timeout=timeout)

    def started(self, b, frames=1) -> bool:
        return wait_until(lambda: b.property("writeDone") >= frames, timeout=15)


class Podcast(Case):
    def test_apply_whole_profile_in_shared_tempo(self):
        core, b = self.visible()
        self.assertEqual(b.property("profile"), "заводской")
        before = {a: list(v) for a, v in core.sc3_nodes.items()}
        want = len(W.plan_write(PR.PODCAST.items, before).writes)       # сколько отличается (у подделки — 27)
        self.assertEqual(want, 27)
        seen = []
        b.stateChanged.connect(lambda: seen.append((b.property("writeTitle"), b.property("writeDone"),
                                                    b.property("writeTotal"))))
        b.profileAction("podcast")
        self.assertEqual(b.property("writeTitle"), "Подкаст")
        self.assertTrue(self.idle(b))
        self.assertEqual(len(core.writes), want)                         # ровно столько кадров, сколько отличалось
        self.assertIn(("Подкаст", want, want), seen)                     # прогресс «27 из 27» в шапке
        self.assertIn(f"записано кадров — {want}", b.property("acpNote"))
        self.assertTrue(all(r.same for r in PR.diff(PR.PODCAST, core.sc3_nodes)))
        gaps = [y[2] - x[2] for x, y in itertools.pairwise(core.acp)]
        self.assertGreaterEqual(min(gaps), 0.499)                        # вместе с опросом — ≤ 1 обращения за 0,5 с
        rows = journal_rows(self.journal)
        self.assertEqual({r["what"] for r in rows}, {"window profile podcast"})
        self.assertEqual(sum(r["op"] == "write" for r in rows), want)
        # после сеанса узлы перечитаны: подпись «Подкаст», в ящике — фильтры профиля
        self.assertTrue(wait_until(lambda: b.property("profile") == "Подкаст", timeout=4))
        slots = b.property("dsp")["eq"]["slots"]
        self.assertEqual((slots[4]["freq"], slots[4]["on"], slots[4]["gain"]), ("4 кГц", True, "+3,0 дБ"))
        self.assertEqual(b.property("dsp")["gain"]["value"], "+6,0 дБ")
        self.assertTrue(b.property("profiles")[0]["active"])

    def test_stop_rolls_back_this_session(self):
        core, b = self.visible()
        before = {a: list(v) for a, v in core.sc3_nodes.items()}
        b.profileAction("podcast")
        self.assertTrue(self.started(b, 3))
        b.stopWrite()
        self.assertTrue(self.idle(b, timeout=20))
        note = b.property("acpNote")
        self.assertIn("остановлено", note)
        self.assertIn("возвращено", note)
        self.assertEqual(core.sc3_nodes, before)                         # всё записанное вернули
        rows = journal_rows(self.journal)
        wrote = sum(r["op"] == "write" for r in rows)
        self.assertGreaterEqual(wrote, 3)
        self.assertEqual(sum(r["op"] == "rollback" and r["ok"] for r in rows), wrote)
        self.assertEqual(len(core.writes), 2 * wrote)                   # кадр и его откат
        self.assertTrue(wait_until(lambda: b.property("profile") == "заводской", timeout=4))

    def test_on_air_mid_session_stops_without_rollback(self):
        core, b = self.visible()
        b.profileAction("podcast")
        self.assertTrue(self.started(b, 2))
        core.live = Live.ON
        self.assertTrue(self.idle(b, timeout=10))
        rows = journal_rows(self.journal)
        wrote = sum(r["op"] == "write" for r in rows)
        self.assertGreaterEqual(wrote, 2)
        self.assertFalse(any(r["op"] == "rollback" for r in rows))      # в эфире ни кадра, отката тоже
        self.assertEqual(len(core.writes), wrote)
        self.assertTrue(wait_until(lambda: "вернуть после эфира" in b.property("acpNote")
                                   or b.property("frozen"), timeout=3))
        self.assertTrue(wait_until(lambda: core.open_sessions == 0))

    def test_fuse_off_writes_nothing(self):
        from opensc3.app.backend import WRITE_OFF
        core, b = self.visible("normal")
        rows = b.property("profiles")
        self.assertEqual([r["action"] for r in rows], ["podcast", "undo", "factory"])
        self.assertFalse(any(r["enabled"] for r in rows))
        self.assertEqual(b.property("profileHint"), WRITE_OFF)
        b.profileAction("podcast")
        self.assertEqual(b.property("acpNote"), WRITE_OFF)
        b._jobRequest.emit("podcast")                                    # мимо проверки окна — поток откажет сам
        spin(1.2)
        self.assertEqual((core.writes, write_frames(core)), ([], []))
        self.assertFalse(self.journal.exists())

    def test_undo_returns_last_session(self):
        core, b = self.visible()
        b.setMicTrim(-1.0)
        self.assertTrue(wait_until(lambda: not b.property("trimMicPending"), timeout=6))
        self.assertEqual(core.sc3_nodes[R.MIC_TRIM][2], W.q12(-1.0))
        self.assertTrue(wait_until(lambda: b.property("profile") == "свой", timeout=3))
        b.profileAction("undo")
        self.assertTrue(self.idle(b, timeout=10))
        self.assertEqual(core.sc3_nodes[R.MIC_TRIM][2], W.q12(2.5))      # как было до ручки
        rows = journal_rows(self.journal)
        self.assertTrue(rows[-1]["what"].startswith("window undo ") and rows[-1].get("undoes"))
        self.assertTrue(wait_until(lambda: b.property("profile") == "заводской", timeout=3))


class Preset(Case):
    def test_voice_button_rereads_dsp_nodes_one_per_slot(self):
        from opensc3.app.fake import EQ_VOICE, GATE_VOICE
        core, b = self.visible("normal")
        n = len(core.poll_reads)
        core.press_voice("monster")                                       # пресет переписал узлы
        self.assertTrue(wait_until(lambda: b.property("voice") == "Monster", timeout=5))
        self.assertTrue(wait_until(lambda: b.state.sc3.nodes.get(R.VOICE_EQ) == tuple(EQ_VOICE)
                                   and b.state.sc3.nodes.get(R.GATE) == tuple(GATE_VOICE), timeout=5))
        reads = core.poll_reads[n:]
        k = next(i for i, r in enumerate(reads) if r[0] == R.PITCH and i + 1 < len(reads)
                 and reads[i + 1][0] in R.DSP_NODES)
        self.assertEqual([r[0] for r in reads[k + 1: k + 4]], list(R.DSP_NODES))   # сразу после, по одному
        gaps = [y[1] - x[1] for x, y in itertools.pairwise(reads[k: k + 4])]
        self.assertGreaterEqual(min(gaps), 0.499)                                # не пачкой
        self.assertEqual(b.property("profile"), "заводской")
        self.assertEqual(b.property("dsp")["gate"]["rows"][0]["value"], "−42,0 дБ")
        self.assertEqual(write_frames(core), [])                                # только чтения


class Drawer(Case):
    def test_mic_drawer_shows_fake_nodes(self):
        _core, b = self.visible()
        dsp = b.property("dsp")
        slots = dsp["eq"]["slots"]
        self.assertEqual(len(slots), 10)
        self.assertEqual([(s["n"], s["name"], s["freq"], s["on"]) for s in slots[:3]],
                         [(1, "ФВЧ", "60 Гц", False), (2, "ФНЧ", "15 кГц", True), (3, "полка НЧ", "400 Гц", True)])
        self.assertTrue(all(s["empty"] for s in slots[3:]))
        self.assertEqual([(x["kind"], x["f"]) for x in dsp["eq"]["bands"]], [("lp", 15000), ("ls", 400)])
        self.assertFalse(dsp["gate"]["on"])
        self.assertEqual([r["value"] for r in dsp["gate"]["rows"]], ["−50,0 дБ", "1:2", "4 мс", "90 мс"])
        self.assertEqual(dsp["gain"]["value"], "+2,5 дБ")
        self.assertNotIn("comp", dsp)                                      # компрессора на пути в ПК нет

    def test_mic_drawer_in_qml(self):
        from PySide6.QtCore import QUrl
        from PySide6.QtQml import QQmlApplicationEngine

        from opensc3.app.backend import Backend
        from opensc3.app.fake import FakeCore
        from tests.test_app_qml import QmlProblems, destroy
        with QmlProblems() as qml:
            core = FakeCore("write")
            b = Backend(core, live_interval=0.2)
            engine = QQmlApplicationEngine()
            engine.setInitialProperties({"sc3": b})
            engine.load(QUrl.fromLocalFile(str(Path(__file__).resolve().parent.parent / "opensc3" / "app" / "qml"
                                               / "Main.qml")))
            window = engine.rootObjects()[0]
            window.visibleChanged.connect(b.set_window_visible)
            window.setProperty("section", "mic")
            window.setProperty("profileOpen", True)
            window.show()
            b.start()
            self.assertTrue(wait_until(lambda: b.property("dsp").get("gate") is not None, timeout=6))
            spin(0.5)
            window.hide()
            destroy(engine)
            b.stop()
            self.assertEqual(qml.problems, [])


class Label(unittest.TestCase):
    """Подпись профиля — чистая логика (poll.profile_label, journal_written, written_matches)."""

    def nodes(self, **change):
        from opensc3.app.fake import EQ_PLAIN, GATE_PLAIN
        n = {R.MIC_TRIM: (1, 0, 4096), R.VOICE_EQ: tuple(EQ_PLAIN), R.GATE: tuple(GATE_PLAIN)}
        state = {a: list(v) for a, v in n.items()}
        for key, value in change.items():
            w = W.target(key.replace("_", "."), value)
            state[w.param.addr][w.param.idx] = w.value
        return {a: tuple(v) for a, v in state.items()}

    def podcast(self):
        state = {a: list(v) for a, v in self.nodes().items()}
        for w in W.plan_write(PR.PODCAST.items, state).writes:
            state[w.param.addr][w.param.idx] = w.value
        return {a: tuple(v) for a, v in state.items()}

    def test_labels(self):
        base = self.nodes()
        trimmed = self.nodes(mic_trim=3)
        self.assertEqual(poll.profile_label({}, poll.BASE_KNOWN, base), "")               # узлы не прочитаны
        self.assertEqual(poll.profile_label(base, poll.BASE_CONNECT, None), "")           # ещё не решили
        self.assertEqual(poll.profile_label(base, poll.BASE_KNOWN, base), "заводской")
        self.assertEqual(poll.profile_label(trimmed, poll.BASE_KNOWN, base), "свой")
        self.assertEqual(poll.profile_label(trimmed, poll.BASE_PRESET, None), "заводской")  # кнопку только нажали
        self.assertEqual(poll.profile_label(trimmed, poll.BASE_WRITTEN, None), "свой")
        for mode in (poll.BASE_KNOWN, poll.BASE_WRITTEN, poll.BASE_PRESET):
            self.assertEqual(poll.profile_label(self.podcast(), mode, base), "Подкаст")

    def test_journal_written(self):
        rows = [{"session": "s1", "op": "intent", "phase": "write", "key": "mic.trim", "before": 4096,
                 "value": W.q12(3)},
                {"session": "s1", "op": "write", "key": "mic.trim", "before": 4096, "value": W.q12(3),
                 "readback": W.q12(3)},
                {"session": "s1", "op": "end"}]
        written = poll.journal_written(rows)
        self.assertEqual(written, {"mic.trim": W.q12(3)})
        self.assertTrue(poll.written_matches(written, self.nodes(mic_trim=3)))
        self.assertFalse(poll.written_matches(written, self.nodes()))   # после кнопки или питания — уже не то
        self.assertEqual(poll.journal_written([{**r, "undoes": "s0"} for r in rows]), {})  # откат своего не оставляет
        self.assertEqual(poll.journal_written([]), {})
        self.assertFalse(poll.written_matches({}, self.nodes()))

    def test_connect_with_written_state_says_own(self):
        """Окно открыли, а в SC3 — то, что оставил последний сеанс журнала (писали из CLI): «свой»."""
        from opensc3.app.backend import Backend
        from opensc3.app.fake import FakeCore
        with tempfile.TemporaryDirectory() as tmp:
            journal = Path(tmp) / "writes.jsonl"
            core = FakeCore("write")                                     # поправка уже +2,5 дБ
            journal.write_text("\n".join(json.dumps(r) for r in (
                {"session": "cli", "what": "set mic.trim 2.5", "op": "intent", "phase": "write", "key": "mic.trim",
                 "before": 4096, "value": W.q12(2.5)},
                {"session": "cli", "what": "set mic.trim 2.5", "op": "write", "key": "mic.trim", "before": 4096,
                 "value": W.q12(2.5), "readback": W.q12(2.5)},
                {"session": "cli", "what": "set mic.trim 2.5", "op": "end"})) + "\n")
            core.journal = journal
            b = Backend(core, live_interval=0.2)
            b.set_window_visible(True)
            b.start()
            try:
                self.assertTrue(wait_until(lambda: b.property("profile") != "", timeout=8))
                self.assertEqual(b.property("profile"), "свой")
            finally:
                b.stop()


class Menu(unittest.TestCase):
    """Меню профиля в окне (Main.qml, offscreen): пункт «Подкаст — применить», прогресс в шапке, «Стоп»."""

    def test_click_podcast_then_stop(self):
        from PySide6.QtCore import Qt, QUrl
        from PySide6.QtQml import QQmlApplicationEngine
        from PySide6.QtQuick import QQuickItem
        from PySide6.QtTest import QTest

        from opensc3.app.backend import Backend
        from opensc3.app.fake import FakeCore
        from tests.test_app_qml import QmlProblems, destroy
        with QmlProblems() as qml, tempfile.TemporaryDirectory() as tmp:
            core = FakeCore("write")
            core.journal = Path(tmp) / "writes.jsonl"
            before = {a: list(v) for a, v in core.sc3_nodes.items()}
            b = Backend(core, live_interval=0.2)
            engine = QQmlApplicationEngine()
            engine.setInitialProperties({"sc3": b})
            engine.load(QUrl.fromLocalFile(str(Path(__file__).resolve().parent.parent / "opensc3" / "app" / "qml"
                                               / "Main.qml")))
            window = engine.rootObjects()[0]
            window.visibleChanged.connect(b.set_window_visible)
            window.setProperty("animations", False)
            window.setWidth(round(window.property("designWidth")))
            window.setHeight(round(window.property("fullHeight")))
            window.show()
            b.start()
            try:
                self.assertTrue(wait_until(lambda: b.property("profile") != "", timeout=8))
                window.setProperty("profileOpen", True)
                spin(0.1)
                row = find_item(window.contentItem(), "profileRow-podcast")   # делегат Repeater — не QObject-ребёнок
                self.assertTrue(row.isVisible())
                QTest.mouseClick(window, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
                                 row.mapToScene(row.boundingRect().center()).toPoint())
                self.assertTrue(wait_until(lambda: b.property("writeDone") >= 2, timeout=15))
                self.assertFalse(window.property("profileOpen"))            # меню закрылось
                label = window.findChild(QQuickItem, "profileLabel")
                self.assertRegex(label.property("text"), r"^Подкаст: \d+ из 27$")
                stop = window.findChild(QQuickItem, "stopWrite")
                QTest.mouseClick(window, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
                                 stop.mapToScene(stop.boundingRect().center()).toPoint())
                self.assertTrue(wait_until(lambda: b.property("writeTitle") == "", timeout=20))
                self.assertEqual(core.sc3_nodes, before)
                self.assertFalse(stop.isVisible())
            finally:
                window.hide()
                destroy(engine)
                b.stop()
            self.assertEqual(qml.problems, [])


if __name__ == "__main__":
    unittest.main()
