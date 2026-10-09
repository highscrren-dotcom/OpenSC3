import unittest

from opensc3 import protocol as P
from tests.fake import DESC4


class Frames(unittest.TestCase):
    def test_never(self):
        for c in (0x11, 0xFB, 0xFD, 0xFE, 0xFF):
            with self.assertRaises(P.ProtocolError):
                P.read_frame(c)

    def test_ceiling_and_unknown(self):
        for c in (0xB7, 0xC0, 0xFA, 0x05, 0x0E, 0x0F, 0x10, 0x12, 0x7F):
            with self.assertRaises(P.ProtocolError):
                P.read_frame(c)

    def test_no_writes(self):
        for f in (bytes([0xA5, 0x5A, 0xB0, 0x03, 0x02, 0x00, 0x10, 0x16]),   # запись усиления
                  bytes([0xA5, 0x5A, 0x01, 0x03, 0x01, 0x01, 0x00, 0x16]),   # sys_reset
                  bytes([0xA5, 0x5A, 0xFC, 0x04, 0x01, 1, 2, 3, 0x16]),       # RGB-Plus FC/04
                  bytes([0xA5, 0x5A, 0xFC, 0x01, 0x02, 0x16]),
                  bytes([0xA5, 0x5A, 0x07, 0x01, 0x00, 0x16])):
            with self.assertRaises(P.ProtocolError):
                P.check_frame(f)

    def test_names_index(self):
        P.name_frame(0)
        P.name_frame(54)
        with self.assertRaises(P.ProtocolError):
            P.name_frame(55)
        with self.assertRaises(P.ProtocolError):
            P.check_frame(bytes([0xA5, 0x5A, 0x80, 0x02, 0x01, 0x05, 0x16]))

    def test_reply_body(self):
        r = bytes([0xA5, 0x5A, 0x07, 0x03, 0xFF, 0x01, 0x00, 0x16]) + bytes(248)
        self.assertEqual(P.reply_body(r, 0x07), b"\xff\x01\x00")
        self.assertIsNone(P.reply_body(r, 0x08))          # чужой (устаревший) ответ не принимается
        n = bytes([0xA5, 0x5A, 0x80, 0x03, 0x07, 0x41, 0x42, 0x16])
        self.assertIsNone(P.reply_body(n, 0x80, echo=8))  # эхо индекса не то — это прошлое имя

    def test_real_descriptor(self):
        self.assertEqual(len(DESC4), 36)
        p = P.parse_hid(DESC4)
        self.assertEqual((p["page"], p["usage"], p["report_ids"], p["in"], p["out"], p["feature"]),
                         (0xFF00, 0x55AA, [], 2048, 2048, 64))
        self.assertTrue(P.interface4_ok(p))
        consumer = bytes.fromhex("050c0901a10115002501 09e909ea09b509b609e209b309cd09b7750195088142c0".replace(" ", ""))
        c = P.parse_hid(consumer)
        self.assertEqual((c["page"], c["in"], c["out"]), (0x0C, 8, 0))
        self.assertFalse(P.interface4_ok(c))


if __name__ == "__main__":
    unittest.main()
