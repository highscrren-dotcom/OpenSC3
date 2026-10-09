"""Запись в SC3 на подделке: кадры, белый список, эфир, чтение назад, откат, частота, журнал (docs/WRITE.md).

Значения узлов — синтетические (решение 5): похожи по виду на настоящие, но не взяты с устройства."""
import itertools
import tempfile
import unittest
from pathlib import Path

from opensc3 import profiles as PR
from opensc3 import protocol as P
from opensc3 import write as W
from opensc3.device import Sc3
from opensc3.guard import AcpGuard
from opensc3.model import Live
from tests.fake import FakeTransport

Sc3.DELAY = 0  # тесты без пауз

TYPES = [30] * P.NODE_COUNT
for _a, _t in W.NODE_TYPES.items():
    TYPES[_a - P.NODE_MIN] = _t


def eq_node(*slots):
    """Узел EQ: включён, предусиление 0, слоты (вкл., тип, f0, Q, усиление), остальные — пустые (нули)."""
    flat = [x for s in slots for x in s]
    vals = [1, 0, sum(s[0] for s in slots)] + flat
    return vals + [0] * (53 - len(vals))


NODES = {
    W.MIC_TRIM: [1, 0, 4090],
    W.LINE_TRIM: [1, 0, 4096],
    W.VOICE_EQ: eq_node((0, 4, 60, 700, 0), (1, 3, 15000, 700, 0), (1, 1, 400, 720, 256)),
    W.GATE: [0, -5000, 2, 4, 90],
}


def state():
    return {a: list(v) for a, v in NODES.items()}


class Clock:
    """Монотонные часы подделки: sleep двигает время, ничего не ждёт."""

    def __init__(self, t=1000.0):
        self.t = t

    def __call__(self):
        return self.t

    def sleep(self, s):
        self.t += s


def device(**kw):
    clock = Clock()
    nodes = state()
    nodes.update(kw.pop("nodes", {}))
    t = FakeTransport(nodes=nodes, types=kw.pop("types", TYPES), clock=clock, **kw)
    return Sc3(t), t, clock


def writes_sent(t):
    return [f for f in t.sent if f[3] and f[2] != P.NAMES]


def run(sc3, clock, items, live=Live.OFF, journal=None, guard=None):
    """apply на подделке; `live` — статус или список статусов по порядку вопросов (до сеанса, перед кадрами)."""
    seq = iter(live) if isinstance(live, list) else itertools.repeat(live)
    plan = items if isinstance(items, W.Plan) else W.plan_write(items)
    return W.apply(sc3, plan, live=lambda: next(seq), guard=guard or AcpGuard(clock=clock), journal=journal,
                   clock=clock, sleep=clock.sleep).done


