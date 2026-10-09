"""Запись в SC3 (этап 3, docs/WRITE.md) — единственное место, где собираются кадры с LEN > 0 (кроме имён 0x80).

Кадр записи — один параметр узла: `A5 5A <узел> 03 <idx> <int16 LE> 16`. Белый список — данные (`PARAMS`): узел,
индекс параметра, границы сырого значения, единицы. `check_frame` (protocol.py) сверяется с ним же — последний рубеж
перед USB, а запреты protocol.py (блоки системы с громкостью `0x07`, узел ползунка `0xB6`, `0x11`, `0xFB`–`0xFF`,
всё выше `0xB6`) действуют поверх него. Голоса и ELECTRIC (`0x83`–`0x8C`) не пишем: их всё равно перепишет кнопка.

`plan_write` — кадры и описание без отправки (сухой прогон). `apply` — отправка с защитами:
1. эфир OFF и AcpGuard (в эфире и при неизвестном эфире — ни одного кадра), затем verify() = V22;
2. типы узлов с устройства (`0x80`, индекс 0) совпадают с ожидаемыми — адреса не уехали;
3. снимок «до»: каждый затронутый узел читается; откат обязан быть возможен (исходные значения — в белом списке),
   а включённый фильтр EQ ни на одном шаге — ни записи, ни отката — не остаётся с частотой или Q, равными 0;
4. кадры записи — по одному, не чаще раза в 0,5 с, без повторов; перед каждым — снова эфир; после — подтверждение
   и чтение назад; не сошлось — откат всего записанного в обратном порядке и ошибка;
5. каждое действие — в журнал; `undo_writes` по журналу возвращает исходные значения последнего сеанса.
Запись живёт до отключения питания: полный сброс — выдернуть USB (вне эфира).
"""
from __future__ import annotations

import itertools
import json
import math
import os
import struct
import time
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, replace
from pathlib import Path

from . import protocol as P
from .guard import MIN_INTERVAL_FLOOR
from .layouts import EQ_TYPES
from .model import Live

WRITE_INTERVAL = 0.5  # не больше одного кадра записи за 0,5 с (та же нагрузка, что у лёгкого опроса, решение 9)
MAX_WRITES = 64       # кадров записи за сеанс; больше — ошибка в плане, а не профиль

# Узлы — по графу звука SDK (docs/WRITE.md, «Где что стоит»): в ПК идёт 0x82 → … → 0xA2 → 0xAC → 0xB0 → USB.
MIC_TRIM = 0xAC    # сухой голос в запись/USB — после ползунка (громкость ADC1 0x07); в наушники не идёт
LINE_TRIM = 0xAE   # «музыка» (Line In) в запись — догадка: в SDK этой ветки в USB нет, а у SC3 Line In в ПК есть
VOICE_EQ = 0xA2    # EQ сухого голоса, до ответвления в запись (0xA5 и DRC 0x9E по SDK — только монитор)
GATE = 0x82        # шумодав микрофона (экспандер) — первый в цепочке микрофона
GAIN_T, EQ_T, EXPANDER_T = 15, 4, 5
NODE_TYPES = {MIC_TRIM: GAIN_T, LINE_TRIM: GAIN_T, VOICE_EQ: EQ_T, GATE: EXPANDER_T}  # с устройства: 0x80, индекс 0
NODE_LEN = {GAIN_T: 3, EQ_T: 53, EXPANDER_T: 5}  # значений в ответе чтения: enable + параметры

Q12_ONE = 4096
TRIM_DB = (-20.0, 10.0)  # дальше 0xB0 добавляет +5 дБ, а лимитера до USB нет — выше +10 дБ пики срежутся
EQ_FREQ, EQ_Q = (20, 20000), (307, 8192)  # у включённого фильтра; 0 — только у выключенного (пустой слот)


class WriteError(P.ProtocolError):
    """Запись не прошла или не начата. `left` — что осталось записанным (откат не удался); пусто — всё вернули.
    `rolled` — откат уже сделан тем, кто бросил ошибку."""

    def __init__(self, msg: str, left: Sequence[Write] = (), rolled: bool = False):
        super().__init__(msg)
        self.left, self.rolled = list(left), rolled


