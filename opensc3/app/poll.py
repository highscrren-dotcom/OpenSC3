"""Лёгкий опрос SC3 окном (решение 9): что читать в очередном слоте, когда слот и как разобрать ответ.

Без Qt и без ввода-вывода — это решает и разбирает, а читает рабочий поток бэкенда (backend.ControlWorker).
Слот — одно чтение ACP раз в 0,5 с по сетке монотонных часов. В начале сессии — поправка MIC (`0xAC`: её меняют
только окно и CLI, в круге её нет), затем полный набор `reader.FULL_SET` — по одному чтению на слот, а не пачкой;
затем круг `reader.POLL_CYCLE` (Mic, голос, Mic, ELECTRIC, Mic, Line In). «Обновить» ставит в очередь то, чего в
круге нет (загрузку DSP): оно занимает ближайший слот, пачки нет. Разбор — функциями `reader`, результат — поля
`Sc3State` (`merge`).

Запись из окна (ручка-поправка MIC) занимает те же слоты: каждое обращение сеанса `write.apply` — чтение типов,
снимок, кадр, чтение назад — ждёт свой слот (`Sc3.pace`), а `WriteGuard` отдаёт apply правило слотов вместо
правила полных наборов (раз в 5 с).

Догадка «MUTE» (`MuteGuess`): аппаратный MUTE лишь обнуляет громкость канала, и одно чтение его не отличит от
«ползунок внизу» (docs/RESEARCH.md §14). Но MUTE обнуляет её скачком, а рука ведёт ползунок через промежуточные
ступени: громкость упала с ≥ 10 % до 0 между двумя соседними чтениями канала — вероятно, MUTE.
"""
from __future__ import annotations

import math
import struct
import time
from dataclasses import replace

from opensc3 import protocol as P
from opensc3 import reader as R
from opensc3.guard import POLL_INTERVAL
from opensc3.model import Channel, Live, Sc3State

MAX_FAILS = 3   # неудачи подряд → опрос выключен до переподключения SC3
# «Обновить» в опросе: чего нет в круге (0x02). Поправку MIC оно не перечитывает: её меняют только окно и CLI, а
# CLI, пока окно держит SC3, к нему не попадёт — поправка читается в начале сессии и после записи.
REFRESH = tuple(c for c in R.FULL_SET if c not in R.POLL_CYCLE and c != R.MIC_TRIM)
TRIM_STEP = 0.5   # шаг ручки-поправки, дБ (границы — write.TRIM_DB)
MUTE_DROP = 0.10  # с какого положения обнуление считается скачком MUTE, а не концом пути ползунка
MUTE_SLACK = 0.1  # запас на дрожание слотов


def cycle_gap(ctrl: int, cycle: tuple[int, ...] = R.POLL_CYCLE, interval: float = POLL_INTERVAL) -> float:
    """Наибольший промежуток между соседними чтениями `ctrl` в круге опроса, с."""
    pos = [i for i, c in enumerate(cycle) if c == ctrl]
    if not pos:
        raise ValueError(f"{ctrl:#04x} нет в круге опроса")
    n = len(cycle)
    return max((pos[(k + 1) % len(pos)] - p) % n or n for k, p in enumerate(pos)) * interval


# Соседние чтения канала не дальше этого — иначе скачок мог быть и рукой. Из круга: Mic — 1,1 с, Line In — 3,1 с.
MUTE_GAP = {c: cycle_gap(c) + MUTE_SLACK for c in (R.ADC1, R.LINE_IN)}


class MuteGuess:
    """Догадка «MUTE» по двум соседним чтениям одного канала. Без ввода-вывода, время — от вызывающего.

    - громкость упала с ≥ MUTE_DROP до 0 не дольше чем за `max_gap` → `muted=True, muted_guess=True`, колпачок
      остаётся на последнем ненулевом положении;
    - пока 0 — догадка держится; громкость вернулась (ровно к прежней — MUTE снят; к другой — это был ползунок) —
      обычное чтение;
    - плавный спуск, первое чтение, долгий перерыв — ползунок: `fader=0, muted=None`.
    Ноль — это `muted is None` из reader (сырая громкость 0), а не `fader == 0`: малое усиление Line In
    округляется до ступени 0, но MUTE это не он (`muted=False`).
    """

    def __init__(self, max_gap: float) -> None:
        self.max_gap = max_gap
        self.prev: float | None = None
        self.prev_at: float | None = None
        self.held: float | None = None   # положение колпачка до MUTE; None — догадки нет

    def feed(self, ch: Channel, now: float) -> Channel:
        prev, prev_at = self.prev, self.prev_at
        self.prev, self.prev_at = ch.fader, now
        if ch.fader is None:
            self.held = None
            return ch
        zero = ch.muted is None   # reader: сырая громкость 0 — MUTE или ползунок внизу
        if self.held is not None:
            if zero:
                return replace(ch, fader=self.held, muted=True, muted_guess=True)
            self.held = None
            return ch
        if zero and prev is not None and prev >= MUTE_DROP and 0 <= now - prev_at <= self.max_gap:
            self.held = prev
            return replace(ch, fader=prev, muted=True, muted_guess=True)
        return ch