class Frames(unittest.TestCase):
    def test_trim_frame(self):
        # +1 дБ = 4096 · 10^(1/20) ≈ 4596 = 0x11F4; индекс 2 — усиление узла (0 — включение, 1 — mute)
        self.assertEqual(W.target("mic.trim", 1).frame, bytes.fromhex(f"a55a{W.MIC_TRIM:02x}0302f41116"))
        self.assertEqual(W.target("mic.trim", "+1,0").value, 4596)
        self.assertEqual(W.target("line.trim", 0).frame, bytes.fromhex(f"a55a{W.LINE_TRIM:02x}0302001016"))

    def test_eq_frame(self):
        # фильтр 3: индексы 13…17 (3 + 5·2 …); −3 дБ в Q8.8 = −768 = 0xFD00
        self.assertEqual(W.target("eq.3.gain", -3).frame, bytes([0xA5, 0x5A, W.VOICE_EQ, 3, 17, 0x00, 0xFD, 0x16]))
        self.assertEqual(W.target("eq.1.on", "on").frame[4], 3)
        self.assertEqual(W.target("eq.10.q", 0.707).frame[4:7], bytes([51, 0xD4, 0x02]))  # Q6.10: 724
        self.assertEqual(W.target("eq.2.type", "highpass").frame[2:7], bytes([W.VOICE_EQ, 3, 9, 4, 0]))
        self.assertEqual(W.target("eq.10.gain", 1).frame[4], 52)  # последний параметр узла EQ

    def test_gate_frame(self):
        self.assertEqual(W.target("gate.threshold", -45).frame,
                         bytes([0xA5, 0x5A, W.GATE, 3, 1]) + (-4500).to_bytes(2, "little", signed=True) + b"\x16")
        self.assertEqual(W.target("gate.on", True).frame, bytes([0xA5, 0x5A, W.GATE, 3, 0, 1, 0, 0x16]))

    def test_outside_whitelist_raises_before_usb(self):
        sc3, t, clock = device()
        for key, value in (("adc1.volume", 1), ("mic.trim", 11), ("mic.trim", -21), ("eq.11.on", 1),
                           ("eq.1.freq", 30000), ("eq.1.q", 9), ("eq.1.gain", 16), ("eq.1.type", "allpass"),
                           ("gate.threshold", -10), ("gate.threshold", -81), ("gate.on", "может"),
                           ("gate.ratio", 0), ("mic.trim", "nan"), ("mic.trim", True), ("eq.1.freq", 80.5),
                           ("comp.on", 1), ("outeq.1.on", 1)):
            with self.subTest(key=key, value=value), self.assertRaises(W.WriteError):
                run(sc3, clock, [(key, value)])
        self.assertEqual(t.sent, [])

    def test_check_frame_follows_whitelist(self):
        P.check_frame(W.target("gate.ratio", 3).frame)
        bad = (
            bytes([0xA5, 0x5A, W.MIC_TRIM, 3, 2, 0xFF, 0x3F, 0x16]),  # 0x3FFF > +10 дБ
            bytes([0xA5, 0x5A, W.MIC_TRIM, 3, 2, 0x00, 0x80, 0x16]),  # −32768
            bytes([0xA5, 0x5A, W.MIC_TRIM, 3, 1, 0x01, 0x00, 0x16]),  # mute узла — не в списке
            bytes([0xA5, 0x5A, W.MIC_TRIM, 3, 0, 0x00, 0x00, 0x16]),  # выключить узел — не в списке
            bytes([0xA5, 0x5A, W.MIC_TRIM, 3, 0xFF, 0x00, 0x10, 0x16]),  # «все параметры сразу»
            bytes([0xA5, 0x5A, W.MIC_TRIM, 7, 0xFF, 1, 0, 0, 0, 0, 0x10, 0x16]),
            bytes([0xA5, 0x5A, W.VOICE_EQ, 3, 2, 0x05, 0x00, 0x16]),  # число фильтров считает устройство
            bytes([0xA5, 0x5A, W.VOICE_EQ, 3, 1, 0x00, 0x01, 0x16]),  # предусиление EQ — не в списке
            bytes([0xA5, 0x5A, W.VOICE_EQ, 3, 53, 0x00, 0x00, 0x16]),  # за последним параметром
            bytes([0xA5, 0x5A, W.GATE, 4, 1, 0x60, 0xEE, 0x00, 0x16]),  # LEN 4
            bytes([0xA5, 0x5A, 0x9E, 7, 4, 0, 0, 0, 0, 0, 0, 0x16]),  # компрессор (DRC) — не в списке
            bytes([0xA5, 0x5A, 0xA5, 3, 13, 0x00, 0x00, 0x16]),       # EQ монитора — не в списке
            bytes([0xA5, 0x5A, 0xB0, 3, 2, 0x00, 0x10, 0x16]),        # общий «мастер в ПК» — не в списке
            bytes([0xA5, 0x5A, 0x85, 3, 1, 0x10, 0x00, 0x16]),        # голоса не пишем
            bytes([0xA5, 0x5A, 0x86, 3, 0, 0x01, 0x00, 0x16]),        # ELECTRIC не пишем
            bytes([0xA5, 0x5A, 0xB6, 3, 2, 0x00, 0x10, 0x16]),        # ползунок Line In
            bytes([0xA5, 0x5A, 0x07, 3, 2, 0x00, 0x10, 0x16]),        # громкость ADC1 (ползунок Mic)
        )
        for f in bad:
            with self.subTest(f=f.hex(" ")), self.assertRaises(P.ProtocolError):
                P.check_frame(f)

    def test_ack(self):
        self.assertTrue(P.write_ack(bytes([0xAC]) + bytes(255), 0xAC))
        self.assertFalse(P.write_ack(bytes([0xAC]) + bytes(255), 0xA2))      # чужой узел
        self.assertFalse(P.write_ack(bytes([0xA5, 0x5A, 0xAC, 0x07, 0xFF]) + bytes(251), 0xAC))  # прошлое чтение
        self.assertTrue(P.write_ack(bytes([0xA5]) + bytes(255), 0xA5))       # узел 0xA5 ≠ начало кадра A5 5A
        self.assertFalse(P.write_ack(bytes(256), 0xAC))


