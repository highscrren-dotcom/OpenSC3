"""Расшифровка блоков на настоящих числах SC3 (дамп 07.10.2026) — то, что видели глазами в docs/RESEARCH.md §12.4."""
import unittest

from sc3linux import layouts as L
from tests.fake import BLOCKS


def body(ctrl):
    return bytes.fromhex(BLOCKS[ctrl].replace(" ", ""))


class Blocks(unittest.TestCase):
    def test_query(self):
        q = L.query(body(0x02))
        self.assertEqual((q["ram_kb"], q["mcps"], q["auto_refresh"], q["cpu_mhz"], q["ram_max_kb"]),
                         (188, 278, 1, 320, 320))

    def test_system_sample_rate(self):
        self.assertEqual(L.sample_rate(L.system(body(0x01))["sr_index"]), 44100)

    def test_adc1_mic(self):
        a = L.adc(body(0x07))
        self.assertEqual((a["channels"], a["mute"], a["vol_l"], a["hpf"], a["dc_blocker"]), (3, 0, 4092, 0, 1))
        self.assertAlmostEqual(L.adc_vol_db(4095), 0.0)

    def test_pga1(self):
        p = L.pga1(body(0x06))
        self.assertEqual((p["mic1_gain"], p["mic1_boost"]), (15, 0))
        self.assertAlmostEqual(L.mic_pga_db(15), 0.42)
        self.assertEqual(L.MIC_BOOST[0], "выкл.")

    def test_agc1_gate_off(self):
        g = L.agc(body(0x08))
        self.assertEqual((g["mode"], g["gate_en"], g["gate_threshold"], g["frame_time"]), (0, 0, 5, 10))

    def test_nodes(self):
        self.assertAlmostEqual(L.q12_db(4096), 0.0)
        self.assertAlmostEqual(L.q12_db(7284), 5.0, places=1)
        at = L.autotune([1, 67, 110, 1])
        self.assertEqual((at["key"], at["snap"]), ("C", "n"))
        self.assertEqual(L.autotune([0, ord("X"), 117, 0])["key"], "хроматический")
        e = L.eq([1, 0, 2, 0, 4, 50, 717, 0, 1, 3, 16000, 717, 0, 1, 1, 350, 724, 512] + [0] * 35)
        self.assertEqual([(f["type"], f["f0"], f["gain_db"]) for f in e["filters"]],
                         [("lowpass", 16000, 0.0), ("lowshelf", 350, 2.0)])


if __name__ == "__main__":
    unittest.main()