class WriteRefused(Exception):
    """Эфир или правило 4: к SC3 сейчас нельзя. `done` — что успели записать до отказа (вернуть — после эфира)."""

    def __init__(self, msg: str, done: Sequence[Done] = ()):
        super().__init__(msg)
        self.done = list(done)


# -- единицы ----------------------------------------------------------------------------------------------

def _num(v) -> float:
    if isinstance(v, bool):
        raise TypeError("ждали число")
    x = float(v.replace(",", ".")) if isinstance(v, str) else float(v)
    if not math.isfinite(x):
        raise ValueError("ждали конечное число")
    return x


def _int(v) -> int:
    x = _num(v)
    if x != int(x):
        raise ValueError("ждали целое")
    return int(x)


def _on(v) -> int:
    if isinstance(v, bool):
        return int(v)
    t = str(v).strip().lower()
    if t in ("1", "on", "вкл", "да"):
        return 1
    if t in ("0", "off", "выкл", "нет"):
        return 0
    raise ValueError("ждали on/off")


def _eqtype(v) -> int:
    t = str(v).strip().lower()
    if t not in EQ_TYPES:
        raise ValueError(f"тип фильтра — один из: {', '.join(EQ_TYPES)}")
    return EQ_TYPES.index(t)


def q12(db: float) -> int:
    """дБ → усиление Q12 (4096 = 0 дБ)."""
    return round(Q12_ONE * 10 ** (db / 20))


def q12_db(raw: int) -> float:
    return -math.inf if raw <= 0 else 20 * math.log10(raw / Q12_ONE)


TO_RAW: dict[str, Callable[[object], int]] = {
    "gain": lambda v: q12(_num(v)),            # дБ → Q12
    "eqgain": lambda v: round(_num(v) * 256),  # дБ → Q8.8
    "cdb": lambda v: round(_num(v) * 100),     # дБ → сотые дБ
    "q": lambda v: round(_num(v) * 1024),      # Q → Q6.10
    "hz": _int, "ms": _int, "xratio": _int,
    "on": _on, "eqtype": _eqtype,
}


def _f(x: float, nd: int = 1, sign: bool = True) -> str:
    return (f"{x:+.{nd}f}" if sign else f"{x:.{nd}f}").replace(".", ",").replace("-", "−")


def human(unit: str, raw: int | None) -> str:
    """Сырое значение → для людей: «+1,0 дБ», «80 Гц», «Q 0,71», «вкл.»; None — «?»."""
    if raw is None:
        return "?"
    if unit == "gain":
        db = q12_db(raw)
        return "−∞ дБ" if db == -math.inf else f"{_f(db)} дБ"
    if unit in ("eqgain", "cdb"):
        return f"{_f(raw / (256 if unit == 'eqgain' else 100))} дБ"
    if unit == "q":
        return f"Q {_f(raw / 1024, 2, sign=False)}"
    if unit == "eqtype":
        return EQ_TYPES[raw] if 0 <= raw < len(EQ_TYPES) else f"тип {raw}"
    return {"hz": f"{raw} Гц", "ms": f"{raw} мс", "xratio": f"1:{raw} ниже порога",
            "on": "вкл." if raw else "выкл."}.get(unit, str(raw))


# -- белый список -----------------------------------------------------------------------------------------

@dataclass(frozen=True)
class Param:
    """Что можно писать: узел `addr`, индекс `idx` в кадре записи — он же место в ответе чтения `[enable, p1, …]`
    (0 — включение узла). `lo`/`hi` — границы сырого значения, включительно."""
    key: str
    addr: int
    idx: int
    lo: int
    hi: int
    unit: str
    text: str

    def fmt(self, raw: int | None) -> str:
        return human(self.unit, raw)