class Apply(unittest.TestCase):
    def test_trim_round_trip(self):
        sc3, t, clock = device()
        done = run(sc3, clock, [("mic.trim", 1)])
        self.assertEqual([d.write.param.key for d in done], ["mic.trim"])
        self.assertTrue(done[0].ack)
        self.assertEqual((done[0].write.before, done[0].readback), (4090, 4596))
        self.assertEqual(t.nodes[W.MIC_TRIM], [1, 0, 4596])
        # порядок кадров: версия (verify) → типы узлов → снимок узла → запись → чтение назад
        self.assertEqual([(f[2], f[3]) for f in t.sent],
                         [(0x00, 0), (P.NAMES, 1), (W.MIC_TRIM, 0), (W.MIC_TRIM, 3), (W.MIC_TRIM, 0)])

    def test_live_on_or_unknown_sends_nothing(self):
        for live in (Live.ON, Live.UNKNOWN):
            sc3, t, clock = device()
            with self.subTest(live=live), self.assertRaises(W.WriteRefused):
                run(sc3, clock, [("mic.trim", 1)], live=live)
            self.assertEqual(t.sent, [])

    def test_guard_interval_sends_nothing(self):
        sc3, t, clock = device()
        g = AcpGuard(clock=clock)
        g.mark()  # набор чтений только что был
        with self.assertRaises(W.WriteRefused):
            run(sc3, clock, [("mic.trim", 1)], guard=g)
        self.assertEqual(t.sent, [])

    def test_guard_marked_after_session(self):
        sc3, _t, clock = device()
        g = AcpGuard(clock=clock)
        run(sc3, clock, [("mic.trim", 1)], guard=g)
        self.assertTrue(g.check(Live.OFF).startswith("рано"))

    def test_live_starts_mid_session(self):
        sc3, t, clock = device()
        items = [("gate.release", 120), ("gate.on", 1), ("mic.trim", 2)]
        # до сеанса OFF; перед 1-м кадром OFF; перед 2-м — эфир
        with self.assertRaises(W.WriteRefused) as cm:
            run(sc3, clock, items, live=[Live.OFF, Live.OFF, Live.ON])
        self.assertEqual(len(writes_sent(t)), 1)  # после начала эфира — ни кадра, и отката тоже
        self.assertEqual([d.write.param.key for d in cm.exception.done], ["gate.release"])

    def test_readback_mismatch_rolls_back(self):
        sc3, t, clock = device(stuck={W.LINE_TRIM})  # значение держит прошивка: подтверждает, но не меняет
        items = [("mic.trim", 3), ("gate.threshold", -48), ("gate.on", 1), ("line.trim", -4)]
        with self.assertRaises(W.WriteError) as cm:
            run(sc3, clock, items)
        self.assertEqual(cm.exception.left, [])
        self.assertIn("line.trim", str(cm.exception))
        self.assertIn("всё записанное вернул", str(cm.exception))
        self.assertEqual(t.nodes, state())  # всё как было
        self.assertEqual([(f[2], f[4]) for f in writes_sent(t)],
                         [(W.MIC_TRIM, 2), (W.GATE, 1), (W.GATE, 0), (W.LINE_TRIM, 2),    # сеанс
                          (W.LINE_TRIM, 2), (W.GATE, 0), (W.GATE, 1), (W.MIC_TRIM, 2)])  # откат — обратно

    def test_failed_rollback_is_reported(self):
        sc3, t, clock = device()
        orig = t.set_output

        def set_output(frame):  # после первой записи в шумодав его чтение «не отвечает» (GET_REPORT — мусор)
            orig(frame)
            if frame[2] == W.GATE and frame[3] == 0 and any(f[2] == W.GATE and f[3] for f in t.sent):
                t.last = bytes(256)

        t.set_output = set_output
        with self.assertRaises(W.WriteError) as cm:
            run(sc3, clock, [("mic.trim", 3), ("gate.on", 1)])
        # откат шумодава не сверился — дальше не идём: следующие шаги проверены только от его состояния
        self.assertEqual([w.param.key for w in cm.exception.left], ["gate.on", "mic.trim"])
        self.assertIn("вернуть не удалось: gate.on, mic.trim — выдерни USB для полного сброса", str(cm.exception))
        self.assertEqual(t.nodes[W.MIC_TRIM][2], W.q12(3))

    def test_transport_breaks_mid_write(self):
        sc3, t, clock = device()
        orig, broke = t.set_output, []

        def set_output(frame):  # один сбой транспорта на кадре записи шумодава
            if frame[2] == W.GATE and frame[3] and not broke:
                broke.append(frame)
                raise P.ProtocolError("control 0x21/0x09: LIBUSB_ERROR_TIMEOUT")
            orig(frame)

        t.set_output = set_output
        with self.assertRaises(W.WriteError):
            run(sc3, clock, [("mic.trim", 3), ("gate.on", 1)])
        self.assertEqual(t.nodes[W.MIC_TRIM], NODES[W.MIC_TRIM])

    def test_no_ack_but_readback_ok(self):
        sc3, t, clock = device(no_ack={W.MIC_TRIM})
        done = run(sc3, clock, [("mic.trim", -6)])
        self.assertFalse(done[0].ack)
        self.assertEqual(t.nodes[W.MIC_TRIM][2], W.q12(-6))

    def test_write_rate(self):
        sc3, t, clock = device()
        items = [("mic.trim", 1), ("line.trim", -2), ("gate.release", 150), ("gate.on", 1), ("eq.2.freq", 14000)]
        run(sc3, clock, items)
        stamps = [ts for f, ts in zip(t.sent, t.times, strict=True) if f[3] and f[2] != P.NAMES]
        self.assertEqual(len(stamps), 7)  # фильтр 2 включён — правка в скобках выкл./вкл.
        gaps = [b - a for a, b in itertools.pairwise(stamps)]
        self.assertTrue(all(g >= W.WRITE_INTERVAL - 1e-9 for g in gaps), gaps)
        for bad in (0.4, 0, float("nan")):
            with self.assertRaises(ValueError):
                W.Pacer(bad)

    def test_wrong_types_stop_before_writes(self):
        types = list(TYPES)
        types[W.GATE - P.NODE_MIN] = 2
        sc3, t, clock = device(types=types)
        with self.assertRaises(W.WriteError):
            run(sc3, clock, [("gate.on", 1)])
        self.assertEqual(writes_sent(t), [])

    def test_unreadable_node_stops_before_writes(self):
        sc3, t, clock = device(silent={W.GATE})
        with self.assertRaises(W.WriteError):
            run(sc3, clock, [("mic.trim", 1), ("gate.on", 1)])
        self.assertEqual(writes_sent(t), [])

    def test_wrong_node_length_stops(self):
        sc3, t, clock = device(nodes={W.GATE: [0, -5000, 2]})
        with self.assertRaises(W.WriteError):
            run(sc3, clock, [("gate.on", 1)])
        self.assertEqual(writes_sent(t), [])

    def test_foreign_firmware_stops(self):
        sc3, t, clock = device(version=bytes.fromhex("31000101012205"))
        with self.assertRaises(P.ProtocolError):
            run(sc3, clock, [("mic.trim", 1)])
        self.assertEqual(writes_sent(t), [])

    def test_unrestorable_original_refused(self):
        sc3, t, clock = device(nodes={W.GATE: [0, -9000, 2, 4, 90]})  # порог −90 дБ — вне белого списка
        with self.assertRaises(W.WriteError) as cm:
            run(sc3, clock, [("gate.threshold", -45)])
        self.assertIn("вернуть не смогу", str(cm.exception))
        self.assertEqual(writes_sent(t), [])

    def test_nothing_to_do(self):
        sc3, t, clock = device()
        self.assertEqual(run(sc3, clock, [("gate.threshold", -50), ("gate.ratio", 2)]), [])
        self.assertEqual(writes_sent(t), [])


