"""Лёгкий опрос (opensc3/app/poll.py): порядок слотов, сетка времени, разбор ответов. Без Qt и без устройства."""
import itertools
import struct
import unittest

from opensc3 import reader as R
from opensc3.app import poll
from opensc3.app.fake import FakeCore
from opensc3.device import Sc3
from opensc3.model import Sc3State
from tests.fake import FakeTransport

Sc3.DELAY = 0

ADC, LINE, PITCH, TUNE = R.ADC1, R.LINE_IN, R.PITCH, R.AUTOTUNE


def take(plan: poll.Plan, n: int) -> list[int]:
    return [plan.next() for _ in range(n)]


class Order(unittest.TestCase):
    def test_cycle_voice_and_electric_in_poll(self):
        self.assertEqual(R.POLL_CYCLE, (ADC, PITCH, ADC, TUNE, ADC, LINE))
        self.assertEqual(take(poll.Plan(full_set_first=False), 8), [ADC, PITCH, ADC, TUNE, ADC, LINE, ADC, PITCH])
        cycle_s = len(R.POLL_CYCLE) * poll.POLL_INTERVAL
        self.assertEqual(cycle_s, 3.0)                                   # голос, ELECTRIC, Line In — раз в 3 с
        self.assertEqual(poll.cycle_gap(ADC), 1.0)                       # Mic — раз в 1 с
        self.assertEqual((poll.cycle_gap(PITCH), poll.cycle_gap(TUNE), poll.cycle_gap(LINE)), (3.0, 3.0, 3.0))

    def test_full_set_first_one_per_slot(self):
        plan = poll.Plan()
        self.assertEqual(take(plan, len(R.FULL_SET)), list(R.FULL_SET))
        self.assertEqual(take(plan, len(R.POLL_CYCLE)), list(R.POLL_CYCLE))

    def test_refresh_takes_one_slot_no_burst(self):
        self.assertEqual(poll.REFRESH, (R.QUERY,))                     # голос и ELECTRIC и так в круге
        plan = poll.Plan(full_set_first=False)
        take(plan, 2)
        plan.refresh()
        plan.refresh()   # дважды — без дублей
        self.assertEqual(take(plan, 3), [R.QUERY, ADC, TUNE])          # одно чтение вместо слота круга

    def test_refresh_during_full_set_is_absorbed(self):
        plan = poll.Plan()
        plan.refresh()                     # набор только начался
        take(plan, 2)
        plan.refresh()                     # 0x02 уже прочитан, но набор ещё идёт — «Обновить» поглощено
        n = len(R.FULL_SET) - 2 + len(R.POLL_CYCLE)
        self.assertEqual(take(plan, n), list(R.FULL_SET[2:]) + list(R.POLL_CYCLE))

    def test_failed_queued_read_comes_back(self):
        plan = poll.Plan()
        first = plan.next()
        plan.retry(first)
        self.assertEqual(plan.next(), first)
        plan = poll.Plan(full_set_first=False)
        plan.retry(plan.next())   # круг не повторяет — просто идёт дальше
        self.assertEqual(take(plan, 3), [PITCH, ADC, TUNE])


class Grid(unittest.TestCase):
    def test_on_grid(self):
        self.assertEqual(poll.next_slot(t0=10.0, k=0, now=10.02, last=10.0), (1, 10.5))

    def test_never_sooner_than_half_second_after_last_read(self):
        k, at = poll.next_slot(t0=10.0, k=3, now=11.52, last=11.51)   # прошлое чтение началось позже слота
        self.assertEqual(k, 4)
        self.assertAlmostEqual(at, 12.01)

    def test_late_skips_slots_without_burst(self):
        k, at = poll.next_slot(t0=10.0, k=1, now=11.8, last=10.5)     # чтение висело 1,3 с
        self.assertEqual(k, 4)
        self.assertAlmostEqual(at, 12.0)                               # одно чтение, а не три подряд