def _eq(prefix: str, addr: int, what: str) -> list[Param]:
    """10 фильтров EQ: индексы 3 + 5k … 7 + 5k — вкл., тип, частота, Q, усиление (SDK, Communication_Effect_EQ).
    Число фильтров (индекс 2) устройство считает само; предусиление (1) и включение всего EQ (0) не трогаем.
    Частота и Q могут быть 0 — так выглядит пустой слот, и откат должен уметь его вернуть; включённым такой
    фильтр не бывает (проверка плана `check_filters`)."""
    out = []
    for n in range(1, 11):
        i = 3 + 5 * (n - 1)
        out += [
            Param(f"{prefix}.{n}.on", addr, i, 0, 1, "on", f"{what}, фильтр {n}: вкл./выкл."),
            Param(f"{prefix}.{n}.type", addr, i + 1, 0, len(EQ_TYPES) - 1, "eqtype", f"{what}, фильтр {n}: тип"),
            Param(f"{prefix}.{n}.freq", addr, i + 2, 0, EQ_FREQ[1], "hz",
                  f"{what}, фильтр {n}: частота ({EQ_FREQ[0]}…{EQ_FREQ[1]}; 0 — пустой слот)"),
            Param(f"{prefix}.{n}.q", addr, i + 3, 0, EQ_Q[1], "q", f"{what}, фильтр {n}: Q (0,3…8; 0 — пустой слот)"),
            Param(f"{prefix}.{n}.gain", addr, i + 4, -3840, 3840, "eqgain", f"{what}, фильтр {n}: усиление (±15 дБ)"),
        ]
    return out


PARAMS: tuple[Param, ...] = (
    Param("mic.trim", MIC_TRIM, 2, q12(TRIM_DB[0]), q12(TRIM_DB[1]), "gain", "поправка MIC в ПК после ползунка"),
    Param("line.trim", LINE_TRIM, 2, q12(TRIM_DB[0]), q12(TRIM_DB[1]), "gain",
          "поправка LINE IN в ПК после ползунка (узел — догадка)"),
    *_eq("eq", VOICE_EQ, "EQ голоса"),
    Param("gate.on", GATE, 0, 0, 1, "on", "шумодав микрофона (экспандер): вкл./выкл."),
    Param("gate.threshold", GATE, 1, -8000, -2000, "cdb", "шумодав: порог"),
    Param("gate.ratio", GATE, 2, 1, 10, "xratio", "шумодав: степень ниже порога"),
    Param("gate.attack", GATE, 3, 1, 100, "ms", "шумодав: атака"),
    Param("gate.release", GATE, 4, 10, 2000, "ms", "шумодав: спад"),
)
BY_KEY = {p.key: p for p in PARAMS}
BY_SLOT = {(p.addr, p.idx): p for p in PARAMS}


def check_write_frame(f: bytes) -> None:
    """Для `check_frame`: кадр записи — ровно параметр из белого списка, LEN 3, значение в границах."""
    addr, ln, idx = f[2], f[3], f[4]
    p = BY_SLOT.get((addr, idx))
    if p is None:
        raise P.ProtocolError(f"запись {addr:#04x}[{idx}] не в белом списке")
    if ln != 3 or len(f) != 8:
        raise P.ProtocolError(f"запись {p.key}: LEN {ln}, а нужно 3")
    (v,) = struct.unpack("<h", f[5:7])
    if not p.lo <= v <= p.hi:
        raise P.ProtocolError(f"запись {p.key} = {v}: вне {p.lo}…{p.hi}")


def write_frame(p: Param, value: int) -> bytes:
    """Кадр записи одного параметра: `A5 5A <узел> 03 <idx> <int16 LE> 16` (через protocol.frame)."""
    if not p.lo <= value <= p.hi:
        raise WriteError(f"{p.key} = {value}: вне {p.lo}…{p.hi}")
    return P.frame(p.addr, bytes([p.idx]) + struct.pack("<h", value))


# -- план -------------------------------------------------------------------------------------------------

