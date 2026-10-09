"""Сторож по исходникам: опасного в коде пакета быть не должно (docs/GOTCHAS.md, раздел «Устройство»)."""
import ast
import os
import pathlib
import re
import subprocess
import unittest
import unittest.mock

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


def functions_of(tree):
    """Узел AST → имя ближайшей объемлющей функции (None — уровень модуля)."""
    owner = {}

    def walk(node, fn):
        for child in ast.iter_child_nodes(node):
            name = child.name if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)) else fn
            owner[child] = name
            walk(child, name)

    walk(tree, None)
    return owner


def parents_of(tree):
    return {child: node for node in ast.walk(tree) for child in ast.iter_child_nodes(node)}


def refs(tree, name):
    """Все упоминания имени: `name`, `x.name`, вызовы и передача без вызова (`f = W.apply`)."""
    return [n for n in ast.walk(tree) if (isinstance(n, ast.Name) and n.id == name) or
            (isinstance(n, ast.Attribute) and n.attr == name)]


# Жёсткие пределы записи — числа самого сторожа, не из write.py: расширить белый список шире них нельзя, не
# поправив и этот тест (docs/WRITE.md, «Белый список»).
HARD = {"eq_f0": (20, 20000), "eq_q": (307, 8192), "eq_gain": 3840, "trim": (410, 12953),  # −20…+10 дБ в Q12
        "gate_threshold": (-8000, -2000), "gate_ratio": (1, 10), "gate_ms": (1, 2000)}


# Узлы, в которые можно писать (docs/WRITE.md). Новый узел — новая категория записи: только по разрешению владельца
# (решение 4) и только вместе с правкой этой строки.
WRITE_NODES = {0x82: "шумодав микрофона", 0xA2: "EQ голоса", 0xAC: "поправка MIC", 0xAE: "поправка LINE IN"}
VOICE_NODES = range(0x83, 0x8D)  # голоса, автотюн (ELECTRIC), эхо, ревербераторы — их переписывает кнопка панели
HARD_NO = [*range(P.NODE_MIN), P.LINE_IN_FADER, *range(P.NODE_MAX + 1, 0x100)]  # блоки, 0x11, 0x80, 0xB6, > 0xB6


