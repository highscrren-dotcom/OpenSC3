"""`sc3 state` и `sc3 live` без железа, OBS и PipeWire: всё внешнее подменено. Главное — отказ от ACP в эфире."""
import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from sc3linux import cli
from sc3linux.device import Sc3
from sc3linux.model import Link, Live
from sc3linux.pipewire import Sc3Nodes
from tests.fake import FakeTransport

Sc3.DELAY = 0


class State(unittest.TestCase):
    def run_state(self, live, link=Link.CONNECTED, nodes=None, muted=None):
        opened = []

        def fake_open():
            opened.append(1)
            return Sc3(FakeTransport())

        with tempfile.TemporaryDirectory() as d, \
                mock.patch("sc3linux.obs.live_status", return_value=live), \
                mock.patch("sc3linux.guard.default_stamp", return_value=Path(d) / "acp-last"), \
                mock.patch("sc3linux.hotplug.probe", return_value=(link, "/dev/bus/usb/003/007")), \
                mock.patch("sc3linux.pipewire.find_sc3", return_value=nodes), \
                mock.patch("sc3linux.pipewire.get_mute", return_value=muted), \
                mock.patch("sc3linux.pipewire.set_mute", side_effect=AssertionError("CLI не трогает mute")), \
                mock.patch.object(cli, "_open", fake_open):
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                code = cli.main(["state"])
        return json.loads(out.getvalue()), opened, code

    def test_live_on_refuses_acp(self):
        st, opened, code = self.run_state((Live.ON, 1000.0))
        self.assertEqual((opened, code), ([], 0))
        self.assertEqual((st["live"], st["live_since"], st["acp_note"]), ("on", 1000.0, "идёт эфир или запись"))
        self.assertIsNone(st["sc3"]["read_at"])

    def test_live_unknown_refuses_acp(self):
        st, opened, _ = self.run_state((Live.UNKNOWN, None))
        self.assertEqual(opened, [])
        self.assertEqual(st["acp_note"], "эфир неизвестен — OBS не отвечает")

    def test_off_reads_once_and_reports_pipewire(self):
        nodes = Sc3Nodes(56, "alsa_input.sc3", 38, "alsa_output.sc3")
        st, opened, code = self.run_state((Live.OFF, None), nodes=nodes, muted=False)
        self.assertEqual((opened, code, st["acp_note"]), ([1], 0, ""))
        self.assertEqual((st["sc3"]["link"], st["sc3"]["firmware"]), ("connected", "V22"))
        self.assertEqual(st["audio"], {"present": True, "to_pc_db": None, "from_pc_db": None, "pw_muted": False})
        self.assertEqual(st["pipewire"]["source_id"], 56)

    def test_no_access_and_disconnected(self):
        st, opened, _ = self.run_state((Live.OFF, None), link=Link.NO_ACCESS)
        self.assertEqual((opened, st["sc3"]["link"]), ([], "no_access"))
        self.assertIn("нет прав", st["acp_note"])
        st, opened, _ = self.run_state((Live.OFF, None), link=Link.DISCONNECTED)
        self.assertEqual((opened, st["sc3"]["link"], st["audio"]["present"]), ([], "disconnected", False))


class LiveCmd(unittest.TestCase):
    def test_live_output(self):
        for live, want in (((Live.OFF, None), "эфир: OFF"), ((Live.UNKNOWN, None), "эфир: UNKNOWN"),
                           ((Live.ON, 0.0), "эфир: ON — идёт эфир или запись, с ")):
            out = io.StringIO()
            with mock.patch("sc3linux.obs.live_status", return_value=live), contextlib.redirect_stdout(out):
                self.assertEqual(cli.main(["live"]), 0)
            self.assertTrue(out.getvalue().startswith(want), out.getvalue())


if __name__ == "__main__":
    unittest.main()