class BadReply(ValueError):
    """Ответ пришёл, но разобрать его нельзя (короче раскладки) — считается неудачей чтения."""


class Plan:
    def __init__(self, full_set_first: bool = True, trim: bool = False) -> None:
        """`full_set_first` — сначала полный набор по одному чтению на слот; `trim` — поправку MIC первой (окно:
        без неё ручка неактивна), даже без полного набора — пока окно было скрыто, её мог поменять CLI."""
        start = list(R.FULL_SET) if full_set_first else []
        if trim:
            start = [R.MIC_TRIM] + [c for c in start if c != R.MIC_TRIM]
        self.queue: list[int] = start
        self.turn = 0
        self.mute = {ctrl: MuteGuess(gap) for ctrl, gap in MUTE_GAP.items()}

    def next(self) -> int:
        """Адрес для очередного слота."""
        if self.queue:
            return self.queue.pop(0)
        ctrl = R.POLL_CYCLE[self.turn % len(R.POLL_CYCLE)]
        self.turn += 1
        return ctrl

    def retry(self, ctrl: int) -> None:
        """Чтение из очереди не удалось — вернуть его в начало (круг просто пойдёт дальше)."""
        if ctrl not in R.POLL_CYCLE and ctrl not in self.queue:
            self.queue.insert(0, ctrl)

    def refresh(self) -> None:
        """«Обновить» в опросе: то, чего нет в круге, — в ближайший слот. Пока в очереди что-то есть (идёт полный
        набор, повтор) — ничего: эти чтения и так свежие. Пачки не бывает: очередь отдаёт одно чтение на слот."""
        if self.queue:
            return
        self.queue.extend(REFRESH)

    def parse(self, ctrl: int, body: bytes, now: float | None = None) -> dict:
        """Ответ → поля `Sc3State`, которые он обновляет. `now` — time.monotonic() чтения (для догадки MUTE)."""
        now = time.monotonic() if now is None else now
        try:
            if ctrl == R.ADC1:
                return {"mic": self.mute[ctrl].feed(R.mic_channel(body), now)}
            if ctrl == R.QUERY:
                return {"dsp_load": R.dsp_load(body)}
            values = P.node_values(body)
            if len(values) < R.NEED.get(ctrl, 1):
                raise BadReply(f"узел {ctrl:#04x}: {len(values)} значений")
            if ctrl == R.LINE_IN:
                return {"line_in": self.mute[ctrl].feed(R.line_in_channel(values), now)}
            if ctrl == R.AUTOTUNE:
                return {"electric_key": R.electric_key(values)}
            if ctrl == R.PITCH:
                return {"voice": R.voice(values)}
            if ctrl == R.MIC_TRIM:
                return {"mic_trim": R.mic_trim(values)}
        except (KeyError, IndexError, struct.error) as e:
            raise BadReply(f"{ctrl:#04x}: {e}") from None
        raise BadReply(f"{ctrl:#04x}: не из набора опроса")


def merge(st: Sc3State, update: dict) -> Sc3State:
    """Поля из чтения опроса (или итога записи) → новое `Sc3State`. Чтение `0x07` даёт канал Mic без поправки —
    прочитанная поправка остаётся; `mic_trim` — поправка MIC в дБ (None — неизвестна)."""
    update = dict(update)
    trim = update.pop("mic_trim", st.mic.trim_db)
    mic = update.pop("mic", st.mic)
    return replace(st, mic=replace(mic, trim_db=trim), **update)


def trim_step(db: float, lo: float, hi: float) -> float:
    """Значение ручки → ближайший шаг 0,5 дБ в границах [lo, hi]."""
    return min(max(round(db / TRIM_STEP) * TRIM_STEP, lo), hi)


class WriteGuard:
    """Гвард, который окно отдаёт `write.apply` вместо AcpGuard. Эфир — те же проверки AcpGuard (`check_live`; ON и
    UNKNOWN — отказ). Интервал — правило лёгкого опроса, а не полных наборов: перед сеансом слот должен быть
    свободен (`check_poll`), а каждое обращение внутри сеанса само ждёт свой слот и отмечает его (`Sc3.pace`).
    Отметку полного набора (`mark`) сеанс записи не ставит: полного набора не было, слоты уже отмечены."""

    def __init__(self, guard) -> None:
        self.guard = guard

    def check(self, live: Live) -> str:
        return self.guard.check_poll(live)

    def check_live(self, live: Live) -> str:
        return self.guard.check_live(live)

    def mark(self) -> None:
        pass


def next_slot(t0: float, k: int, now: float, last: float, interval: float = POLL_INTERVAL) -> tuple[int, float]:
    """После слота k: номер и время следующего — по сетке t0 + n·interval и не раньше last + interval
    (last — начало прошлого чтения). Опоздали — пропущенные слоты не догоняются пачкой."""
    n = max(k + 1, math.ceil((now - t0) / interval - 1e-9))
    return n, max(t0 + n * interval, last + interval)

