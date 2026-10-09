"""Сторож по исходникам: опасного в коде пакета быть не должно (docs/GOTCHAS.md, раздел «Устройство»)."""
import ast
import os
import pathlib
import re
import subprocess
import unittest

from opensc3 import protocol as P

ROOT = pathlib.Path(__file__).resolve().parent.parent
PKG = ROOT / "opensc3"
# Имя узла из таблицы прошивки Fifine: «<канал>:<Слово> <Слово>…» (решение 5). Синтетика тестов («1:Fake 7») не
# подходит. Журнал только дописывается — его прошлые записи не правим.
NODE_NAME = re.compile(r"\b\d{1,2}:[A-Z][a-z]+ [A-Z]")
NODE_NAME_EXEMPT = {"docs/JOURNAL.md"}
OUTSIDE_GIT = ("dumps", "refs", "firmware", ".git", ".venv", "venv", "__pycache__", ".ruff_cache")
FORBIDDEN = (
    "libusb_set_configuration", "libusb_reset_device", "libusb_set_interface_alt_setting",
    "libusb_detach_kernel_driver", "libusb_attach_kernel_driver", "set_configuration(",
    "0x0300", "0x0301", "0x0303",  # wValue SET/GET_REPORT(Feature) — вход в загрузчик
)
# PipeWire: громкость, устройство по умолчанию, профили, маршруты, параметры узлов — не наше дело (только mute)
PW_FORBIDDEN = ("set-volume", "set-default", "set-profile", "set-route", "set-param", "pactl", "pw-metadata ")
OBS_REQUESTS = {"GetStreamStatus", "GetRecordStatus"}


def sources():
    return sorted(f for f in PKG.rglob("*.py") if "__pycache__" not in f.parts)


def rel(f):
    return f.relative_to(PKG).as_posix()


def calls(tree, name):
    return [n for n in ast.walk(tree) if isinstance(n, ast.Call) and
            ((isinstance(n.func, ast.Name) and n.func.id == name) or
             (isinstance(n.func, ast.Attribute) and n.func.attr == name))]


class Source(unittest.TestCase):
    def test_no_dangerous_calls(self):
        for f in sources():
            text = f.read_text()
            for bad in FORBIDDEN:
                self.assertNotIn(bad, text, f"{bad} в {f.name}")

    def test_only_usb_module_talks_to_libusb(self):
        users = [f.name for f in sources() if "libusb_control_transfer" in f.read_text()]
        self.assertEqual(users, ["usb.py"])


def repo_files() -> list[str]:
    """Файлы, которые попадут в git: отслеживаемые и новые без игнорируемых. Без git — обход с теми же
    исключениями, что в .gitignore."""
    try:
        out = subprocess.run(["git", "-C", str(ROOT), "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
                             capture_output=True, check=True, timeout=10).stdout
        return sorted({p for p in out.decode().split("\0") if p})
    except (OSError, subprocess.SubprocessError):
        found = []
        for d, dirs, files in os.walk(ROOT):
            dirs[:] = [x for x in dirs if x not in OUTSIDE_GIT]
            found += [os.path.relpath(os.path.join(d, f), ROOT) for f in files]
        return sorted(found)


class Fifine(unittest.TestCase):
    """Решение 5: имён узлов из прошивки в репо нет — только адреса и смысл своими словами."""

    def test_no_firmware_node_names(self):
        files = repo_files()
        self.assertIn("opensc3/reader.py", files)
        hits = []
        for rel_path in files:
            if rel_path in NODE_NAME_EXEMPT or rel_path.split("/")[0] in OUTSIDE_GIT:
                continue
            try:
                text = (ROOT / rel_path).read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue  # картинки, шрифты
            hits += [f"{rel_path}:{n}: {m.group(0)}" for n, line in enumerate(text.splitlines(), 1)
                     for m in [NODE_NAME.search(line)] if m]
        self.assertEqual(hits, [])

    def test_pattern(self):
        self.assertTrue(NODE_NAME.search("узел «7" + ":Abc Def»"))  # склеено, чтобы сторож не нашёл сам себя
        self.assertFalse(NODE_NAME.search('f"1:Fake {i}" и 12:30 и 0x86'))


class Frames(unittest.TestCase):
    """Кадры записи (LEN > 0) не строятся нигде; единственное исключение — 0x80 с байтом-индексом."""

    def test_frame_literals_only_in_protocol(self):
        for f in sources():
            tree = ast.parse(f.read_text())
            for n in ast.walk(tree):
                if isinstance(n, (ast.List, ast.Tuple)) and len(n.elts) >= 4 and \
                        all(isinstance(e, ast.Constant) for e in n.elts[:2]) and \
                        [e.value for e in n.elts[:2]] == [0xA5, 0x5A]:
                    self.assertEqual(f.name, "protocol.py", f"кадр собирается в {rel(f)}:{n.lineno}")
                    ctrl, ln = n.elts[2], n.elts[3]
                    ok = isinstance(ln, ast.Constant) and (ln.value == 0 or (
                        ln.value == 1 and isinstance(ctrl, ast.Name) and ctrl.id == "NAMES"))
                    self.assertTrue(ok, f"кадр с LEN > 0 в {rel(f)}:{n.lineno}")
                if isinstance(n, ast.Constant) and isinstance(n.value, str) and \
                        re.match(r"(?i)\s*a5\s*5a", n.value):
                    self.fail(f"кадр строкой hex в {rel(f)}:{n.lineno}")

    def test_check_frame_rejects_every_write(self):
        for ctrl in range(256):
            f = bytes([0xA5, 0x5A, ctrl, 0x01, 0x01, 0x16])
            if ctrl == P.NAMES:
                continue
            with self.assertRaises(P.ProtocolError, msg=f"{ctrl:#04x}"):
                P.check_frame(f)

    def test_transport_checks_every_frame(self):
        tree = ast.parse((PKG / "usb.py").read_text())
        fn = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "set_output")
        self.assertTrue(calls(fn, "check_frame"), "set_output обязан звать check_frame")


