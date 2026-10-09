"""status, dump, descriptor: в эфире и при неизвестном эфире USB не открывается; два вызова подряд — второй отказ."""
import contextlib
import io
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from sc3linux import cli
from sc3linux.device import Sc3
from sc3linux.model import Live
from tests.fake import FakeTransport

Sc3.DELAY = 0
COMMANDS = (["status"], ["dump"], ["descriptor"])


class Gate(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.stamp = Path(self.tmp.name) / "acp-last"
        self.opened = []

    def fake_open(self):
        self.opened.append(1)
        return Sc3(FakeTransport())

    def run_cli(self, argv, live):
        out, err = io.StringIO(), io.StringIO()
        with mock.patch("sc3linux.obs.live_status", return_value=live), \
                mock.patch("sc3linux.guard.default_stamp", return_value=self.stamp), \
                mock.patch.object(cli, "_open", self.fake_open), \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = cli.main(argv)
        return code, out.getvalue(), err.getvalue()

    def test_live_refuses_before_usb(self):
        for live, reason in (((Live.ON, 1.0), "идёт эфир или запись"),
                             ((Live.UNKNOWN, None), "эфир неизвестен — OBS не отвечает")):
            for argv in COMMANDS:
                code, out, err = self.run_cli(argv, live)
                self.assertEqual(self.opened, [], argv)
                self.assertNotEqual(code, 0, argv)
                self.assertIn(reason, err, argv)
                self.assertEqual(out, "", argv)
        self.assertFalse(self.stamp.exists())  # отказ — не набор чтений

    def test_guard_second_call_refused(self):
        for argv in (["descriptor"], ["dump"]):
            self.stamp.unlink(missing_ok=True)
            code, _, _ = self.run_cli(argv, (Live.OFF, None))
            self.assertEqual((code, len(self.opened)), (0, 1), argv)
            code, _, err = self.run_cli(argv, (Live.OFF, None))
            self.assertEqual(len(self.opened), 1, f"{argv}: второй раз USB не открыт")
            self.assertEqual(code, 3)
            self.assertIn("рано: не чаще раза в 5 с", err)
            self.opened.clear()

    def test_guard_shared_across_commands(self):
        self.run_cli(["descriptor"], (Live.OFF, None))
        code, _, err = self.run_cli(["status"], (Live.OFF, None))
        self.assertEqual((code, len(self.opened)), (3, 1))
        self.assertIn("рано", err)

    def test_mark_even_if_open_fails(self):
        def broken():
            raise cli.P.ProtocolError("не открыть SC3")
        with mock.patch.object(self, "fake_open", broken):
            code, _, err = self.run_cli(["descriptor"], (Live.OFF, None))
        self.assertEqual(code, 1)
        self.assertIn("не открыть SC3", err)
        self.assertTrue(self.stamp.exists())


if __name__ == "__main__":
    unittest.main()