@dataclass(frozen=True)
class Write:
    """Один кадр записи. `before` — что было (снимок; None — неизвестно); `expect` — писать, только если сейчас так
    (откат по журналу: значение с тех пор не меняли)."""
    param: Param
    value: int
    before: int | None = None
    expect: int | None = None

    @property
    def frame(self) -> bytes:
        return write_frame(self.param, self.value)

    def hex(self) -> str:
        """Кадр записи для показа (сухой прогон)."""
        return self.frame.hex(" ")

    def undo(self) -> Write:
        if self.before is None:
            raise WriteError(f"{self.param.key}: исходное значение неизвестно — откатить нечем")
        return Write(self.param, self.before, before=self.value)

    def describe(self) -> str:
        p = self.param
        was = f"{p.fmt(self.before)} → " if self.before is not None else ""
        return f"{p.key:<14} {p.addr:#04x}[{p.idx:>2}]  {was + p.fmt(self.value):<24} {self.frame.hex(' ')}"


def target(key: str, value) -> Write:
    """Ключ белого списка и значение в единицах для людей → кадр записи. Чужое и вне границ — WriteError до USB."""
    p = BY_KEY.get(key)
    if p is None:
        raise WriteError(f"«{key}» писать нельзя: нет в белом списке (sc3 params)")
    try:
        raw = TO_RAW[p.unit](value)
    except (ValueError, TypeError, OverflowError) as e:
        raise WriteError(f"{key} = {value!r}: {e}") from None
    if not p.lo <= raw <= p.hi:
        raise WriteError(f"{key} = {value}: вне {p.fmt(p.lo)} … {p.fmt(p.hi)}")
    return Write(p, raw)


def current(p: Param, state: dict[int, Sequence[int]] | None) -> int | None:
    """Значение параметра в снимке {узел: [enable, p1, …]}; None — узла нет или он короче, чем нужно."""
    vals = (state or {}).get(p.addr)
    return vals[p.idx] if vals is not None and len(vals) > p.idx else None


def state_from_dump(dump: dict) -> dict[int, list[int]]:
    """Снимок из дампа `sc3 dump` (JSON): {узел: значения} — для сухого прогона без обращения к SC3."""
    return {int(a, 16): list(n["values"]) for a, n in (dump.get("nodes") or {}).items() if n.get("values")}


def _eq_slot(p: Param) -> int | None:
    """Номер фильтра EQ (0…9), к которому относится параметр, или None."""
    return (p.idx - 3) // 5 if NODE_TYPES.get(p.addr) == EQ_T and p.idx >= 3 else None


def _on_param(addr: int, slot: int) -> Param:
    return BY_SLOT[(addr, 3 + 5 * slot)]


def order(writes: Iterable[Write], state: dict[int, Sequence[int]] | None = None) -> tuple[list[Write], list[Write]]:
    """План по снимку: (что писать по порядку, что пропущено). Повторы ключа — последнее значение; «уже так» —
    вон; `expect` не сошёлся — в пропущенные. Узел за узлом в порядке первого упоминания; внутри узла выключения —
    первыми, включения — последними; фильтр EQ, который сейчас включён и меняется, на время правки выключается.
    Без снимка (сухой прогон) — только порядок, без «до» и без скобок выкл./вкл."""
    last: dict[str, Write] = {}
    for w in writes:
        last.pop(w.param.key, None)
        last[w.param.key] = w
    todo, skipped = [], []
    for w in last.values():
        now = current(w.param, state) if state is not None else None
        if state is not None and now is None:
            raise WriteError(f"{w.param.key}: узла {w.param.addr:#04x} нет в снимке — не пишу")
        if now is not None and now == w.value:
            continue
        if w.expect is not None and now is not None and now != w.expect:
            skipped.append(replace(w, before=now))
            continue
        todo.append(replace(w, before=now))
    if state is not None:  # скобки выкл./вкл. вокруг правки включённого фильтра
        keys = {w.param.key for w in todo}
        slots = {(w.param.addr, s) for w in todo if (s := _eq_slot(w.param)) is not None and w.param.unit != "on"}
        for addr, slot in sorted(slots):
            on = _on_param(addr, slot)
            if on.key not in keys and current(on, state) == 1:
                todo += [Write(on, 0, before=1), Write(on, 1, before=0)]
    out = []
    for addr in dict.fromkeys(w.param.addr for w in todo):
        ws = [w for w in todo if w.param.addr == addr]
        out += [w for w in ws if w.param.unit == "on" and w.value == 0]
        out += [w for w in ws if w.param.unit != "on"]
        out += [w for w in ws if w.param.unit == "on" and w.value != 0]
    return out, skipped