class Filters(unittest.TestCase):
    """Пустой слот EQ (частота 0, Q 0) включённым не бывает — ни при записи, ни при откате."""

    def test_empty_slot_filled_then_enabled_and_restored(self):
        sc3, t, clock = device()
        run(sc3, clock, [("eq.5.on", 1), ("eq.5.type", "peak"), ("eq.5.freq", 4000), ("eq.5.q", 0.8),
                         ("eq.5.gain", 3)])
        self.assertEqual(t.nodes[W.VOICE_EQ][23:28], [1, 0, 4000, 819, 768])
        self.assertEqual([f[4] for f in writes_sent(t)], [25, 26, 27, 23])  # тип уже peak (0); включение — последним
        plan = W.plan_write([("eq.5.freq", 0), ("eq.5.q", 0), ("eq.5.gain", 0), ("eq.5.on", 0)],
                            {a: list(v) for a, v in t.nodes.items()})
        self.assertEqual([w.param.key for w in plan.writes], ["eq.5.on", "eq.5.freq", "eq.5.q", "eq.5.gain"])

    def test_enabling_empty_slot_refused(self):
        for items in ([("eq.5.on", 1)], [("eq.5.on", 1), ("eq.5.freq", 1000)], [("eq.2.freq", 0)],
                      [("eq.2.q", 0)]):
            sc3, t, clock = device()
            with self.subTest(items=items), self.assertRaises(W.WriteError):
                run(sc3, clock, items)
            self.assertEqual(writes_sent(t), [])

    def test_rollback_path_is_checked_too(self):
        # слот 4 включён, но пуст (испорченное состояние): правка с откатом в «включённый ноль» — не пишем
        broken = eq_node((0, 4, 60, 700, 0), (1, 3, 15000, 700, 0), (1, 1, 400, 720, 256), (1, 0, 0, 0, 0))
        with self.assertRaises(W.WriteError):
            W.plan_write([("eq.4.freq", 1000), ("eq.4.q", 1)], {**state(), W.VOICE_EQ: broken})


