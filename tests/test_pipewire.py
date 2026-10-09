"""PipeWire без PipeWire: синтетический pw-dump, подделка `run` для wpctl и подделка pw-record для индикаторов.
⚠ Настоящий `wpctl set-mute` здесь не вызывается никогда — только подделка `run`."""
import json
import math
import subprocess
import sys
import time
import unittest
from unittest import mock

from opensc3 import pipewire as PW


def node(i, cls, name, device=None, **props):
    return {"id": i, "type": "PipeWire:Interface:Node",
            "info": {"props": {"media.class": cls, "node.name": name, "device.id": device, **props}}}


def device(i, vid, pid):
    return {"id": i, "type": "PipeWire:Interface:Device",
            "info": {"props": {"device.vendor.id": vid, "device.product.id": pid, "device.api": "alsa"}}}


DUMP = [
    {"id": 0, "type": "PipeWire:Interface:Core", "info": {}},
    device(10, "0x1234", "0x0001"),                    # чужая карта
    device(47, "0x3142", "0x0C33"),                    # SC3 (регистр шестнадцатеричных — любой)
    node(30, "Audio/Sink", "alsa_output.other", 10),
    node(38, "Audio/Sink", "alsa_output.sc3", 47),
    node(56, "Audio/Source", "alsa_input.sc3", 47),
    node(57, "Audio/Source", "alsa_input.sc3.second", 47),  # второй узел того же класса — берём первый
    node(90, "Stream/Input/Audio", "obs", None),
]


class Run:
    """Подделка subprocess.run: запоминает команды, отвечает заготовкой."""

    def __init__(self, stdout="", returncode=0, stderr="", exc=None):
        self.calls, self.stdout, self.rc, self.stderr, self.exc = [], stdout, returncode, stderr, exc

    def __call__(self, cmd, **kw):
        self.calls.append(cmd)
        if self.exc:
            raise self.exc
        return subprocess.CompletedProcess(cmd, self.rc, self.stdout, self.stderr)


class Nodes(unittest.TestCase):
    def test_parse_dump(self):
        n = PW.parse_dump(DUMP)
        self.assertEqual(n, PW.Sc3Nodes(56, "alsa_input.sc3", 38, "alsa_output.sc3"))

    def test_components_fallback_and_absent(self):
        only = [node(5, "Audio/Source", "x", 99, **{"alsa.components": "USB3142:0c33"})]
        self.assertEqual(PW.parse_dump(only), PW.Sc3Nodes(5, "x", None, None))
        self.assertIsNone(PW.parse_dump(DUMP[:2] + [DUMP[3]]))
        self.assertIsNone(PW.parse_dump([]))

    def test_find_sc3(self):
        run = Run(json.dumps(DUMP))
        self.assertEqual(PW.find_sc3(run).source_id, 56)
        self.assertEqual(run.calls, [["pw-dump"]])
        for bad in (Run("не json"), Run("", returncode=1), Run(exc=FileNotFoundError("pw-dump")),
                    Run(exc=subprocess.TimeoutExpired("pw-dump", 3)), Run("{}")):
            self.assertIsNone(PW.find_sc3(bad))


class Mute(unittest.TestCase):
    def test_get_mute(self):
        self.assertIs(PW.get_mute(56, Run("Volume: 1.00 [MUTED]\n")), True)
        run = Run("Volume: 0.80\n")
        self.assertIs(PW.get_mute(56, run), False)
        self.assertEqual(run.calls, [["wpctl", "get-volume", "56"]])
        self.assertIsNone(PW.get_mute(56, Run("", returncode=1, stderr="Object not found")))
        self.assertIsNone(PW.get_mute(56, Run(exc=FileNotFoundError("wpctl"))))

    def test_set_mute_fake_only(self):
        run = Run()
        PW.set_mute(56, True, run)
        PW.set_mute(56, False, run)
        self.assertEqual(run.calls, [["wpctl", "set-mute", "56", "1"], ["wpctl", "set-mute", "56", "0"]])
        with self.assertRaises(PW.PipeWireError):
            PW.set_mute(56, True, Run(returncode=1, stderr="Object not found"))

    def test_only_numeric_ids(self):
        for bad in ("@DEFAULT_AUDIO_SOURCE@", "56", None, 0, -1, True):
            run = Run()
            with self.assertRaises(PW.PipeWireError):
                PW.set_mute(bad, True, run)
            self.assertEqual(run.calls, [], bad)
            self.assertIsNone(PW.get_mute(bad, run))