def check_undo(plan: Sequence[Write]) -> None:
    """Писать только то, что можно вернуть: исходное значение известно и само лежит в белом списке."""
    for w in plan:
        if w.before is None:
            raise WriteError(f"{w.param.key}: исходное значение неизвестно — без снимка не пишу")
        if not w.param.lo <= w.before <= w.param.hi:
            raise WriteError(f"{w.param.key}: исходное {w.before} вне белого списка — вернуть не смогу, не пишу")


def check_filters(plan: Sequence[Write], state: dict[int, Sequence[int]]) -> None:
    """Ни на одном шаге записи и отката включённый фильтр EQ не остаётся с частотой вне 20…20000 Гц или Q вне
    0,3…8: нули — только у пустого (выключенного) слота. Шаги проигрываются на копии снимка."""
    sim = {a: list(v) for a, v in state.items()}

    def step(w: Write) -> None:
        sim[w.param.addr][w.param.idx] = w.value
        slot = _eq_slot(w.param)
        if slot is None:
            return
        en, _t, f0, q, _g = sim[w.param.addr][3 + 5 * slot: 8 + 5 * slot]
        if en and not (EQ_FREQ[0] <= f0 <= EQ_FREQ[1] and EQ_Q[0] <= q <= EQ_Q[1]):
            raise WriteError(f"фильтр {slot + 1} узла {w.param.addr:#04x} включён с частотой {f0} и Q {q / 1024:.2f}"
                             f" после «{w.param.key}» — сначала частота и Q, потом включение; не пишу")

    for w in plan:
        step(w)
    for w in reversed(plan):
        step(w.undo())


@dataclass(frozen=True)
class Plan:
    writes: list[Write]   # по порядку; с «до», если был снимок
    skipped: list[Write]  # не пишем: значение с тех пор меняли (откат по журналу)
    targets: list[Write]  # что просили (apply пересчитает план по свежему снимку)

    def lines(self) -> list[str]:
        out = [w.describe() for w in self.writes]
        out += [f"{w.param.key:<14} пропуск: сейчас {w.param.fmt(w.before)}, а сеанс оставил "
                f"{w.param.fmt(w.expect)} — меняли с панели?" for w in self.skipped]
        return out


def plan_write(items: Iterable[tuple[str, object]] | Iterable[Write],
               state: dict[int, Sequence[int]] | None = None) -> Plan:
    """Сухой прогон: (ключ, значение) или готовые Write → план с кадрами. Ничего не шлёт. Со снимком — с «до»,
    без «уже так» и с проверками: откат возможен, включённый фильтр EQ всегда настоящий."""
    targets = [x if isinstance(x, Write) else target(*x) for x in items]
    for w in targets:  # готовые Write (откат по журналу) — тоже в границах белого списка, до первого кадра
        if not w.param.lo <= w.value <= w.param.hi:
            raise WriteError(f"{w.param.key} = {w.value}: вне {w.param.lo}…{w.param.hi} — не пишу")
    writes, skipped = order(targets, state)
    if len(writes) > MAX_WRITES:
        raise WriteError(f"кадров записи {len(writes)} > {MAX_WRITES} — это не профиль, а ошибка")
    if state is not None:
        check_undo(writes)
        check_filters(writes, state)
    return Plan(writes, skipped, targets)


# -- журнал -----------------------------------------------------------------------------------------------

_SESSIONS = itertools.count(1)


def default_journal() -> Path:
    base = os.environ.get("XDG_STATE_HOME") or str(Path.home() / ".local" / "state")
    return Path(base) / "opensc3" / "writes.jsonl"