class Frames(unittest.TestCase):
    """Кадры собирает только `protocol.frame`; кадры с телом (LEN > 0) — только имена 0x80 (protocol.py) и запись
    одного параметра (write.py, по белому списку). `check_frame` пропускает запись только из белого списка, а блоки
    системы (0x01, 0x07 …), 0x11, 0xFB–0xFF, всё выше 0xB6 и ползунок 0xB6 — никогда, даже если список расширят."""

    def test_frame_literals_only_in_frame_builder(self):
        for f in sources():
            tree = ast.parse(f.read_text())
            owner = functions_of(tree)
            for n in ast.walk(tree):
                if isinstance(n, (ast.List, ast.Tuple)) and len(n.elts) >= 2 and \
                        all(isinstance(e, ast.Constant) for e in n.elts[:2]) and \
                        [e.value for e in n.elts[:2]] == [0xA5, 0x5A]:
                    self.assertEqual((rel(f), owner[n]), ("protocol.py", "frame"),
                                     f"кадр собирается в {rel(f)}:{n.lineno}")
                if isinstance(n, ast.Constant) and isinstance(n.value, bytes) and n.value[:2] == b"\xa5\x5a":
                    self.fail(f"кадр байтами в {rel(f)}:{n.lineno}")
                if isinstance(n, ast.Constant) and isinstance(n.value, str) and \
                        re.match(r"(?i)\s*a5\s*5a", n.value):
                    self.fail(f"кадр строкой hex в {rel(f)}:{n.lineno}")

    def test_bodies_only_for_names_and_write(self):
        """`frame(ctrl, тело)` — только имя узла (protocol.name_frame) и запись (write.write_frame)."""
        allowed = {("protocol.py", "name_frame"), ("write.py", "write_frame")}
        found = set()
        for f in sources():
            tree = ast.parse(f.read_text())
            owner = functions_of(tree)
            for c in calls(tree, "frame"):
                if len(c.args) > 1 or c.keywords:
                    self.assertIn((rel(f), owner[c]), allowed, f"кадр с телом в {rel(f)}:{c.lineno}")
                    found.add((rel(f), owner[c]))
        self.assertEqual(found, allowed)

    def test_write_path_only_in_write_module(self):
        """Кадры записи строит и шлёт только write.py; check_frame спрашивает его белый список. Упоминание считается
        и без вызова (`f = W.write_frame`), а `.frame` у Write вне write.py — уже обход `apply`."""
        allowed = {"write_frame": {"write.py"}, "check_write_frame": {"protocol.py", "write.py"},
                   "write_ack": {"protocol.py", "write.py"}, "_send": {"write.py"}, "_step": {"write.py"},
                   "_rollback": {"write.py"}, "set_output": {"device.py", "write.py", "usb.py"},
                   "_transact": {"device.py"}, "apply": {"write.py", "cli.py", WINDOW_WRITE[0]}}  # окно — Window
        for f in sources():
            tree = ast.parse(f.read_text())
            for name, where in allowed.items():
                for n in refs(tree, name):
                    self.assertIn(rel(f), where, f"{name} в {rel(f)}:{n.lineno}")
            if rel(f) not in ("write.py", "protocol.py"):
                for n in ast.walk(tree):
                    if isinstance(n, ast.Attribute) and n.attr == "frame":
                        self.fail(f"кадр записи (.frame) вне write.py: {rel(f)}:{n.lineno}")

    def test_send_sites(self):
        """set_output зовут только Sc3._transact (кадр чтения) и write._send; _transact — только с кадром чтения или
        имени, собранным тут же (`P.read_frame(…)`, `P.name_frame(…)`)."""
        for name, owner_ok in (("device.py", {"_transact"}), ("write.py", {"_send"})):
            tree = ast.parse((PKG / name).read_text())
            owner = functions_of(tree)
            for c in calls(tree, "set_output"):
                self.assertIn(owner[c], owner_ok, f"set_output в {name}:{c.lineno}")
        tree = ast.parse((PKG / "device.py").read_text())
        for c in calls(tree, "_transact"):
            arg = c.args[0] if c.args else None
            self.assertTrue(isinstance(arg, ast.Call) and isinstance(arg.func, ast.Attribute) and
                            arg.func.attr in ("read_frame", "name_frame"), f"_transact не с кадром чтения: {c.lineno}")

    def test_check_frame_accepts_only_whitelist(self):
        from opensc3 import write as W
        accepted = set()
        for ctrl in range(256):
            for idx in [*range(64), 0xFF]:
                for v in (-0x8000, -9000, -1, 0, 1, 2, 80, 4096, W.q12(10), 0x3FFF, 0x7FFF):
                    f = bytes([0xA5, 0x5A, ctrl, 3, idx]) + v.to_bytes(2, "little", signed=True) + b"\x16"
                    try:
                        P.check_frame(f)
                    except P.ProtocolError:
                        continue
                    p = W.BY_SLOT.get((ctrl, idx))
                    self.assertIsNotNone(p, f.hex(" "))
                    self.assertTrue(p.lo <= v <= p.hi, f.hex(" "))
                    accepted.add(ctrl)
        self.assertEqual(accepted, set(WRITE_NODES))
        for ctrl in range(256):  # любая другая длина тела, кроме имени узла 0x80, — отказ
            for ln in (1, 2, 4, 5, 7, 53 * 2 + 1):
                if ctrl == P.NAMES and ln == 1:
                    continue
                f = bytes([0xA5, 0x5A, ctrl, ln, 2]) + bytes(ln - 1) + b"\x16"
                with self.assertRaises(P.ProtocolError, msg=f"{ctrl:#04x} LEN={ln}"):
                    P.check_frame(f)

    def test_hard_bans_hold_even_if_whitelist_widens(self):
        from opensc3 import write as W
        wide = {(c, i): W.Param(f"x{c}.{i}", c, i, -0x8000, 0x7FFF, "hz", "")
                for c in HARD_NO for i in (0, 1, 2, 3, 0xFF)}
        with unittest.mock.patch.dict(W.BY_SLOT, wide):
            for (c, i) in wide:
                f = bytes([0xA5, 0x5A, c, 3, i, 0x01, 0x00, 0x16])
                with self.assertRaises(P.ProtocolError, msg=f.hex(" ")):
                    P.check_frame(f)
        for c in (0x01, 0x07, 0x11, 0x80, 0xB6, 0xB7, 0xC0, 0xFA, 0xFB, 0xFC, 0xFD, 0xFE, 0xFF):
            self.assertIn(c, HARD_NO)

    def test_whitelist_shape(self):
        from opensc3 import write as W
        self.assertEqual({p.addr for p in W.PARAMS}, set(WRITE_NODES))
        self.assertEqual(set(W.NODE_TYPES), set(WRITE_NODES))
        self.assertEqual(len(W.BY_SLOT), len(W.PARAMS))  # без повторов (узел, индекс)
        for p in W.PARAMS:
            self.assertTrue(P.NODE_MIN <= p.addr <= P.NODE_MAX and p.addr not in P.WRITE_NEVER, p.key)
            self.assertNotIn(p.addr, VOICE_NODES, p.key)
            self.assertTrue(-0x8000 <= p.lo <= p.hi <= 0x7FFF, p.key)
            t = W.NODE_TYPES[p.addr]
            if t == W.GAIN_T:  # только усиление (индекс 2), не mute и не выключение; −20…+10 дБ
                self.assertEqual(p.idx, 2, p.key)
                self.assertTrue(HARD["trim"][0] <= p.lo and p.hi <= HARD["trim"][1], p.key)
            elif t == W.EQ_T:  # только фильтры: число фильтров, предусиление и включение EQ — нет
                self.assertTrue(3 <= p.idx <= 52, p.key)
                field = (p.idx - 3) % 5  # вкл., тип, частота, Q, усиление
                limit = {0: (0, 1), 1: (0, 6), 2: (0, HARD["eq_f0"][1]), 3: (0, HARD["eq_q"][1]),
                         4: (-HARD["eq_gain"], HARD["eq_gain"])}[field]
                self.assertTrue(limit[0] <= p.lo and p.hi <= limit[1], p.key)
            elif t == W.EXPANDER_T:
                limit = {0: (0, 1), 1: HARD["gate_threshold"], 2: HARD["gate_ratio"], 3: HARD["gate_ms"],
                         4: HARD["gate_ms"]}[p.idx]
                self.assertTrue(limit[0] <= p.lo and p.hi <= limit[1], p.key)
            else:
                self.fail(f"{p.key}: тип узла {t} не предусмотрен")

    def test_enabled_filter_limits(self):
        """Включённый фильтр EQ — с частотой ≥ 20 Гц и Q ≥ 307 (0,3): нули и малые значения — только у выключенного."""
        from opensc3 import write as W
        self.assertTrue(W.EQ_FREQ[0] >= HARD["eq_f0"][0] and W.EQ_Q[0] >= HARD["eq_q"][0])
        eq = [1, 0, 0] + [0] * 50
        state = {W.VOICE_EQ: eq}
        for f0, q in ((HARD["eq_f0"][0] - 1, 1024), (1000, HARD["eq_q"][0] - 1), (0, 0)):
            items = [W.Write(W.BY_KEY["eq.5.freq"], f0), W.Write(W.BY_KEY["eq.5.q"], q), W.Write(W.BY_KEY["eq.5.on"], 1)]
            with self.assertRaises(W.WriteError, msg=(f0, q)):
                W.plan_write(items, state)
        W.plan_write([("eq.5.freq", HARD["eq_f0"][0]), ("eq.5.q", HARD["eq_q"][0] / 1024), ("eq.5.on", 1)], state)

    def test_transport_checks_every_frame(self):
        tree = ast.parse((PKG / "usb.py").read_text())
        fn = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "set_output")
        self.assertTrue(calls(fn, "check_frame"), "set_output обязан звать check_frame")

    def test_frame_builder_checks(self):
        tree = ast.parse((PKG / "protocol.py").read_text())
        fn = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "frame")
        self.assertTrue(calls(fn, "check_frame"), "frame обязан звать check_frame")


