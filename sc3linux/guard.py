"""Правило 4 в коде: когда можно обратиться к SC3 по ACP. Ничего не шлёт и не открывает — только решает.

Два правила, оба — никогда в эфире и при неизвестном эфире:
- **полный набор** чтений (`reader.read_state`, `sc3 status|dump|state`): `live_status()` → `check(live)` →
  (если «») набор → `mark()`; не чаще раза в `min_interval` (5 с), отметка общая для CLI и окна;
- **лёгкий опрос** окна (решение 9, docs/DECISIONS.md): `check_poll(live)` → одно чтение → `mark_poll()`;
  не больше одного чтения за `POLL_INTERVAL` (0,5 с) — та же нагрузка, что на стенде этапа 2. Отметка — в памяти:
  опрашивает только окно, и SC3 оно держит открытым (CLI в это время получит «занято»).
Причины отказа — по-русски, их показывает интерфейс (`AppState.acp_note`).

`stamp` — общий для процессов файл с моментом последнего набора (CLOCK_MONOTONIC, общий на всю загрузку):
без него `watch -n1 sc3 state` обходил бы интервал, ведь у каждого запуска CLI своя память.
"""
from __future__ import annotations

import os
import time
from pathlib import Path

from .model import Live

CONTINUOUS_POLLING = True   # решение 9 (docs/DECISIONS.md): стенд этапа 2 пройден — окну можно опрашивать SC3
MIN_INTERVAL_FLOOR = 0.5    # чаще раза в 0,5 с — никогда, даже после стенда
POLL_INTERVAL = 0.5         # лёгкий опрос: не больше одного чтения ACP за 0,5 с (решение 9)


def default_stamp() -> Path:
    """Файл отметки в каталоге сеанса ($XDG_RUNTIME_DIR), общий для CLI и окна."""
    base = os.environ.get("XDG_RUNTIME_DIR") or f"/tmp/sc3-linux-{os.getuid()}"
    return Path(base) / "sc3-linux" / "acp-last"


def _seconds(x: float) -> str:
    return f"{x:g}".replace(".", ",")


class AcpGuard:
    def __init__(self, min_interval: float = 5.0, clock=time.monotonic, stamp: Path | None = None,
                 poll_interval: float = POLL_INTERVAL):
        for name, v in (("min_interval", min_interval), ("poll_interval", poll_interval)):
            if not v >= MIN_INTERVAL_FLOOR:  # `not >=` ловит и NaN
                raise ValueError(f"{name} {v} < {MIN_INTERVAL_FLOOR} с: так часто SC3 опрашивать нельзя")
        self.min_interval, self.clock, self.stamp = float(min_interval), clock, stamp
        self.poll_interval = float(poll_interval)
        self._last: float | None = None
        self._last_poll: float | None = None

    def _last_mark(self) -> float | None:
        last = self._last
        if self.stamp is not None:
            try:
                t = float(self.stamp.read_text().strip())
            except (OSError, ValueError):
                t = None
            if t is not None and t <= self.clock() and (last is None or t > last):
                last = t  # отметка из будущего (другая загрузка, порча) — не в счёт
        return last

    @staticmethod
    def _live(live: Live) -> str:
        if live is Live.ON:
            return "идёт эфир или запись"
        if live is not Live.OFF:
            return "эфир неизвестен — OBS не отвечает"
        return ""

    def check(self, live: Live) -> str:
        """«» — набор чтений разрешён; иначе причина отказа."""
        if note := self._live(live):
            return note
        last = self._last_mark()
        if last is not None and self.clock() - last < self.min_interval:
            return f"рано: не чаще раза в {_seconds(self.min_interval)} с"
        return ""

    def mark(self) -> None:
        """Сразу после набора чтений — удачного или нет: устройство всё равно опрашивали."""
        self._last = self.clock()
        if self.stamp is not None:
            try:
                self.stamp.parent.mkdir(parents=True, exist_ok=True)
                self.stamp.write_text(f"{self._last:.3f}\n")
            except OSError:
                pass  # без файла остаётся отметка в памяти

    def check_poll(self, live: Live) -> str:
        """«» — одно чтение лёгкого опроса разрешено; иначе причина отказа (эфир важнее интервала)."""
        if note := self._live(live):
            return note
        if not CONTINUOUS_POLLING:
            return "постоянный опрос SC3 выключен"
        if self._last_poll is not None and self.clock() - self._last_poll < self.poll_interval:
            return f"рано: не больше одного чтения за {_seconds(self.poll_interval)} с"
        return ""

    def mark_poll(self) -> None:
        """Перед каждым чтением лёгкого опроса (и verify при открытии): слот занят, даже если чтение не удастся."""
        self._last_poll = self.clock()
