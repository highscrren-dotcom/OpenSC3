"""Подделка ядра для `--fake` и тестов: SC3, OBS и PipeWire без железа, без сети и без PipeWire.

Повторяет договор `core.Core` и поведение настоящих модулей там, где оно важно окну: гвард — настоящий
`sc3linux.guard.AcpGuard` (без файла-отметки), набор чтений даёт то же, что умеет `reader.read_state`
(ползунки Mic и Line In, Mute микрофона, ELECTRIC, «голос выкл.»; остальное — None), сессия опроса отдаёт тела
ответов в раскладке SC3 (их разбирает настоящий `reader`), hotplug — канал `os.pipe()` под QSocketNotifier.
Счётчики вызовов, моменты чтений и потоки — для тестов.
"""
from __future__ import annotations

import math
import os
import struct
import threading
import time
from dataclasses import dataclass

from sc3linux import reader as R
from sc3linux.model import Channel, Link, Live, Sc3State

from .core import SC3_BUSY, OpenFailed

# Сценарии `python3 -m sc3linux.app --fake <имя>`.
SCENARIOS = {
    "normal": "SC3 подключён, эфира нет",
    "muted": "микрофон заглушён в PipeWire",
    "hw-muted": "микрофон заглушён клавишей на корпусе",
    "onair": "первый набор чтений, затем эфир (данные заморожены)",
    "onair-muted": "как onair, микрофон заглушён в PipeWire",
    "unknown-live": "OBS запущена, но статус эфира не узнать",
    "disconnected": "SC3 нет на шине",
    "no-access": "SC3 есть, но нет прав на USB-узел",
    "foreign": "сборка прошивки не V22",
    "error": "чтения ACP не проходят",
}
ON_AIR_FOR = 1 * 3600 + 23 * 60 + 45  # «1:23:45» — как в макете


@dataclass(frozen=True)
class FakeNodes:
    """Как pipewire.Sc3Nodes."""
    source_id: int | None = 41                       # SC3 → ПК (голос)
    source_name: str | None = "alsa_input.fake-sc3"
    sink_id: int | None = 42                         # ПК → SC3 (наушники)
    sink_name: str | None = "alsa_output.fake-sc3"


class FakeWatcher:
    """Как hotplug.Watcher: fileno() для QSocketNotifier, poll() → было ли событие."""

    def __init__(self) -> None:
        self._r, self._w = os.pipe()
        os.set_blocking(self._r, False)

    def fileno(self) -> int:
        return self._r

    def poll(self) -> bool:
        try:
            return bool(os.read(self._r, 64))
        except BlockingIOError:
            return False

    def kick(self) -> None:
        os.write(self._w, b"!")

    def close(self) -> None:
        for fd in (self._r, self._w):
            try:
                os.close(fd)
            except OSError:
                pass


class FakeMeter:
    """Уровни «как голос»: слоги с паузами в ПК, ровная музыка из ПК. Детерминированы от времени."""

    def __init__(self, core: FakeCore) -> None:
        self.core = core
        self.running = False

    def start(self) -> None:
        self.running = True

    def stop(self) -> None:
        self.running = False

    def peaks(self) -> tuple[float | None, float | None]:
        if not self.running:
            return None, None
        t = time.monotonic()
        syllable = max(0.0, math.sin(t * 5.3)) * (0.6 + 0.4 * math.sin(t * 0.7))
        to_pc = -60.0 if self.core.pw_muted else -40.0 + 34.0 * syllable
        from_pc = -22.0 + 4.0 * math.sin(t * 1.9) + 2.0 * math.sin(t * 7.1)
        return to_pc, from_pc


def _node(*values: int) -> bytes:
    return b"\xff" + struct.pack(f"<{len(values)}h", *values)


class FakeSession:
    """SC3, открытый для опроса: тела ответов как у настоящего (синтетические числа, решение 5)."""

    def __init__(self, core: FakeCore) -> None:
        self.core = core
        self.closed = False

    def read(self, ctrl: int) -> bytes | None:
        core = self.core
        core.poll_reads.append((ctrl, time.monotonic(), threading.current_thread().name))
        if self.closed:
            raise AssertionError("чтение из закрытой сессии")
        if core.fail_reads > 0:
            core.fail_reads -= 1
            return None
        vol = 0 if core.hw_mute else core.mic_vol()   # MUTE на корпусе обнуляет громкость; флаг mute — всегда 0
        if ctrl == R.ADC1:
            return b"\xff" + struct.pack("<10H", 3, 0, vol, vol, 7, 0, 0, 0, 0, 1)
        if ctrl == R.QUERY:
            return b"\xff" + struct.pack("<HHBHH", 100, 258, 0, 300, 320)   # загрузка 0,86
        if ctrl == R.LINE_IN:
            return _node(1, 0, R.STEP * 16)                                   # ступень 16 из 31
        if ctrl == R.AUTOTUNE:
            return _node(1, ord("B"), ord("u"), 0)                          # буква SDK «B» — на панели «C»
        if ctrl == R.PITCH:
            return _node(0, -40)                                              # голос выкл. (высота от Elder)
        return None

    def close(self) -> None:
        if not self.closed:
            self.closed = True
            self.core.open_sessions -= 1