class Cli(unittest.TestCase):
    def test_usb_opened_only_behind_live_check(self):
        """В cli.py SC3 открывается только в `_acp` (status/dump/descriptor/profile diff), `cmd_state` и `_write`
        (запись) — все сначала спрашивают OBS и AcpGuard."""
        tree = ast.parse((PKG / "cli.py").read_text())
        for fn in (n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)):
            if calls(fn, "_open") or calls(fn, "open") and "Sc3" in ast.unparse(fn):
                if fn.name == "_open":
                    continue
                self.assertIn(fn.name, ("_acp", "cmd_state", "_write"), f"SC3 открывается в {fn.name}")
                self.assertTrue(calls(fn, "live_status") and calls(fn, "check"), fn.name)

    def test_writes_only_behind_write_flag(self):
        """Запись из CLI — только через `_write`, а его вызов лежит внутри `if a.write:` (в теле, не в else)."""
        tree = ast.parse((PKG / "cli.py").read_text())
        owner, parent = functions_of(tree), parents_of(tree)
        for n in refs(tree, "apply"):
            self.assertEqual(owner[n], "_write", f"write.apply вне _write: строка {n.lineno}")
        sites = calls(tree, "_write")
        self.assertGreaterEqual(len(sites), 3)
        for c in sites:
            node, ok = c, False
            while node in parent and not isinstance(node, ast.FunctionDef):
                up = parent[node]
                if isinstance(up, ast.If) and node in up.body and ast.unparse(up.test) == "a.write":
                    ok = True
                node = up
            self.assertTrue(ok, f"_write не под `if a.write:` в {owner[c]}:{c.lineno}")
        for n in refs(tree, "_write"):  # только прямой вызов: не передавать `_write` дальше как значение
            self.assertTrue(isinstance(parent[n], ast.Call) and parent[n].func is n, f"_write как значение: {n.lineno}")

    def test_write_session_asks_obs_fresh(self):
        """`_write` отдаёт apply функцию, которая каждый раз спрашивает OBS (`live_status()`), а не готовый ответ."""
        tree = ast.parse((PKG / "cli.py").read_text())
        fn = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "_write")
        (site,) = calls(fn, "apply")
        live = next(k.value for k in site.keywords if k.arg == "live")
        self.assertIsInstance(live, ast.Lambda)
        self.assertEqual(ast.unparse(live.body), "live_status()[0]")
        imported = {a.name for n in ast.walk(fn) if isinstance(n, ast.ImportFrom) and n.module == "obs"
                    for a in n.names}
        self.assertIn("live_status", imported)