def bad_filter_states(t):
    """Обёртка над подделкой: после каждого кадра записи — нет ли включённого фильтра EQ с частотой или Q вне границ."""
    bad, orig = [], t.set_output

    def set_output(frame):
        orig(frame)
        if frame[3]:
            eq = t.nodes[W.VOICE_EQ]
            for k in range(10):
                en, _t, f0, q, _g = eq[3 + 5 * k: 8 + 5 * k]
                if en and not (20 <= f0 <= 20000 and 307 <= q <= 8192):
                    bad.append((k + 1, f0, q))

    t.set_output = set_output
    return bad


def fail_once(t, match):
    """Один сбой транспорта на первом кадре, для которого match(frame) истинно."""
    orig, hit = t.set_output, []

    def set_output(frame):
        if match(frame) and not hit:
            hit.append(frame)
            raise P.ProtocolError("control 0x21/0x09: LIBUSB_ERROR_TIMEOUT")
        orig(frame)

    t.set_output = set_output
    return hit


class Review(unittest.TestCase):
    """Находки ревью (scratchpad/review/r1…r5): откат, эфир после паузы, Ctrl+C, журнал, прерванный откат."""

    def test_r1_rollback_stops_at_first_failure(self):
        # mic.trim держит прошивка → откат; откатный кадр eq.5.on = 0 не дошёл. Раньше откат шёл дальше и оставлял
        # включённый фильтр с частотой 0 и Q 0; теперь — стоп в проверенном состоянии
        sc3, t, clock = device(stuck={W.MIC_TRIM})
        bad = bad_filter_states(t)
        hit = fail_once(t, lambda f: f[2] == W.VOICE_EQ and f[3] and f[4] == 23 and f[5:7] == b"\0\0")
        with self.assertRaises(W.WriteError) as cm:
            run(sc3, clock, [("eq.5.freq", 4000), ("eq.5.q", 0.8), ("eq.5.on", 1), ("mic.trim", 3)])
        self.assertTrue(hit)
        self.assertEqual(bad, [])
        self.assertEqual([w.param.key for w in cm.exception.left], ["eq.5.on", "eq.5.q", "eq.5.freq"])
        self.assertIn("выдерни USB для полного сброса", str(cm.exception))
        self.assertEqual(t.nodes[W.VOICE_EQ][23:26], [1, 0, 4000])

    def test_r1_mirror_parked_slot(self):
        # зеркально: фильтр 2 выключен и «запаркован» в нули; откат Q не дошёл — частоту и включение не трогаем
        sc3, t, clock = device(stuck={W.MIC_TRIM})
        bad = bad_filter_states(t)
        fail_once(t, lambda f: f[2] == W.VOICE_EQ and f[3] and f[4] == 11 and f[5:7] != b"\0\0")
        with self.assertRaises(W.WriteError) as cm:
            run(sc3, clock, [("eq.2.on", 0), ("eq.2.freq", 0), ("eq.2.q", 0), ("mic.trim", 3)])
        self.assertEqual(bad, [])
        self.assertEqual([w.param.key for w in cm.exception.left], ["eq.2.q", "eq.2.freq", "eq.2.on"])
        self.assertEqual(t.nodes[W.VOICE_EQ][8:12], [0, 3, 0, 0])

    def test_r2_live_checked_after_pause(self):
        sc3, t, clock = device()
        stream_at = clock.t + 0.3  # эфир начинается во время паузы перед вторым кадром

        def live():
            return Live.ON if clock.t >= stream_at else Live.OFF

        with self.assertRaises(W.WriteRefused):
            W.apply(sc3, W.plan_write([("gate.on", 1), ("mic.trim", 2)]), live=live, guard=AcpGuard(clock=clock),
                    clock=clock, sleep=clock.sleep)
        stamps = [ts for f, ts in zip(t.sent, t.times, strict=True) if f[3] and f[2] != P.NAMES]
        self.assertEqual(len(stamps), 1)
        self.assertTrue(all(ts < stream_at for ts in stamps))

    def test_r2_rollback_checks_live_after_pause(self):
        sc3, t, clock = device(stuck={W.LINE_TRIM})
        stream_at = clock.t + 0.7  # после второго кадра, во время паузы перед первым кадром отката

        def live():
            return Live.ON if clock.t >= stream_at else Live.OFF

        with self.assertRaises(W.WriteError) as cm:
            W.apply(sc3, W.plan_write([("mic.trim", 2), ("line.trim", -3)]), live=live,
                    guard=AcpGuard(clock=clock), clock=clock, sleep=clock.sleep)
        stamps = [ts for f, ts in zip(t.sent, t.times, strict=True) if f[3] and f[2] != P.NAMES]
        self.assertTrue(all(ts < stream_at for ts in stamps), stamps)
        self.assertEqual([w.param.key for w in cm.exception.left], ["line.trim", "mic.trim"])

    def test_r3_interrupt_is_journaled_and_rolled_back(self):
        sc3, t, clock = device()
        orig_node, fired = sc3.node, []

        def node(addr):  # Ctrl+C во время чтения назад после первого кадра записи
            if any(f[3] and f[2] != P.NAMES for f in t.sent) and not fired:
                fired.append(addr)
                raise KeyboardInterrupt
            return orig_node(addr)

        sc3.node = node
        j = W.Journal()
        with self.assertRaises(KeyboardInterrupt):
            run(sc3, clock, PR.PODCAST.items, journal=j)
        self.assertEqual(t.nodes, state())  # отправленный кадр вернули
        self.assertEqual([(e["op"], e.get("readback")) for e in j.entries[:2]], [("intent", None), ("write", None)])
        self.assertEqual(j.entries[-1]["op"], "rollback")
        self.assertTrue(j.entries[-1]["ok"])

    def test_r3_interrupt_without_rollback_still_journaled(self):
        sc3, t, clock = device()
        orig_node = sc3.node

        def node(addr):  # прерывание не даёт и откату прочитать назад
            if any(f[3] and f[2] != P.NAMES for f in t.sent):
                raise KeyboardInterrupt
            return orig_node(addr)

        sc3.node = node
        j = W.Journal()
        with self.assertRaises(KeyboardInterrupt):
            run(sc3, clock, [("gate.on", 1), ("mic.trim", 2)], journal=j)
        self.assertEqual([(e["op"], e["key"], e.get("readback")) for e in j.entries],
                         [("intent", "gate.on", None), ("write", "gate.on", None),
                          ("intent", "gate.on", None), ("rollback", "gate.on", None)])
        self.assertEqual([(w.param.key, w.value, w.expect) for w in W.undo_writes(j.entries)], [("gate.on", 0, 1)])

    def test_r4_undo_keeps_param_without_readback(self):
        sc3, t, clock = device()
        orig = t.set_output

        def set_output(f):  # чтение назад mic.trim «молчит»: GET_REPORT отдаёт прошлое подтверждение
            orig(f)
            if f[2] == W.MIC_TRIM and f[3] == 0 and any(x[2] == W.MIC_TRIM and x[3] for x in t.sent):
                t.last = bytes([W.MIC_TRIM]) + bytes(255)

        t.set_output = set_output
        j = W.Journal()
        with self.assertRaises(W.WriteError) as cm:  # перед откатом — эфир: откат не начат
            run(sc3, clock, [("gate.on", 1), ("mic.trim", 3)], live=[Live.OFF] * 3 + [Live.ON], journal=j)
        self.assertEqual([w.param.key for w in cm.exception.left], ["mic.trim", "gate.on"])
        undo = W.undo_writes(j.entries)
        self.assertEqual([(w.param.key, w.value, w.expect) for w in undo],
                         [("mic.trim", 4090, W.q12(3)), ("gate.on", 0, 1)])

    def test_r5_interrupted_undo_resumes_original(self):
        sc3, t, clock = device()
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "writes.jsonl"
            run(sc3, clock, [("gate.on", 1), ("mic.trim", 3), ("gate.release", 150)], journal=W.Journal(path))
            original = W.last_session(path)
            clock.t += 10
            with self.assertRaises(W.WriteRefused):  # sc3 undo --write: эфир начался перед вторым кадром
                run(sc3, clock, W.plan_write(W.undo_writes(original)), live=[Live.OFF, Live.OFF, Live.ON],
                    journal=W.Journal(path, undoes=original[0]["session"]))
            self.assertEqual(W.last_session(path), original)  # прерванный откат — не сеанс для undo
            clock.t += 10
            run(sc3, clock, W.plan_write(W.undo_writes(W.last_session(path))),
                journal=W.Journal(path, undoes=original[0]["session"]))
            self.assertEqual(t.nodes, state())
            done = W.last_session(path)  # удачный откат — сам сеанс: следующий undo вернёт отменённое
            self.assertNotEqual(done[0]["session"], original[0]["session"])
            self.assertEqual(done[-1]["op"], "end")