class Journal:
    """Журнал записанного, строки JSON. На каждый кадр — «намерение» (`intent`, до отправки) и итог (`write` или
    `rollback`, с чтением назад); в конце удачного сеанса — `end`. `undoes` — сеанс, который этот сеанс отменяет
    (`sc3 undo`). Файл открывается на дозапись до первого кадра (`open`): не открылся — к SC3 не идём. Без файла —
    только в памяти."""

    def __init__(self, path: Path | None = None, what: str = "", undoes: str | None = None, clock=time.time):
        self.path, self.what, self.undoes, self.clock = path, what, undoes, clock
        self.entries: list[dict] = []
        self.session = time.strftime("%Y%m%d-%H%M%S") + f"-{os.getpid()}-{next(_SESSIONS)}"
        self.fh = None
        self.broken = ""  # почему файл перестал дописываться посреди сеанса (строки остаются в памяти)

    def open(self) -> None:
        if self.path is None or self.fh is not None:
            return
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.fh = self.path.open("a", encoding="utf-8")
        except OSError as e:
            raise WriteError(f"журнал {self.path} не открыть ({e}) — без журнала не пишу") from None

    def close(self) -> None:
        if self.fh is not None:
            self.fh.close()
            self.fh = None

    def intent(self, phase: str, w: Write) -> dict:
        """Перед кадром: что и поверх чего собираемся записать. Для кадров сеанса строка обязана лечь в файл —
        иначе WriteError до отправки; для отката — нет (откат важнее журнала)."""
        return self._put({"op": "intent", "phase": phase, "key": w.param.key, "addr": w.param.addr,
                          "idx": w.param.idx, "before": w.before, "value": w.value}, strict=phase == "write")

    def add(self, op: str, w: Write, ack: bool, back: int | None) -> dict:
        """Итог кадра: `op` write — кадр сеанса, rollback — кадр отката после сбоя."""
        return self._put({"op": op, "key": w.param.key, "addr": w.param.addr, "idx": w.param.idx,
                          "before": w.before, "value": w.value, "ack": ack, "readback": back, "ok": back == w.value})

    def end(self) -> dict:
        """Сеанс прошёл до конца: всё записано и сверено."""
        return self._put({"op": "end"})

    def _put(self, e: dict, strict: bool = False) -> dict:
        e = {"time": round(self.clock(), 3), "session": self.session, "what": self.what,
             **({"undoes": self.undoes} if self.undoes else {}), **e}
        self.entries.append(e)
        if self.fh is not None:
            try:
                self.fh.write(json.dumps(e, ensure_ascii=False) + "\n")
                self.fh.flush()
            except OSError as err:
                self.broken = str(err)
                if strict:
                    raise WriteError(f"журнал перестал дописываться ({err}) — дальше не пишу") from None
        return e


def last_session(path: Path) -> list[dict]:
    """Строки последнего сеанса записи из файла журнала (пусто — журнала нет). Удачный откат по журналу — тоже
    сеанс: повторный `sc3 undo` вернёт отменённое. Прерванный или сорвавшийся откат (нет строки `end`) — нет:
    вместо него возвращается сеанс, который он отменял, и повторный `sc3 undo` доделает начатое."""
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, ValueError):
        return []
    rows = []
    for ln in lines:  # битые строки (обрыв записи, правка руками) — мимо
        try:
            r = json.loads(ln)
        except ValueError:
            continue
        if isinstance(r, dict) and isinstance(r.get("session"), str):
            rows.append(r)
    sessions = [r["session"] for r in rows if r.get("op") in ("intent", "write")]
    session, seen = (sessions[-1] if sessions else None), set()
    while session is not None and session not in seen:
        seen.add(session)
        mine = [r for r in rows if r.get("session") == session]
        undoes = next((r["undoes"] for r in mine if r.get("undoes")), None)
        if undoes is None or any(r.get("op") == "end" for r in mine):
            return mine
        session = undoes
    return []


