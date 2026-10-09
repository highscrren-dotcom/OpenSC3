"""Лёгкий опрос SC3 окном (решение 9): что читать в очередном слоте, когда слот и как разобрать ответ.

Без Qt и без ввода-вывода — это решает и разбирает, а читает рабочий поток бэкенда (backend.ControlWorker).
Слот — одно чтение ACP раз в 0,5 с по сетке монотонных часов. Сначала полный набор `reader.FULL_SET` — по одному
чтению на слот, а не пачкой; затем круг `reader.POLL_CYCLE` (Mic, голос, Mic, ELECTRIC, Mic, Line In). «Обновить»
ставит в очередь то, чего в круге нет (загрузку DSP): оно занимает ближайший слот, пачки нет. Разбор — функциями
`reader`, результат сразу идёт в `Sc3State`.

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
from opensc3.model import Channel

MAX_FAILS = 3   # неудачи подряд → опрос выключен до переподключения SC3
REFRESH = tuple(c for c in R.FULL_SET if c not in R.POLL_CYCLE)  # «Обновить» в опросе: чего нет в круге (0x02)
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
    def __init__(self, full_set_first: bool = True) -> None:
        self.queue: list[int] = list(R.FULL_SET) if full_set_first else []
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
        except (KeyError, IndexError, struct.error) as e:
            raise BadReply(f"{ctrl:#04x}: {e}") from None
        raise BadReply(f"{ctrl:#04x}: не из набора опроса")


def next_slot(t0: float, k: int, now: float, last: float, interval: float = POLL_INTERVAL) -> tuple[int, float]:
    """После слота k: номер и время следующего — по сетке t0 + n·interval и не раньше last + interval
    (last — начало прошлого чтения). Опоздали — пропущенные слоты не догоняются пачкой."""
    n = max(k + 1, math.ceil((now - t0) / interval - 1e-9))
    return n, max(t0 + n * interval, last + interval)