# Окно пишет в SC3 ровно из одного места (docs/WRITE.md, «Сторож»): ручка MIC, профиль и возврат — всё через
# `_apply_plan`; его зовёт только `_run_job`, а того — только слот опроса `_slot`.
WINDOW_WRITE = ("app/backend.py", "ControlWorker", "_apply_plan")
WINDOW_CHAIN = {"_apply_plan": "_run_job", "_run_job": "_slot"}   # кто кого зовёт — и больше никто


def _method(cls: ast.ClassDef, name: str) -> ast.FunctionDef | None:
    return next((n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == name), None)


def _self_attr(n: ast.AST, attr: str | None = None) -> bool:
    """`self.<attr>` (любой attr, если None)."""
    return (isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name) and n.value.id == "self"
            and (attr is None or n.attr == attr))


def window_apply_problems(files: dict[str, str]) -> list[str]:
    """Нарушения правила «окно зовёт write.apply из одного места» по исходникам окна {путь в пакете: текст}:
    - `apply` упоминается только в `ControlWorker._apply_plan` (app/backend.py), ровно один прямой вызов;
    - `live=` — метод `self`, который каждый раз спрашивает OBS заново (`_live_status()` → `self._core.live_status()`),
      а не готовый ответ (`self._live`); `guard=` — `poll.WriteGuard(self._guard)`;
    - до вызова — проверка предохранителя (`_write_unwanted()` смотрит `self._write_enabled`);
    - `_apply_plan` зовёт только `_run_job`, а `_run_job` — только слот опроса `_slot`, прямыми вызовами."""
    path, cls_name, fn_name = WINDOW_WRITE
    problems = []
    for name, text in files.items():
        tree = ast.parse(text)
        owner, parent = functions_of(tree), parents_of(tree)
        for n in refs(tree, "apply"):
            if (name, owner[n]) != (path, fn_name):
                problems.append(f"write.apply вне {fn_name}: {name}:{n.lineno}")
            elif not (isinstance(parent[n], ast.Call) and parent[n].func is n):
                problems.append(f"write.apply как значение: {name}:{n.lineno}")
    tree = ast.parse(files.get(path, ""))
    cls = next((n for n in ast.walk(tree) if isinstance(n, ast.ClassDef) and n.name == cls_name), None)
    fn = _method(cls, fn_name) if cls is not None else None
    if fn is None:
        return [*problems, f"нет {cls_name}.{fn_name} в {path}"]
    sites = calls(fn, "apply")
    if len(sites) != 1:
        return [*problems, f"{fn_name}: вызовов apply {len(sites)}, а нужен один"]
    (site,) = sites
    kw = {k.arg: k.value for k in site.keywords}
    live = kw.get("live")
    method = _method(cls, live.attr) if _self_attr(live) else None
    status = _method(cls, "_live_status")
    if method is None or status is None:
        problems.append(f"{fn_name}: live= — не метод self ({ast.unparse(live) if live else 'нет'})")
    else:
        if not any(_self_attr(c.func, "_live_status") for c in calls(method, "_live_status")):
            problems.append(f"{live.attr}: не спрашивает self._live_status()")
        if any(_self_attr(n, "_live") for n in ast.walk(method)):
            problems.append(f"{live.attr}: смотрит готовый self._live вместо свежего ответа OBS")
        if not any(_self_attr(c.func.value, "_core") for c in calls(status, "live_status")
                   if isinstance(c.func, ast.Attribute)):
            problems.append("_live_status: не спрашивает self._core.live_status()")
    guard = kw.get("guard")
    if guard is None or ast.unparse(guard) != "poll.WriteGuard(self._guard)":
        problems.append(f"{fn_name}: guard= не poll.WriteGuard(self._guard)")
    fuse = [c for c in calls(fn, "_write_unwanted") if c.lineno < site.lineno]
    check = _method(cls, "_write_unwanted")
    if not fuse or check is None or not any(_self_attr(n, "_write_enabled") for n in ast.walk(check)):
        problems.append(f"{fn_name}: до apply нет проверки предохранителя (_write_unwanted → self._write_enabled)")
    owner, parent = functions_of(tree), parents_of(tree)
    for callee, caller in WINDOW_CHAIN.items():
        sites = refs(tree, callee)
        if not sites:
            problems.append(f"{callee} не зовётся вовсе")
        for n in sites:
            if owner[n] != caller or not (isinstance(parent[n], ast.Call) and parent[n].func is n):
                problems.append(f"{callee} зовётся не из {caller} (или передаётся как значение): строка {n.lineno}")
    return problems