class Parse(unittest.TestCase):
    def setUp(self):
        self.session = FakeCore().open_sc3()   # настоящий Sc3 поверх поддельного транспорта, verify пройден
        self.addCleanup(self.session.close)

    def test_values_through_reader(self):
        plan = poll.Plan()
        got = {}
        for ctrl in R.FULL_SET:
            got.update(plan.parse(ctrl, self.session.read(ctrl)))
        self.assertAlmostEqual(got["mic"].fader, round(0.8 * 4092) / 4092)
        self.assertIs(got["mic"].muted, False)   # громкость > 0 — MUTE не нажат
        self.assertAlmostEqual(got["line_in"].fader, 16 / 31)
        self.assertEqual((got["electric_key"], got["voice"]), ("C", ""))
        self.assertAlmostEqual(got["dsp_load"], 0.86)
        self.assertEqual(got["mic_trim"], 0.0)   # 0xAC: 4096 = 0 дБ

    def test_mic_trim_and_merge(self):
        """0xAC → поправка MIC в дБ; чтение 0x07 канал Mic заменяет, а поправку оставляет."""
        plan = poll.Plan()
        up = plan.parse(R.MIC_TRIM, b"\xff" + struct.pack("<hhh", 1, 0, 5461))     # ≈ +2,5 дБ
        self.assertAlmostEqual(up["mic_trim"], 2.5, places=2)
        st = poll.merge(Sc3State(), up)
        self.assertAlmostEqual(st.mic.trim_db, 2.5, places=2)
        st = poll.merge(st, plan.parse(ADC, adc(20 * 132)))
        self.assertAlmostEqual(st.mic.fader, 20 / 31)
        self.assertAlmostEqual(st.mic.trim_db, 2.5, places=2)                       # чтение 0x07 её не стёрло
        self.assertIsNone(plan.parse(R.MIC_TRIM, b"\xff" + struct.pack("<hhh", 1, 0, 0))["mic_trim"])
        with self.assertRaises(poll.BadReply):
            plan.parse(R.MIC_TRIM, b"\xff" + struct.pack("<hh", 1, 0))

    def test_trim_first_and_not_in_cycle_or_refresh(self):
        """Поправку MIC читаем первой в каждой сессии окна (и без полного набора), но ни в круге, ни в «Обновить»."""
        self.assertEqual(poll.Plan(trim=True).queue, [R.MIC_TRIM, *(c for c in R.FULL_SET if c != R.MIC_TRIM)])
        self.assertEqual(poll.Plan(full_set_first=False, trim=True).queue, [R.MIC_TRIM])
        self.assertNotIn(R.MIC_TRIM, R.POLL_CYCLE)
        self.assertNotIn(R.MIC_TRIM, poll.REFRESH)
        self.assertEqual(poll.trim_step(2.26, -20, 10), 2.5)
        self.assertEqual(poll.trim_step(-33, -20, 10), -20)
        self.assertEqual(poll.trim_step(12.1, -20, 10), 10)

    def test_voice_from_pitch_alone(self):
        plan = poll.Plan()
        self.assertEqual(plan.parse(PITCH, self.session.read(PITCH)), {"voice": ""})
        self.assertEqual(plan.parse(PITCH, b"\xff" + struct.pack("<hh", 1, -120)), {"voice": "monster"})
        self.assertEqual(plan.parse(PITCH, b"\xff" + struct.pack("<hh", 1, 7)), {"voice": None})
        self.assertEqual(plan.parse(TUNE, b"\xff" + struct.pack("<hhhh", 1, ord("a"), ord("n"), 1)),
                         {"electric_key": "A"})

    def test_short_reply_is_a_failure(self):
        plan = poll.Plan()
        with self.assertRaises(poll.BadReply):
            plan.parse(ADC, b"\xff\x01\x00")
        with self.assertRaises(poll.BadReply):
            plan.parse(LINE, b"\xff" + struct.pack("<h", 1))
        with self.assertRaises(poll.BadReply):
            plan.parse(0x99, b"\xff")


def adc(vol: int) -> bytes:
    return b"\xff" + struct.pack("<10H", 3, 0, vol, vol, 7, 0, 0, 0, 0, 1)


def line(gain: int) -> bytes:
    return b"\xff" + struct.pack("<hhh", 1, 0, gain)


class VirtualPoll(unittest.TestCase):
    """Опрос на виртуальных часах: Plan + next_slot + настоящий Sc3 на поддельном транспорте (tests/fake.py)."""

    def run_poll(self, seconds, change_at, change):
        t = FakeTransport(nodes={R.LINE_IN: [1, 0, 132 * 16], R.PITCH: [0, -40], R.AUTOTUNE: [0, ord("C"), 0, 0]},
                          blocks={R.ADC1: b"\xff" + struct.pack("<10H", 3, 0, 4092, 4092, 7, 0, 0, 0, 0, 1)})
        sc3 = Sc3(t)
        sc3.verify()
        plan, state, seen = poll.Plan(), Sc3State(), []
        t0, k, at, last = 0.0, 0, 0.0, -1.0
        changed = False
        while at < seconds:
            if not changed and at >= change_at:
                change(t)
                changed = True
            ctrl = plan.next()
            state = poll.merge(state, plan.parse(ctrl, sc3.read(ctrl), now=at))
            seen.append((at, ctrl, state))
            last = at
            k, at = poll.next_slot(t0, k, at, last)   # чтение мгновенное: «сейчас» = начало слота
        return seen

    def test_voice_and_electric_reach_state_within_cycle(self):
        change_at = 7.2   # после полного набора, в середине круга
        def press(t):
            t.nodes[R.PITCH] = [1, -120]                          # CHANGE VOICE → Monster
            t.nodes[R.AUTOTUNE] = [1, ord("a"), ord("n"), 1]      # ELECTRIC → «A» на панели
        seen = self.run_poll(20.0, change_at, press)
        voice_at = next(t for t, _, st in seen if t >= change_at and st.voice == "monster")
        key_at = next(t for t, _, st in seen if t >= change_at and st.electric_key == "A")
        self.assertLessEqual(voice_at - change_at, 3.0)
        self.assertLessEqual(key_at - change_at, 3.0)
        times = [t for t, _, _ in seen]
        self.assertGreaterEqual(min(b - a for a, b in itertools.pairwise(times)), 0.5)   # не чаще раза в 0,5 с

    def test_refresh_no_burst(self):
        plan = poll.Plan(full_set_first=False)
        reads = []
        for slot in range(12):
            if slot in (2, 3, 4):
                plan.refresh()                 # «Обновить» трижды подряд
            reads.append(plan.next())
        self.assertEqual(len(reads), 12)       # одно чтение на слот, что бы ни нажимали
        self.assertEqual(reads.count(R.QUERY), 3)   # каждое нажатие — один слот вместо круга, не пачка
        self.assertEqual(reads[2:5], [R.QUERY] * 3)
        self.assertEqual(reads[5:8], [ADC, TUNE, ADC])     # круг идёт дальше с того же места