class Review2(unittest.TestCase):
    """Второе ревью (scratchpad/probe*.py): журнал до первого кадра, пропуски в итоге, подделанный журнал."""

    def test_a_unwritable_journal_sends_nothing(self):
        sc3, t, clock = device()
        with tempfile.TemporaryDirectory() as d:
            ro = Path(d) / "ro"
            ro.mkdir()
            ro.chmod(0o500)
            try:
                with self.assertRaises(W.WriteError) as cm:
                    run(sc3, clock, [("mic.trim", 1)], journal=W.Journal(ro / "sub" / "writes.jsonl"))
            finally:
                ro.chmod(0o700)
        self.assertIn("без журнала не пишу", str(cm.exception))
        self.assertEqual(t.sent, [])

    def test_a_intent_before_frame_and_journal_failure_mid_session(self):
        sc3, t, clock = device()
        j = W.Journal(Path("/dev/null"))  # открывается; запись строк — проверяем порядок и отказ на ходу
        orig_send = W._send
        order_seen = []

        def send(sc3_, frame):
            order_seen.append(j.entries[-1]["op"])  # перед отправкой последняя строка — намерение
            return orig_send(sc3_, frame)

        with unittest.mock.patch.object(W, "_send", send):
            run(sc3, clock, [("gate.on", 1)], journal=j)
        self.assertEqual(order_seen, ["intent"])

        sc3, t, clock = device()
        j = W.Journal()
        puts, real = [], j._put

        def put(e, strict=False):  # второй кадр: журнал отказал на намерении
            puts.append(e.get("op"))
            if e.get("op") == "intent" and e.get("phase") == "write" and puts.count("intent") == 2:
                raise W.WriteError("журнал перестал дописываться (диск полон) — дальше не пишу")
            return real(e, strict)

        j._put = put
        with self.assertRaises(W.WriteError) as cm:
            run(sc3, clock, [("gate.on", 1), ("mic.trim", 2)], journal=j)
        self.assertIn("всё записанное вернул", str(cm.exception))
        self.assertEqual(t.nodes, state())
        self.assertEqual(len(writes_sent(t)), 2)  # gate.on и его откат; mic.trim не ушёл

    def test_b_undo_reports_skipped(self):
        sc3, t, clock = device()
        j = W.Journal()
        run(sc3, clock, [("gate.on", 1), ("mic.trim", 2)], journal=j)
        t.nodes[W.MIC_TRIM][2] = 5000  # поменяли после сеанса
        clock.t += 10
        res = W.apply(sc3, W.plan_write(W.undo_writes(j.entries)), live=lambda: Live.OFF,
                      guard=AcpGuard(clock=clock), clock=clock, sleep=clock.sleep)
        self.assertEqual([d.write.param.key for d in res.done], ["gate.on"])
        self.assertEqual([(w.param.key, w.before, w.expect) for w in res.skipped], [("mic.trim", 5000, W.q12(2))])
        self.assertEqual(t.nodes[W.MIC_TRIM][2], 5000)

    def test_c_forged_journal_sends_nothing(self):
        p = W.BY_KEY["mic.trim"]
        sc3, t, clock = device()
        with self.assertRaises(W.WriteError):  # «до» вне белого списка: отказ до эфира, журнала и USB
            run(sc3, clock, [W.Write(p, 30000, expect=4596)])
        with self.assertRaises(W.WriteError):
            run(sc3, clock, W.undo_writes([{"op": "write", "key": "mic.trim", "before": 30000, "value": 4596,
                                            "readback": 4596}]))
        self.assertEqual(t.sent, [])
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "writes.jsonl"
            path.write_text("[1, 2]\nне json\n" + '{"session": "s", "op": "write", "key": "mic.trim", '
                            '"before": Infinity, "value": 4596, "readback": NaN}\n'
                            '{"session": "s", "op": "write", "key": "gate.on", "before": true, "value": 1}\n'
                            '{"session": "s", "op": "write", "key": "gate.on", "before": 0, "value": 1.5}\n')
            rows = W.last_session(path)
            self.assertEqual(len(rows), 3)
            self.assertEqual(W.undo_writes(rows), [])