def undo_writes(entries: Sequence[dict]) -> list[Write]:
    """Сеанс из журнала → «вернуть как было»: каждому тронутому параметру — его исходное значение, если сейчас там
    то, что сеанс оставил (иначе меняли с панели — пропуск, решает `order` по снимку). Порядок — обратный.
    Намерение без итога или итог без чтения назад — считаем, что кадр дошёл (проверит `expect`); намерение и итог
    отката без чтения назад ничего не доказывают. Строки с чужими ключами и негодными числами — мимо; значения
    вне белого списка отвергнет `plan_write`."""
    first: dict[str, int] = {}
    final: dict[str, int] = {}
    for e in entries:
        if not isinstance(e, dict) or e.get("key") not in BY_KEY:
            continue
        try:
            op, key = e.get("op"), e["key"]
            if op in ("intent", "write") and e.get("phase", "write") == "write":
                if e.get("before") is not None:
                    first.setdefault(key, _whole(e["before"]))
                back = e.get("readback") if op == "write" else None
                final[key] = _whole(back if back is not None else e["value"])
            elif op == "rollback" and e.get("readback") is not None:
                final[key] = _whole(e["readback"])
        except (KeyError, TypeError, ValueError, OverflowError):
            continue
    return [Write(BY_KEY[k], first[k], expect=final[k]) for k in reversed(list(first))
            if k in final and final[k] != first[k]]


def _whole(v) -> int:
    """Целое из журнала: bool, дроби, Infinity и NaN — TypeError."""
    if isinstance(v, bool) or not isinstance(v, int):
        raise TypeError(f"не целое: {v!r}")
    return v


# -- отправка ---------------------------------------------------------------------------------------------

@dataclass(frozen=True)
class Done:
    write: Write
    ack: bool             # пришло подтверждение `<узел> 00 …`
    readback: int | None  # что прочиталось назад


@dataclass(frozen=True)
class Result:
    done: list[Done]      # записано и сверено
    skipped: list[Write]  # не писали: значение с тех пор меняли (откат по журналу); `before` — что там сейчас


class Pacer:
    """Не чаще одного кадра записи за `interval` (не меньше 0,5 с)."""

    def __init__(self, interval: float = WRITE_INTERVAL, clock=None, sleep=None):
        if not interval >= MIN_INTERVAL_FLOOR:  # `not >=` ловит и NaN
            raise ValueError(f"интервал записи {interval} < {MIN_INTERVAL_FLOOR} с")
        self.interval, self.clock, self.sleep = float(interval), clock or time.monotonic, sleep or time.sleep
        self.last: float | None = None

    def wait(self) -> None:
        if self.last is not None:
            left = self.interval - (self.clock() - self.last)
            if left > 0:
                self.sleep(left)
        self.last = self.clock()


def _send(sc3, frame: bytes) -> bool:
    """Один кадр записи, без повторов (повтор — уже второй кадр записи). True — пришло подтверждение."""
    sc3.t.set_output(frame)
    time.sleep(sc3.DELAY)
    try:
        r = sc3.t.get_input()
    except P.ProtocolError:
        return False
    return P.write_ack(r, frame[2])


def _readback(sc3, p: Param) -> int | None:
    vals = sc3.node(p.addr)
    return current(p, {p.addr: vals}) if vals is not None else None


def check_types(sc3, addrs: Iterable[int]) -> None:
    """Типы узлов с устройства (`0x80`, индекс 0) — те, что ждём: иначе адреса у этой сборки другие."""
    types = sc3.types()
    if types is None:
        raise WriteError("таблица типов узлов не прочиталась — не пишу")
    for a in sorted(set(addrs)):
        k, want = a - P.NODE_MIN, NODE_TYPES.get(a)
        got = types[k] if 0 <= k < len(types) else None
        if want is None or got != want:
            raise WriteError(f"узел {a:#04x}: тип {got}, ждали {want} — раскладка не та, не пишу")


def snapshot(sc3, addrs: Iterable[int]) -> dict[int, list[int]]:
    """Снимок «до»: каждый узел читается один раз; не прочитался или длина не та — WriteError."""
    state = {}
    for a in sorted(set(addrs)):
        vals = sc3.node(a)
        if vals is None:
            raise WriteError(f"узел {a:#04x} не прочитался — не пишу")
        want = NODE_LEN.get(NODE_TYPES.get(a, -1))
        if want is not None and len(vals) != want:
            raise WriteError(f"узел {a:#04x}: {len(vals)} значений, ждали {want} — не пишу")
        state[a] = vals
    return state


