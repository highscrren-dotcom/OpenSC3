"""Дверь окна к ядру (sc3linux/app/core.py, RealCore) сходится с модулями ядра: всё на заглушках, без SC3,
OBS, PipeWire и udev."""
import unittest
from unittest import mock

from sc3linux import guard, hotplug, obs, pipewire, reader
from sc3linux import protocol as P
from sc3linux.app.core import ACP_MIN_INTERVAL, LIVE_TIMEOUT, SC3_BUSY, OpenFailed, RealCore
from sc3linux.model import Link, Live, Sc3State

NODES = pipewire.Sc3Nodes(source_id=41, source_name="in", sink_id=42, sink_name="out")


class Contract(unittest.TestCase):
    def setUp(self):
        self.core = RealCore()

    def test_continuous_polling_by_decision_9(self):
        self.assertTrue(self.core.continuous_polling)
        self.assertIs(self.core.continuous_polling, guard.CONTINUOUS_POLLING)

    def test_guard_shares_stamp_with_cli(self):
        g = self.core.guard()
        self.assertIsInstance(g, guard.AcpGuard)
        self.assertEqual(g.min_interval, ACP_MIN_INTERVAL)
        self.assertEqual(g.stamp, guard.default_stamp())
        self.assertTrue(g.check(Live.ON))          # в эфире — отказ
        self.assertTrue(g.check(Live.UNKNOWN))

    def test_live_status_with_timeout(self):
        with mock.patch.object(obs, "live_status", return_value=(Live.OFF, None)) as f:
            self.assertEqual(self.core.live_status(), (Live.OFF, None))
        f.assert_called_once_with(timeout=LIVE_TIMEOUT)

    def test_read_state_opens_reads_closes(self):
        dev = mock.MagicMock()
        dev.__enter__.return_value = dev
        st = Sc3State(link=Link.CONNECTED)
        with mock.patch("sc3linux.device.Sc3.open", return_value=dev) as opened, \
                mock.patch.object(reader, "read_state", return_value=st) as read:
            self.assertIs(self.core.read_state(123.0), st)
        opened.assert_called_once_with()
        read.assert_called_once_with(dev, 123.0)
        dev.__exit__.assert_called_once()

    def test_open_for_poll(self):
        t = mock.MagicMock()
        with mock.patch("sc3linux.usb.LibusbTransport", return_value=t), \
                mock.patch.object(reader, "verify_link", return_value=None):
            session = self.core.open_sc3()
        t.claim.assert_called_once_with()
        self.assertTrue(callable(session.read) and callable(session.close))
        t.close.assert_not_called()

    def test_open_busy_closes_transport(self):
        t = mock.MagicMock()
        t.claim.side_effect = P.Sc3Busy()
        with mock.patch("sc3linux.usb.LibusbTransport", return_value=t), self.assertRaises(OpenFailed) as cm:
            self.core.open_sc3()
        self.assertEqual(cm.exception.note, SC3_BUSY)
        self.assertIsNone(cm.exception.link)       # временно: попробовать позже
        t.close.assert_called_once_with()          # открытый узел USB не копится

    def test_open_foreign_blocks(self):
        t = mock.MagicMock()
        with mock.patch("sc3linux.usb.LibusbTransport", return_value=t), \
                mock.patch.object(reader, "verify_link", return_value=Link.FOREIGN), \
                self.assertRaises(OpenFailed) as cm:
            self.core.open_sc3()
        self.assertIs(cm.exception.link, Link.FOREIGN)
        t.close.assert_called_once_with()

    def test_hotplug(self):
        with mock.patch.object(hotplug, "probe", return_value=(Link.NO_ACCESS, "/dev/bus/usb/003/013")):
            self.assertEqual(self.core.probe(), (Link.NO_ACCESS, "/dev/bus/usb/003/013"))
        with mock.patch.object(hotplug, "Watcher") as w:
            self.assertIs(self.core.watcher(), w.return_value)

    def test_pipewire_uses_source_id(self):
        with mock.patch.object(pipewire, "find_sc3", return_value=NODES):
            self.assertIs(self.core.find_sc3(), NODES)
        with mock.patch.object(pipewire, "get_mute", return_value=True) as g:
            self.assertTrue(self.core.get_mute(NODES))
        g.assert_called_once_with(41)
        with mock.patch.object(pipewire, "set_mute") as s:
            self.core.set_mute(NODES, True)
        s.assert_called_once_with(41, True)
        with mock.patch.object(pipewire, "LevelMeter") as m:
            self.assertIs(self.core.meter(NODES), m.return_value)
        m.assert_called_once_with(NODES)


class Busy(unittest.TestCase):
    def test_cli_says_who_holds_sc3(self):
        from sc3linux import cli
        self.assertEqual(cli.SC3_BUSY, SC3_BUSY)
        with mock.patch("sc3linux.device.Sc3.open", side_effect=P.Sc3Busy()), self.assertRaises(P.Sc3Busy) as cm:
            cli._open()
        self.assertEqual(str(cm.exception), "SC3 занят другим процессом (окно SC3?)")
        other = P.ProtocolError("не открыть SC3")
        with mock.patch("sc3linux.device.Sc3.open", side_effect=other), self.assertRaises(P.ProtocolError) as cm:
            cli._open()
        self.assertEqual(str(cm.exception), "не открыть SC3")


if __name__ == "__main__":
    unittest.main()
