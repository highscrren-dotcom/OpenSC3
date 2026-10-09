"""Наличие SC3 и права — на поддельном sysfs (tmpdir); Watcher — на поддельном pyudev. USB-узел не открывается."""
import os
import tempfile
import unittest
from pathlib import Path

from opensc3 import hotplug as H
from opensc3.model import Link


def usb(root: Path, name: str, vid: str, pid: str, bus=3, num=7):
    d = root / name
    d.mkdir()
    for k, v in (("idVendor", vid), ("idProduct", pid), ("busnum", bus), ("devnum", num)):
        (d / k).write_text(f"{v}\n")
    return d


class Probe(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.sys = Path(self.tmp.name)
        usb(self.sys, "1-1", "1d6b", "0002", 1, 1)
        (self.sys / "3-13:1.0").mkdir()  # интерфейс: без idVendor
        self.asked = []

    def access(self, ok):
        def f(path, mode):
            self.asked.append((path, mode))
            return ok
        return f

    def test_disconnected(self):
        self.assertEqual(H.probe(self.sys, access=self.access(True)), (Link.DISCONNECTED, None))
        self.assertEqual(self.asked, [])

    def test_connected_and_no_access(self):
        usb(self.sys, "3-13", "3142", "0c33", 3, 7)
        self.assertEqual(H.probe(self.sys, access=self.access(True)), (Link.CONNECTED, "/dev/bus/usb/003/007"))
        self.assertEqual(self.asked, [("/dev/bus/usb/003/007", os.R_OK | os.W_OK)])  # нужна и запись
        self.assertEqual(H.probe(self.sys, access=self.access(False)), (Link.NO_ACCESS, "/dev/bus/usb/003/007"))

    def test_vanishing_device(self):
        d = usb(self.sys, "3-13", "3142", "0c33")
        (d / "devnum").unlink()  # ушло посреди чтения
        self.assertEqual(H.probe(self.sys, access=self.access(True)), (Link.DISCONNECTED, None))
        self.assertIsNone(H.usb_device(self.sys / "нет"))

    def test_same_serial_other_pid_ignored(self):
        usb(self.sys, "3-14", "3142", "a010")  # микрофон AM8T того же SDK
        self.assertEqual(H.probe(self.sys, access=self.access(True))[0], Link.DISCONNECTED)


class Dev:
    def __init__(self, **props):
        self.properties = props


class FakeMonitor:
    def __init__(self):
        self.queue, self.filters, self.started = [], [], False

    @classmethod
    def from_netlink(cls, ctx):
        return cls()

    def filter_by(self, subsystem, device_type=None):
        self.filters.append((subsystem, device_type))

    def start(self):
        self.started = True

    def fileno(self):
        return 99

    def poll(self, timeout=None):
        assert timeout == 0, "poll() окна не должен блокировать"
        return self.queue.pop(0) if self.queue else None


class FakePyudev:
    Monitor = FakeMonitor

    @staticmethod
    def Context():
        return object()


class Watch(unittest.TestCase):
    def test_events(self):
        w = H.Watcher(pyudev=FakePyudev)
        mon = w._mon
        self.assertEqual((mon.filters, mon.started, w.fileno()), ([("usb", "usb_device")], True, 99))
        self.assertFalse(w.poll())
        mon.queue += [Dev(ACTION="add", PRODUCT="1d6b/2/614")]
        self.assertFalse(w.poll())
        mon.queue += [Dev(ACTION="add", PRODUCT="1d6b/2/614"), Dev(ACTION="remove", PRODUCT="3142/c33/100")]
        self.assertTrue(w.poll())
        self.assertEqual(mon.queue, [])  # выбрано всё
        mon.queue += [Dev(ACTION="change", ID_VENDOR_ID="3142", ID_MODEL_ID="0c33")]
        self.assertTrue(w.poll())
        mon.queue += [Dev(ACTION="add", PRODUCT="мусор")]
        self.assertFalse(w.poll())

    def test_real_pyudev_if_present(self):
        try:
            import pyudev  # noqa: F401
        except ImportError:
            self.skipTest("нет python-pyudev")
        w = H.Watcher()
        self.assertIsInstance(w.fileno(), int)
        self.assertIsInstance(w.poll(), bool)


if __name__ == "__main__":
    unittest.main()