# Подделка pw-record: пишет кадры f32 × 2 так же, как pw-record в режиме пиков.
CHILD = r"""
import struct, sys, time
mode = sys.argv[1]
if mode == "gone":
    sys.exit(1)  # как pw-record без SC3: «defined target not found»
out = sys.stdout.buffer
vals = {"half": (0.5, -0.25), "silence": (0.0, 0.0), "burst": (0.1, 0.1)}[mode]
for k in range(10_000):
    out.write(struct.pack("<ff", *vals)); out.flush()
    if mode == "burst" and k == 3:
        time.sleep(30)  # поток замолк (узел уснул)
    time.sleep(0.01)
"""


class Spawn:
    def __init__(self, modes):
        self.modes, self.procs, self.cmds = modes, [], []

    def __call__(self, cmd, **kw):
        self.cmds.append(cmd)
        mode = self.modes["out" if "stream.capture.sink = true" in cmd[-2] else "in"]
        p = subprocess.Popen([sys.executable, "-c", CHILD, mode], **kw)
        self.procs.append(p)
        return p


def wait_for(fn, limit=3.0):
    t = time.monotonic()
    while time.monotonic() - t < limit:
        v = fn()
        if v:
            return v
        time.sleep(0.02)
    return fn()


class Meter(unittest.TestCase):
    NODES = PW.Sc3Nodes(56, "alsa_input.sc3", 38, "alsa_output.sc3")

    def meter(self, modes, **kw):
        sp = Spawn(modes)
        m = PW.LevelMeter(self.NODES, spawn=sp, **kw)
        self.addCleanup(m.stop)
        return m, sp

    def test_command_is_passive_peak_stream(self):
        cmd = PW.record_cmd("alsa_output.sc3", sink=True)
        self.assertEqual(cmd[:3], ["stdbuf", "-o0", "pw-record"])
        self.assertEqual(cmd[cmd.index("--target") + 1], "alsa_output.sc3")
        self.assertEqual(cmd[cmd.index("--rate") + 1], "25")
        self.assertLessEqual(PW.RATE, 30)
        props = cmd[-2]
        for p in ("resample.peaks = true", "node.passive = true", "node.dont-fallback = true",
                  "node.dont-reconnect = true", "stream.capture.sink = true"):
            self.assertIn(p, props)
        self.assertEqual(cmd[-1], "-")  # только в канал, не в файл
        self.assertNotIn("stream.capture.sink", PW.record_cmd("alsa_input.sc3", sink=False)[-2])

    def test_peaks_and_missing_output(self):
        with mock.patch.object(PW, "RETRY", (0.05, 0.1)):
            m, sp = self.meter({"in": "half", "out": "gone"})
            m.start()
            to_pc = wait_for(lambda: m.peaks()[0])
            self.assertAlmostEqual(to_pc, 20 * math.log10(0.5), places=3)  # max |L|, |R|
            self.assertIsNone(m.peaks()[1])  # выход не поднялся — неизвестно, а не тишина
            self.assertTrue(wait_for(lambda: len([c for c in sp.cmds if "meter-out" in c[-2]]) >= 3))  # перезапуски
            m.stop()
        self.assertTrue(all(p.poll() is not None for p in sp.procs), "все pw-record остановлены")
        self.assertEqual(m.peaks(), (None, None))
        self.assertFalse(m.running)

    def test_silence_is_floor(self):
        m, _ = self.meter({"in": "silence", "out": "silence"})
        m.start()
        self.assertEqual(wait_for(lambda: None not in (p := m.peaks()) and p), (PW.FLOOR_DB, PW.FLOOR_DB))

    def test_stale_becomes_none(self):
        with mock.patch.object(PW, "STALE", 0.2):
            m, _ = self.meter({"in": "burst", "out": "gone"})
            m.start()
            self.assertIsNotNone(wait_for(lambda: m.peaks()[0]))
            time.sleep(0.4)
            self.assertIsNone(m.peaks()[0])

    def test_no_sc3_no_streams(self):
        sp = Spawn({})
        m = PW.LevelMeter(spawn=sp, find=lambda: None)
        m.start()
        self.assertEqual((m.peaks(), sp.cmds, m.running), ((None, None), [], False))
        m.stop()

    def test_to_db(self):
        self.assertEqual(PW.to_db(0.0), PW.FLOOR_DB)
        self.assertEqual(PW.to_db(1e-9), PW.FLOOR_DB)
        self.assertAlmostEqual(PW.to_db(1.0), 0.0)


if __name__ == "__main__":
    unittest.main()