def window_sources() -> dict[str, str]:
    return {rel(f): f.read_text() for f in sources() if rel(f).startswith("app/")}


class Window(unittest.TestCase):
    """Запись из окна — ровно одно место: `ControlWorker._apply_plan` (ручка MIC, профиль, возврат), через
    `write.apply` со свежим статусом OBS, гвардом слотов и предохранителем; путь к нему — только слот опроса.
    Всё остальное в окне `apply` не упоминает."""

    def test_window_writes_from_one_place(self):
        self.assertEqual(window_apply_problems(window_sources()), [])

    def test_violations_are_caught(self):
        """Сторож видит нарушение: вызов из другого места окна, готовый ответ об эфире, другой гвард, нет
        проверки предохранителя, `_apply_plan` или `_run_job` не из своего места."""
        files = window_sources()
        path = WINDOW_WRITE[0]
        text = files[path]
        site = "res = W.apply(session, plan, "
        self.assertEqual(text.count(site), 1)
        bad = {
            "другая функция бэкенда": text.replace(
                "    def refresh_poll(self) -> None:\n",
                "    def refresh_poll(self) -> None:\n        W.apply(self._session, [], live=self._live_before_acp,"
                " guard=poll.WriteGuard(self._guard))\n", 1),
            "второй вызов в той же функции": text.replace(site, "W.apply(session, plan, live=self._live_before_acp, "
                                                          "guard=poll.WriteGuard(self._guard))\n            " + site, 1),
            "готовый ответ об эфире": text.replace("live=self._live_before_acp", "live=self._cached_live", 1)
                                       .replace("    def _wait_slot(self) -> None:\n",
                                                "    def _cached_live(self):\n        return self._live\n\n"
                                                "    def _wait_slot(self) -> None:\n", 1),
            "гвард полных наборов не тот": text.replace("guard=poll.WriteGuard(self._guard)", "guard=self._guard", 1),
            "без предохранителя": text.replace("        if why := self._write_unwanted():\n            if trim is not None:",
                                               "        if False:\n            if trim is not None:", 1),
            "_apply_plan не из _run_job": text.replace("    def refresh_poll(self) -> None:\n",
                                                       "    def refresh_poll(self) -> None:\n        self._apply_plan(None, "
                                                       "\"x\")\n", 1),
            "_run_job не из слота": text.replace("    def refresh_poll(self) -> None:\n",
                                                 "    def refresh_poll(self) -> None:\n        self._run_job()\n", 1),
        }
        for what, mutated in bad.items():
            with self.subTest(what=what):
                self.assertNotEqual(mutated, text, "мутация не легла — поправь тест под исходник")
                self.assertTrue(window_apply_problems({**files, path: mutated}), what)
        elsewhere = {**files, "app/view.py": files["app/view.py"] + "\n\ndef oops(s, p):\n    return W.apply(s, p)\n"}
        self.assertTrue(window_apply_problems(elsewhere))


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