def apply(sc3, plan: Plan | Sequence[Write], *, live: Callable[[], Live], guard, journal: Journal | None = None,
          clock=None, sleep=None, interval: float = WRITE_INTERVAL) -> Result:
    """Записать с защитами (порядок — в описании модуля). `live` — свежий статус эфира: спрашивается после паузы,
    прямо перед каждым кадром. `guard` — AcpGuard (эфир и правило 4; отметка ставится в конце в любом случае).
    Журнал открывается до первого кадра; не открылся — WriteError, к SC3 не идём. Эфир посреди сеанса —
    WriteRefused без отката (в эфире кадров нет); не сошлось чтение назад или отказал журнал — откат и WriteError;
    любое другое исключение (Ctrl+C) — откат уже отправленного и то же исключение дальше."""
    pacer = Pacer(interval, clock, sleep)
    journal = journal if journal is not None else Journal()
    targets = plan.targets if isinstance(plan, Plan) else list(plan)
    plan_write(targets)  # границы белого списка — до эфира, журнала и USB
    if note := guard.check(live()):
        raise WriteRefused(note)
    journal.open()
    try:
        if not sc3.verified:
            sc3.verify()
        addrs = {w.param.addr for w in targets}
        check_types(sc3, addrs)
        fresh = plan_write(targets, snapshot(sc3, addrs))
        done: list[Done] = []
        sent: list[Write] = []  # ушли или могли уйти: откатываем всё это
        try:
            for w in fresh.writes:
                pacer.wait()
                if note := guard.check_live(live()):
                    raise WriteRefused(f"{note} — запись остановлена", done)
                journal.intent("write", w)
                sent.append(w)
                ack, back, err = _step(sc3, w, journal, "write")
                if back != w.value:
                    left = _rollback(sc3, sent, pacer, journal, live, guard)
                    raise WriteError(f"{w.param.key}: записал {w.param.fmt(w.value)}, прочитал "
                                     f"{w.param.fmt(back)}{err}{_left_text(left)}", left, rolled=True)
                done.append(Done(w, ack, back))
        except WriteRefused:
            raise
        except BaseException as e:  # журнал, Ctrl+C, сбой не транспорта: вернуть отправленное, потом — дальше
            if isinstance(e, WriteError) and e.rolled:
                raise
            left = _rollback(sc3, sent, pacer, journal, live, guard) if sent else []
            if isinstance(e, WriteError):
                raise WriteError(f"{e}{_left_text(left)}", left, rolled=True) from None
            raise
        journal.end()
        return Result(done, fresh.skipped)
    finally:
        journal.close()
        guard.mark()


def _left_text(left: Sequence[Write]) -> str:
    if not left:
        return "; всё записанное вернул"
    return (f"; вернуть не удалось: {', '.join(w.param.key for w in left)} — выдерни USB для полного сброса "
            "(вне эфира): запись не переживает питание")


def _step(sc3, w: Write, journal: Journal, op: str) -> tuple[bool, int | None, str]:
    """Кадр записи и чтение назад. Строка журнала пишется в любом случае — и при Ctrl+C (чтение назад = None)."""
    ack, back, err = False, None, ""
    try:
        ack = _send(sc3, w.frame)
        back = _readback(sc3, w.param)
    except P.ProtocolError as e:
        err = f" ({e})"
    finally:
        journal.add(op, w, ack, back)
    return ack, back, err


def _rollback(sc3, written: Sequence[Write], pacer: Pacer, journal: Journal, live, guard) -> list[Write]:
    """Вернуть записанное в обратном порядке. На первой неудаче (или если начался эфир) — стоп: следующие шаги
    отката проверены только от состояния после этого шага. Возвращает всё, что вернуть не удалось."""
    todo = list(reversed(written))
    for k, w in enumerate(todo):
        pacer.wait()
        if guard.check_live(live()):
            return todo[k:]
        u = w.undo()
        journal.intent("rollback", u)
        _ack, back, _err = _step(sc3, u, journal, "rollback")
        if back != u.value:
            return todo[k:]
    return []