class Order(unittest.TestCase):
    def test_enabled_filter_is_bracketed(self):
        plan = W.plan_write([("eq.3.type", "peak"), ("eq.3.freq", 300), ("eq.3.gain", -3)], state())
        self.assertEqual([(w.param.key, w.value) for w in plan.writes],
                         [("eq.3.on", 0), ("eq.3.type", 0), ("eq.3.freq", 300), ("eq.3.gain", -768), ("eq.3.on", 1)])

    def test_disabled_filter_params_then_on(self):
        plan = W.plan_write([("eq.1.on", 1), ("eq.1.freq", 80)], state())
        self.assertEqual([w.param.key for w in plan.writes], ["eq.1.freq", "eq.1.on"])

    def test_switch_off_first(self):
        plan = W.plan_write([("eq.2.freq", 12000), ("eq.2.on", 0)], state())
        self.assertEqual([w.param.key for w in plan.writes], ["eq.2.on", "eq.2.freq"])

    def test_noop_and_repeat(self):
        plan = W.plan_write([("mic.trim", 1), ("gate.ratio", 2), ("mic.trim", 2)], state())
        self.assertEqual([(w.param.key, w.value) for w in plan.writes], [("mic.trim", W.q12(2))])

    def test_dry_run_without_state(self):
        plan = W.plan_write([("eq.3.freq", 300), ("eq.3.on", 1)])
        self.assertEqual([w.before for w in plan.writes], [None, None])
        self.assertTrue(all("a5 5a" in line for line in plan.lines()))

    def test_too_many(self):
        items = [(f"eq.{n}.{f}", v) for n in range(1, 11) for f, v in
                 (("type", "peak"), ("freq", 1000), ("q", 1), ("gain", 1), ("on", 1))]
        items += [("mic.trim", 1), ("line.trim", 1)] + [(f"gate.{k}", v) for k, v in
                                                       (("on", 1), ("threshold", -40), ("ratio", 3),
                                                        ("attack", 5), ("release", 100))]
        items += [(f"eq.{n}.gain", 2) for n in range(1, 11)]  # повторы ключа не считаются
        self.assertEqual(len(W.plan_write(items).writes), 57)
        with self.assertRaises(W.WriteError):  # все 10 фильтров включены и меняются: 57 + 20 скобок > 64
            W.plan_write(items, state={**state(), W.VOICE_EQ: eq_node(*[(1, 1, 500, 700, 0)] * 10)})


