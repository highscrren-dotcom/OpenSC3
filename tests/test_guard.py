import tempfile
import unittest
import unittest.mock
from pathlib import Path

from opensc3 import guard as G
from opensc3.model import Live


class Clock:
    def __init__(self, t=100.0):
        self.t = t

    def __call__(self):
        return self.t


class Guard(unittest.TestCase):
    def test_policy_constants(self):
        self.assertIs(G.CONTINUOUS_POLLING, True)   # решение 9: стенд этапа 2 пройден
        self.assertEqual(G.MIN_INTERVAL_FLOOR, 0.5)
        self.assertEqual(G.POLL_INTERVAL, 0.5)
        self.assertEqual(G.AcpGuard().min_interval, 5.0)  # полные наборы — как прежде

    def test_floor(self):
        for bad in (0.49, 0, -1, float("nan")):
            with self.assertRaises(ValueError):
                G.AcpGuard(bad)
            with self.assertRaises(ValueError):
                G.AcpGuard(poll_interval=bad)
        G.AcpGuard(0.5, poll_interval=0.5)

    def test_live_blocks(self):
        g = G.AcpGuard(clock=Clock())
        self.assertEqual(g.check(Live.ON), "идёт эфир или запись")
        self.assertEqual(g.check(Live.UNKNOWN), "эфир неизвестен — OBS не отвечает")
        self.assertEqual(g.check(Live.OFF), "")

    def test_interval(self):
        c = Clock()
        g = G.AcpGuard(clock=c)
        g.mark()
        c.t += 4.9
        self.assertEqual(g.check(Live.OFF), "рано: не чаще раза в 5 с")
        self.assertEqual(g.check(Live.ON), "идёт эфир или запись")  # эфир важнее интервала
        c.t += 0.1
        self.assertEqual(g.check(Live.OFF), "")
        g2 = G.AcpGuard(0.5, clock=c)
        g2.mark()
        self.assertEqual(g2.check(Live.OFF), "рано: не чаще раза в 0,5 с")

    def test_stamp_shared_between_guards(self):
        with tempfile.TemporaryDirectory() as d:
            stamp = Path(d) / "sub" / "acp-last"
            c = Clock()
            G.AcpGuard(clock=c, stamp=stamp).mark()
            self.assertTrue(stamp.exists())
            other = G.AcpGuard(clock=c, stamp=stamp)  # другой процесс CLI
            c.t += 1
            self.assertTrue(other.check(Live.OFF).startswith("рано"))
            c.t += 5
            self.assertEqual(other.check(Live.OFF), "")
            stamp.write_text("мусор")
            self.assertEqual(other.check(Live.OFF), "")
            stamp.write_text(f"{c.t + 1000}")  # из будущего — не в счёт
            self.assertEqual(other.check(Live.OFF), "")

    def test_poll_never_on_air(self):
        g = G.AcpGuard(clock=Clock())
        self.assertEqual(g.check_poll(Live.ON), "идёт эфир или запись")
        self.assertEqual(g.check_poll(Live.UNKNOWN), "эфир неизвестен — OBS не отвечает")
        self.assertEqual(g.check_poll(Live.OFF), "")

    def test_poll_one_read_per_half_second(self):
        c = Clock()
        g = G.AcpGuard(clock=c)
        g.mark_poll()
        c.t += 0.49
        self.assertEqual(g.check_poll(Live.OFF), "рано: не больше одного чтения за 0,5 с")
        self.assertEqual(g.check_poll(Live.ON), "идёт эфир или запись")  # эфир важнее интервала
        c.t += 0.01
        self.assertEqual(g.check_poll(Live.OFF), "")
        g.mark_poll()
        self.assertTrue(g.check_poll(Live.OFF).startswith("рано"))

    def test_poll_and_full_sets_are_separate_rules(self):
        with tempfile.TemporaryDirectory() as d:
            stamp = Path(d) / "acp-last"
            c = Clock()
            g = G.AcpGuard(clock=c, stamp=stamp)
            g.mark_poll()
            self.assertFalse(stamp.exists())         # отметка опроса — только в памяти окна
            self.assertEqual(g.check(Live.OFF), "")  # полному набору опрос не мешает
            g.mark()
            c.t += 0.5
            self.assertEqual(g.check_poll(Live.OFF), "")       # опросу — полный набор тоже
            self.assertTrue(g.check(Live.OFF).startswith("рано"))  # а наборы — по-прежнему раз в 5 с

    def test_poll_off_without_permission(self):
        g = G.AcpGuard(clock=Clock())
        with unittest.mock.patch.object(G, "CONTINUOUS_POLLING", False):
            self.assertEqual(g.check_poll(Live.OFF), "постоянный опрос SC3 выключен")

    def test_default_stamp_in_runtime_dir(self):
        self.assertEqual(G.default_stamp().name, "acp-last")


if __name__ == "__main__":
    unittest.main()