class FakeCore:
    continuous_polling = True

    def __init__(self, scenario: str = "normal", *, min_interval: float = 5.0, demo: bool = False) -> None:
        if scenario not in SCENARIOS:
            raise ValueError(f"нет сценария {scenario!r}; есть: {', '.join(SCENARIOS)}")
        self.scenario = scenario
        self.min_interval = min_interval
        self.link = {"disconnected": Link.DISCONNECTED, "no-access": Link.NO_ACCESS}.get(scenario, Link.CONNECTED)
        self.live = Live.UNKNOWN if scenario == "unknown-live" else Live.OFF
        self.live_since: float | None = None
        self.live_after_read = scenario in ("onair", "onair-muted")
        self.nodes: FakeNodes | None = None if scenario == "disconnected" else FakeNodes()
        self.pw_muted = scenario in ("muted", "onair-muted")
        self.hw_mute = scenario == "hw-muted"
        self.demo = demo           # --fake: ползунок Mic медленно ходит, чтобы было видно опрос
        self.busy = False          # интерфейс держит другой процесс
        self.fail_reads = 0        # столько следующих чтений опроса не ответят
        # для тестов
        self.reads = 0
        self.read_threads: list[str] = []
        self.live_calls = 0
        self.mute_calls: list[tuple[int, bool, str]] = []
        self.probes = 0
        self.watchers: list[FakeWatcher] = []
        self.poll_reads: list[tuple[int, float, str]] = []  # (адрес, time.monotonic(), поток)
        self.open_sessions = 0
        self.sessions_opened = 0

    def mic_vol(self) -> int:
        """Громкость ADC1 (ползунок Mic): 0,8 от верха; в показе — медленно ходит по ступеням."""
        if not self.demo:
            return round(0.8 * R.STEP * R.STEPS)
        step = round(R.STEPS * (0.62 + 0.25 * math.sin(time.monotonic() / 2.5)))
        return step * R.STEP

    # --- SC3 ------------------------------------------------------------------------------------------

    def guard(self):
        from sc3linux.guard import AcpGuard
        return AcpGuard(min_interval=self.min_interval)  # без stamp: тест и показ не трогают отметку CLI

    def probe(self) -> tuple[Link, str | None]:
        self.probes += 1
        return self.link, None

    def watcher(self) -> FakeWatcher:
        w = FakeWatcher()
        self.watchers.append(w)
        return w

    def plug(self, link: Link) -> None:
        """Тесты: SC3 подключили/отключили — событие hotplug."""
        self.link = link
        self.nodes = None if link is Link.DISCONNECTED else FakeNodes()
        for w in self.watchers:
            w.kick()

    def read_state(self, now: float) -> Sc3State:
        self.reads += 1
        self.read_threads.append(threading.current_thread().name)
        if self.live_after_read:
            self.live, self.live_since = Live.ON, time.time() - ON_AIR_FOR
        if self.scenario == "foreign":
            return Sc3State(link=Link.FOREIGN)
        if self.scenario == "error":
            return Sc3State(link=Link.ERROR, firmware="V22")
        return Sc3State(
            link=Link.CONNECTED,
            firmware="V22",
            dsp_load=0.86,
            read_at=now,
            # как настоящий reader: mute из чтения не узнать; «hw-muted» показывает догадку опроса
            mic=Channel(fader=0.8, muted=True, muted_guess=True) if self.scenario == "hw-muted" else Channel(0.8),
            line_in=Channel(fader=0.52),
            voice="",
            electric_key="C",
        )

    def open_sc3(self) -> FakeSession:
        if self.link is not Link.CONNECTED or self.busy:
            raise OpenFailed(SC3_BUSY if self.busy else f"SC3 {self.link.value}")
        if self.scenario in ("foreign", "error"):
            raise OpenFailed("сборка прошивки не V22 — SC3 не читаем" if self.scenario == "foreign"
                             else "verify: SC3 не ответил", Link.FOREIGN if self.scenario == "foreign" else Link.ERROR)
        if self.live_after_read:
            self.live, self.live_since = Live.ON, time.time() - ON_AIR_FOR
        self.open_sessions += 1
        self.sessions_opened += 1
        return FakeSession(self)

    # --- OBS ------------------------------------------------------------------------------------------

    def live_status(self) -> tuple[Live, float | None]:
        self.live_calls += 1
        return self.live, self.live_since

    # --- PipeWire -------------------------------------------------------------------------------------

    def find_sc3(self) -> FakeNodes | None:
        return self.nodes

    def get_mute(self, nodes: FakeNodes) -> bool | None:
        return self.pw_muted

    def set_mute(self, nodes: FakeNodes, muted: bool) -> None:
        self.mute_calls.append((nodes.source_id, muted, threading.current_thread().name))
        self.pw_muted = muted

    def meter(self, nodes: FakeNodes) -> FakeMeter:
        return FakeMeter(self)
