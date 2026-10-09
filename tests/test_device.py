import unittest
from unittest import mock

from opensc3 import protocol as P
from opensc3.device import Sc3
from tests.fake import FakeTransport

Sc3.DELAY = 0  # тесты без пауз


class Flow(unittest.TestCase):
    def test_reads_need_verify(self):
        s = Sc3(FakeTransport())
        with self.assertRaises(P.ProtocolError):
            s.read(0x07)
        self.assertEqual(s.t.sent, [])

    def test_full_dump_sends_only_reads(self):
        t = FakeTransport()
        s = Sc3(t)
        s.verify()
        res = s.dump()
        self.assertEqual(res["counters"]["fail"], 0)
        self.assertEqual(len(res["nodes"]), 54)
        self.assertEqual(res["nodes"]["0xb6"]["name"], "1:Fake 54")
        self.assertEqual(res["fc"], P.STOCK_FC.hex(" "))
        for f in t.sent:
            self.assertTrue(f[3] == 0 or (f[2] == P.NAMES and f[3] == 1), f.hex(" "))

    def test_wrong_descriptor_stops_before_acp(self):
        bad = bytes.fromhex("0600ff0aaa55a1018501750896000109018102960001090291 02c0".replace(" ", ""))
        t = FakeTransport(desc=bad)
        with self.assertRaises(P.ProtocolError):
            Sc3(t).verify()
        self.assertEqual(t.sent, [])

    def test_other_firmware_stops_after_version(self):
        t = FakeTransport(version=bytes.fromhex("31000101012205"))
        s = Sc3(t)
        with self.assertRaises(P.ProtocolError):
            s.verify()
        self.assertEqual(len(t.sent), 1)
        with self.assertRaises(P.ProtocolError):
            s.read(0x07)

    def test_dropped_name_is_not_taken_from_previous(self):
        s = Sc3(FakeTransport(drop_names={7}))
        s.verify()
        self.assertEqual(s.name(0x86), "1:Fake 6")
        self.assertIsNone(s.name(0x87))  # устройство промолчало и отдало бы прошлое имя
        self.assertEqual(s.name(0x88), "1:Fake 8")


class Open(unittest.TestCase):
    def test_failed_claim_closes_transport(self):
        for err in (P.Sc3Busy(), P.ProtocolError("claim интерфейса 4: LIBUSB_ERROR_IO")):
            t = mock.MagicMock()
            t.claim.side_effect = err
            with self.assertRaises(type(err)):
                Sc3.open(lambda t=t: t)
            t.close.assert_called_once_with()

    def test_open_ok_keeps_transport(self):
        t = mock.MagicMock()
        s = Sc3.open(lambda: t)
        self.assertIs(s.t, t)
        t.close.assert_not_called()
        s.close()
        t.close.assert_called_once_with()

    def test_busy_is_typed(self):
        from opensc3 import usb
        self.assertTrue(issubclass(P.Sc3Busy, P.ProtocolError))
        self.assertEqual(str(P.Sc3Busy()), "SC3 занят другим процессом (окно SC3?)")
        tr = object.__new__(usb.LibusbTransport)   # без libusb: только ветка claim
        tr.h, tr.claimed, tr.lib = 1, False, mock.MagicMock()
        tr.lib.libusb_claim_interface.return_value = usb.LIBUSB_ERROR_BUSY
        with self.assertRaises(P.Sc3Busy):
            tr.claim()
        tr.lib.libusb_claim_interface.return_value = -1
        tr.lib.libusb_error_name.return_value = b"LIBUSB_ERROR_IO"
        with self.assertRaises(P.ProtocolError) as cm:
            tr.claim()
        self.assertNotIsInstance(cm.exception, P.Sc3Busy)
        self.assertFalse(tr.claimed)


if __name__ == "__main__":
    unittest.main()