class Journal(unittest.TestCase):
    def test_journal_and_undo(self):
        sc3, t, clock = device()
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "writes.jsonl"
            run(sc3, clock, [("eq.3.freq", 300), ("gate.on", 1), ("mic.trim", 2)], journal=W.Journal(path))
            rows = W.last_session(path)
            keys = ["eq.3.on", "eq.3.freq", "eq.3.on", "gate.on", "mic.trim"]
            self.assertEqual([(r["op"], r.get("key")) for r in rows],
                             [(op, k) for k in keys for op in ("intent", "write")] + [("end", None)])
            self.assertTrue(all(r["ok"] and r["ack"] for r in rows if r["op"] == "write"))
            undo = W.undo_writes(rows)
            self.assertEqual([w.param.key for w in undo], ["mic.trim", "gate.on", "eq.3.freq"])  # eq.3.on — как был
            clock.t += 10  # правило 4: следующий сеанс — не раньше чем через 5 с
            run(sc3, clock, W.plan_write(undo), journal=W.Journal(path))
            self.assertEqual(t.nodes, state())
            self.assertNotEqual(W.last_session(path)[0]["session"], rows[0]["session"])

    def test_undo_skips_changed_since(self):
        sc3, t, clock = device()
        journal = W.Journal()
        run(sc3, clock, [("gate.on", 1), ("mic.trim", 2)], journal=journal)
        t.nodes[W.MIC_TRIM][2] = 4096  # с панели нажали голос — пресет переписал усиление
        plan = W.plan_write(W.undo_writes(journal.entries), {a: list(v) for a, v in t.nodes.items()})
        self.assertEqual([w.param.key for w in plan.writes], ["gate.on"])
        self.assertEqual([w.param.key for w in plan.skipped], ["mic.trim"])
        t.nodes[W.GATE][0] = 0  # а то, что уже стоит как было, — не пропуск и не запись
        plan = W.plan_write(W.undo_writes(journal.entries), {a: list(v) for a, v in t.nodes.items()})
        self.assertEqual((plan.writes, [w.param.key for w in plan.skipped]), ([], ["mic.trim"]))

    def test_no_journal_file(self):
        self.assertEqual(W.last_session(Path("/nonexistent/opensc3/writes.jsonl")), [])


class Profiles(unittest.TestCase):
    def test_podcast_is_whitelisted_and_restorable(self):
        p = PR.PROFILES["podcast"]
        self.assertTrue(p.draft)
        keys = [k for k, _ in p.items]
        self.assertEqual(len(keys), len(set(keys)))
        plan = W.plan_write(p.items, state())
        self.assertLessEqual(len(plan.writes), W.MAX_WRITES)

    def test_podcast_applies_on_fake(self):
        sc3, t, clock = device()
        p = PR.PROFILES["podcast"]
        run(sc3, clock, p.items)
        rows = PR.diff(p, {a: list(v) for a, v in t.nodes.items()})
        self.assertTrue(all(r.same for r in rows), [r for r in rows if not r.same])
        eq = t.nodes[W.VOICE_EQ]
        enabled = [eq[3 + 5 * k: 8 + 5 * k] for k in range(10) if eq[3 + 5 * k]]
        self.assertEqual([(f[1], f[2]) for f in enabled],
                         [(4, 80), (3, 15000), (0, 300), (4, 80), (0, 4000), (2, 10000)])

    def test_diff(self):
        rows = PR.diff(PR.PROFILES["podcast"], state())
        by = {r.key: r for r in rows}
        self.assertTrue(by["gate.ratio"].same)
        self.assertFalse(by["gate.on"].same)
        self.assertEqual(by["gate.on"].now, "выкл.")
        self.assertEqual(PR.diff(PR.PROFILES["podcast"], None)[0].now, "?")


if __name__ == "__main__":
    unittest.main()