class MuteGuess(unittest.TestCase):
    """Догадка MUTE по ходу громкости (RESEARCH.md §14): скачок до 0 — MUTE, плавный спуск — ползунок."""

    def feed(self, plan, ctrl, body, t):
        return plan.parse(ctrl, body, now=t)["mic" if ctrl == ADC else "line_in"]

    def test_jump_to_zero_is_guessed_mute_and_release(self):
        plan = poll.Plan(full_set_first=False)
        top = 31 * 132
        self.assertEqual(self.feed(plan, ADC, adc(top), 0.0), R.mic_channel(adc(top)))
        ch = self.feed(plan, ADC, adc(0), 1.0)                  # соседнее чтение Mic — через 1 с
        self.assertEqual((ch.fader, ch.muted, ch.muted_guess), (1.0, True, True))   # колпачок на месте
        ch = self.feed(plan, ADC, adc(0), 2.0)
        self.assertEqual((ch.fader, ch.muted, ch.muted_guess), (1.0, True, True))   # держится, пока 0
        ch = self.feed(plan, ADC, adc(top), 3.0)
        self.assertEqual((ch.fader, ch.muted, ch.muted_guess), (1.0, False, False))  # вернулась — снят

    def test_slow_slide_is_fader(self):
        plan = poll.Plan(full_set_first=False)
        for t, step in ((0.0, 20), (1.0, 9), (2.0, 3), (3.0, 0)):   # рука ведёт через ступени
            ch = self.feed(plan, ADC, adc(step * 132), t)
        self.assertEqual((ch.fader, ch.muted, ch.muted_guess), (0.0, None, False))

    def test_small_or_slow_drop_is_not_guessed(self):
        plan = poll.Plan(full_set_first=False)
        self.feed(plan, ADC, adc(2 * 132), 0.0)                 # 2/31 < 10 %
        self.assertIsNone(self.feed(plan, ADC, adc(0), 1.0).muted)
        plan = poll.Plan(full_set_first=False)
        self.feed(plan, ADC, adc(20 * 132), 0.0)
        self.assertIsNone(self.feed(plan, ADC, adc(0), 1.5).muted)   # слот пропал: 1,5 с — мог быть ползунок
        self.assertEqual(poll.MUTE_GAP, {ADC: 1.1, LINE: 3.1})        # из круга, а не руками
        plan = poll.Plan(full_set_first=False)
        self.assertIsNone(self.feed(plan, ADC, adc(0), 0.0).muted)   # первое чтение — истории нет

    def test_returns_elsewhere_ends_guess(self):
        plan = poll.Plan(full_set_first=False)
        self.feed(plan, ADC, adc(20 * 132), 0.0)
        self.assertTrue(self.feed(plan, ADC, adc(0), 1.0).muted)
        ch = self.feed(plan, ADC, adc(5 * 132), 2.0)
        self.assertEqual((ch.fader, ch.muted, ch.muted_guess), (5 / 31, False, False))

    def test_rounded_zero_is_not_mute(self):
        plan = poll.Plan(full_set_first=False)
        self.feed(plan, LINE, line(14 * 132), 0.0)
        ch = self.feed(plan, LINE, line(50), 3.0)                # ступень 0, но громкость не 0
        self.assertEqual((ch.fader, ch.muted, ch.muted_guess), (0.0, False, False))

    def test_line_in_own_gap(self):
        plan = poll.Plan(full_set_first=False)
        self.feed(plan, LINE, line(14 * 132), 0.0)
        ch = self.feed(plan, LINE, line(0), 3.0)                 # Line In читается раз в 3 с
        self.assertEqual((ch.fader, ch.muted, ch.muted_guess), (14 / 31, True, True))
        plan = poll.Plan(full_set_first=False)
        self.feed(plan, LINE, line(14 * 132), 0.0)
        self.assertIsNone(self.feed(plan, LINE, line(0), 3.6).muted)   # пропущенный слот — уже не догадка
        mic = self.feed(plan, ADC, adc(0), 3.7)                  # каналы независимы
        self.assertIsNone(mic.muted)


if __name__ == "__main__":
    unittest.main()