class Cli(unittest.TestCase):
    def test_usb_opened_only_behind_live_check(self):
        """В cli.py SC3 открывается только в `_acp` (status/dump/descriptor) и в `cmd_state` — оба сначала
        спрашивают OBS и AcpGuard."""
        tree = ast.parse((PKG / "cli.py").read_text())
        for fn in (n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)):
            if calls(fn, "_open") or calls(fn, "open") and "Sc3" in ast.unparse(fn):
                if fn.name == "_open":
                    continue
                self.assertIn(fn.name, ("_acp", "cmd_state"), f"SC3 открывается в {fn.name}")
                self.assertTrue(calls(fn, "live_status") and calls(fn, "check"), fn.name)


class Obs(unittest.TestCase):
    """OBS: ровно GetStreamStatus и GetRecordStatus, без пакетов запросов, и только из obs.py."""

    def test_only_two_request_types(self):
        from opensc3 import obs
        self.assertEqual(set(obs.REQUESTS), OBS_REQUESTS)
        tree = ast.parse((PKG / "obs.py").read_text())
        loops = {}  # имя переменной цикла → по чему цикл
        for n in ast.walk(tree):
            if isinstance(n, (ast.For, ast.comprehension)):
                names = [t.id for t in ast.walk(n.target) if isinstance(t, ast.Name)]
                for name in names:
                    loops.setdefault(name, []).append(ast.unparse(n.iter))
        found = 0
        for n in ast.walk(tree):
            if isinstance(n, ast.Dict):
                for k, v in zip(n.keys, n.values):
                    if isinstance(k, ast.Constant) and k.value == "requestType":
                        found += 1
                        if isinstance(v, ast.Constant):
                            self.assertIn(v.value, OBS_REQUESTS)
                        else:
                            self.assertIsInstance(v, ast.Name, ast.unparse(v))
                            self.assertTrue(loops.get(v.id) and all(
                                it in ("REQUESTS", "enumerate(REQUESTS)") for it in loops[v.id]), ast.unparse(v))
                    if isinstance(k, ast.Constant) and k.value == "op":
                        self.assertIn(getattr(v, "value", None), (1, 6), "только Identify (1) и Request (6)")
            if isinstance(n, ast.Constant) and isinstance(n.value, str) and \
                    re.fullmatch(r"(Get|Set|Start|Stop|Toggle|Create|Remove|Save|Send|Trigger|Open|Pause|Resume|"
                                 r"Broadcast|Call|Press|Duplicate|Sleep|Offset)[A-Z]\w*", n.value):
                self.assertIn(n.value, OBS_REQUESTS, f"obs.py:{n.lineno}")
        self.assertGreaterEqual(found, 1)
        self.assertNotIn("requestBatch", (PKG / "obs.py").read_text())

    def test_obs_protocol_only_in_obs_module(self):
        users = [rel(f) for f in sources() if "requestType" in f.read_text() or "obswebsocket" in f.read_text()]
        self.assertEqual(users, ["obs.py"])


class PipeWire(unittest.TestCase):
    def test_set_mute_only_from_app(self):
        for f in sources():
            text = f.read_text()
            for c in calls(ast.parse(text), "set_mute"):
                self.assertEqual(rel(f).split("/")[0], "app", f"set_mute зовётся в {rel(f)}:{c.lineno}")
        self.assertNotIn("set_mute", (PKG / "cli.py").read_text())
        self.assertNotIn("set-mute", (PKG / "cli.py").read_text())

    def test_wpctl_set_mute_only_in_pipewire_module(self):
        users = [rel(f) for f in sources() if "set-mute" in f.read_text()]
        self.assertEqual(users, ["pipewire.py"])

    def test_no_volume_profile_default_changes(self):
        for f in sources():
            text = f.read_text()
            for bad in PW_FORBIDDEN:
                self.assertNotIn(bad, text, f"{bad} в {rel(f)}")

    def test_meter_writes_nowhere(self):
        from opensc3.pipewire import record_cmd
        for sink in (False, True):
            cmd = record_cmd("x", sink)
            self.assertEqual(cmd[-1], "-", "pw-record только в канал")
            self.assertIn("node.passive = true", cmd[-2])


if __name__ == "__main__":
    unittest.main()
