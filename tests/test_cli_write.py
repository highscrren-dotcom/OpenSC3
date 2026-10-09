"""sc3 set / profile / undo / params: по умолчанию — сухой прогон без USB; --write — только вне эфира и через гвард."""
import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from opensc3 import cli
from opensc3 import write as W
from opensc3.device import Sc3
from opensc3.model import Live
from tests.fake import FakeTransport
from tests.test_write import NODES, TYPES

Sc3.DELAY = 0
OFF, ON, UNKNOWN = (Live.OFF, None), (Live.ON, 1.0), (Live.UNKNOWN, None)


class CliWrite(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        self.journal = self.dir / "writes.jsonl"
        self.stamps = iter(self.dir / f"acp-last-{k}" for k in range(100))  # каждый вызов — своя отметка гварда
        self.t = FakeTransport(nodes={a: list(v) for a, v in NODES.items()}, types=TYPES)
        self.opened = 0
        self.dump = self.dir / "dump.json"
        self.dump.write_text(json.dumps({"nodes": {f"{a:#04x}": {"values": v} for a, v in NODES.items()}}))

    def fake_open(self):
        self.opened += 1
        return Sc3(self.t)

    def run_cli(self, argv, live=OFF):
        out, err = io.StringIO(), io.StringIO()
        status = mock.Mock(return_value=live)
        with mock.patch("opensc3.obs.live_status", status), \
                mock.patch("opensc3.guard.default_stamp", side_effect=lambda: next(self.stamps)), \
                mock.patch.object(W, "default_journal", return_value=self.journal), \
                mock.patch.object(cli, "_open", self.fake_open), \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = cli.main(argv)
        return code, out.getvalue(), err.getvalue(), status

    def test_dry_run_is_default_and_touches_nothing(self):
        for argv in (["set", "mic.trim", "1"], ["set", "mic.trim", "1", "--dry-run"],
                     ["profile", "apply", "podcast"], ["profile", "show", "podcast"], ["params"], ["undo"]):
            code, out, _err, status = self.run_cli(argv, live=ON)
            self.assertEqual(code, 0, argv)
            self.assertEqual(self.opened, 0, argv)
            status.assert_not_called()
        self.assertEqual(self.t.sent, [])
        self.assertFalse(self.journal.exists())
        code, out, _err, _ = self.run_cli(["set", "mic.trim", "1"])
        self.assertIn(f"a5 5a {W.MIC_TRIM:02x} 03 02 f4 11 16", out)
        self.assertIn("сухой прогон", out)

    def test_dry_run_from_dump_shows_rollback(self):
        code, out, _err, _ = self.run_cli(["set", "mic.trim", "1", "--from", str(self.dump)])
        self.assertEqual(code, 0)
        self.assertIn("−0,0 дБ → +1,0 дБ", out)
        self.assertIn("откат", out)
        self.assertIn(f"a5 5a {W.MIC_TRIM:02x} 03 02 fa 0f 16", out)  # 4090 — как было
        code, out, _err, _ = self.run_cli(["profile", "diff", "podcast", "--from", str(self.dump)])
        self.assertEqual(code, 0)
        self.assertIn("отличается:", out)
        self.assertEqual(self.opened, 0)

    def test_outside_whitelist(self):
        for argv in (["set", "adc1.volume", "1"], ["set", "mic.trim", "40"], ["set", "eq.1.type", "allpass"]):
            code, _out, err, _ = self.run_cli(argv)
            self.assertEqual(code, 1, argv)
            self.assertIn("✗", err)
        self.assertEqual(self.opened, 0)

    def test_write_with_from_refused(self):
        with self.assertRaises(SystemExit), contextlib.redirect_stderr(io.StringIO()):
            cli.main(["set", "mic.trim", "1", "--write", "--from", str(self.dump)])
        with self.assertRaises(SystemExit), contextlib.redirect_stderr(io.StringIO()):
            cli.main(["set", "mic.trim", "1", "--write", "--dry-run"])

    def test_write_live_refuses_before_usb(self):
        for live in (ON, UNKNOWN):
            code, _out, err, _ = self.run_cli(["set", "mic.trim", "1", "--write"], live=live)
            self.assertEqual(code, 3)
            self.assertIn("к SC3 не обращаюсь", err)
        self.assertEqual((self.opened, self.t.sent), (0, []))

    def test_write_then_undo(self):
        code, out, err, _ = self.run_cli(["set", "mic.trim", "1", "--write"])
        self.assertEqual(code, 0, err)
        self.assertIn("✓ mic.trim", out)
        self.assertIn("вернуть как было: sc3 undo --write", out)
        self.assertEqual(self.t.nodes[W.MIC_TRIM][2], 4596)
        rows = [json.loads(x) for x in self.journal.read_text().splitlines()]
        self.assertEqual([(r["op"], r.get("key"), r.get("before"), r.get("value"), r.get("ok")) for r in rows],
                         [("intent", "mic.trim", 4090, 4596, None), ("write", "mic.trim", 4090, 4596, True),
                          ("end", None, None, None, None)])
        code, out, _err, _ = self.run_cli(["undo"])
        self.assertIn("если сейчас +1,0 дБ", out)
        self.assertEqual(self.t.nodes[W.MIC_TRIM][2], 4596)  # сухой прогон ничего не вернул
        code, out, err, _ = self.run_cli(["undo", "--write"])
        self.assertEqual(code, 0, err)
        self.assertEqual(self.t.nodes[W.MIC_TRIM][2], 4090)
        self.assertIn("снова применить отменённое: sc3 undo --write", out)  # после отката — не «вернуть как было»
        self.assertNotIn("вернуть как было", out)

    def test_interrupted_undo_resumes(self):
        with mock.patch("time.sleep"):
            self.run_cli(["profile", "apply", "podcast", "--write"])
            live = iter([OFF, OFF, OFF, OFF, ON])  # undo: CLI, apply, кадры 1 и 2 — OFF, перед 3-м — эфир
            out, err = io.StringIO(), io.StringIO()
            with mock.patch("opensc3.obs.live_status", side_effect=lambda: next(live)), \
                    mock.patch("opensc3.guard.default_stamp", return_value=self.dir / "u"), \
                    mock.patch.object(W, "default_journal", return_value=self.journal), \
                    mock.patch.object(cli, "_open", self.fake_open), \
                    contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                self.assertEqual(cli.main(["undo", "--write"]), 3)
            self.assertIn("sc3 undo --write", out.getvalue())
            code, _out, err, _ = self.run_cli(["undo", "--write"])  # совет CLI доделывает откат, а не накатывает
        self.assertEqual(code, 0, err)
        self.assertEqual(self.t.nodes, {a: list(v) for a, v in NODES.items()})

    def test_undo_reports_skip(self):
        self.run_cli(["set", "mic.trim", "2", "--write"])
        self.t.nodes[W.MIC_TRIM][2] = 4000  # сеанс оставил +2 дБ, а теперь там другое
        code, out, err, _ = self.run_cli(["undo", "--write"])
        self.assertEqual(code, 0, err)
        self.assertIn("mic.trim: пропуск — сейчас", out)
        self.assertIn("не трогаю", out)
        self.assertNotIn("всё уже так", out)
        self.assertEqual(self.t.nodes[W.MIC_TRIM][2], 4000)

    def test_unwritable_journal(self):
        with tempfile.TemporaryDirectory() as d:
            ro = Path(d) / "ro"
            ro.mkdir()
            ro.chmod(0o500)
            try:
                self.journal = ro / "sub" / "writes.jsonl"
                code, out, err, _ = self.run_cli(["set", "mic.trim", "2", "--write"])
            finally:
                ro.chmod(0o700)
        self.assertEqual(code, 1)
        self.assertIn("без журнала не пишу", err)
        self.assertNotIn("журнал:", out)
        self.assertEqual([f for f in self.t.sent if f[3] and f[2] != 0x80], [])

    def test_profile_write(self):
        with mock.patch("time.sleep"):  # 0,5 с между кадрами — в тесте не ждём
            code, _out, err, _ = self.run_cli(["profile", "apply", "podcast", "--write"])
        self.assertEqual(code, 0, err)
        code, out, _err, _ = self.run_cli(["profile", "diff", "podcast"])  # чтение с SC3 через гвард
        self.assertEqual(code, 0)
        self.assertIn("отличается: 0 из", out)

    def test_write_readback_mismatch_exit_code(self):
        self.t.stuck = {W.MIC_TRIM}
        code, _out, err, _ = self.run_cli(["set", "mic.trim", "1", "--write"])
        self.assertEqual(code, 1)
        self.assertIn("прочитал", err)

    def test_live_starts_during_write(self):
        live = iter([OFF, OFF, OFF, ON])  # CLI, apply до сеанса, перед 1-м кадром, перед 2-м — эфир
        out, err = io.StringIO(), io.StringIO()
        with mock.patch("opensc3.obs.live_status", side_effect=lambda: next(live)), \
                mock.patch("opensc3.guard.default_stamp", return_value=self.dir / "s"), \
                mock.patch.object(W, "default_journal", return_value=self.journal), \
                mock.patch.object(cli, "_open", self.fake_open), mock.patch("time.sleep"), \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = cli.main(["profile", "apply", "podcast", "--write"])
        self.assertEqual(code, 3)
        self.assertEqual(len([f for f in self.t.sent if f[3] and f[2] != 0x80]), 1)
        self.assertIn("записано до отказа", out.getvalue())
        self.assertIn("sc3 undo --write", out.getvalue())

if __name__ == "__main__":
    unittest.main()
