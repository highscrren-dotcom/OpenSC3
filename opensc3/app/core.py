"""Ядро глазами окна: одна дверь к SC3 (ACP), OBS, PipeWire и hotplug. Бэкенд зовёт только этот протокол;
тесты и `--fake` подставляют подделку (`fake.py`), настоящее ядро — `RealCore`.

Все методы блокирующие и вызываются только из рабочих потоков бэкенда (backend.py), не из потока интерфейса.
Модули ядра импортируются лениво: окно и подделка работают и там, где части ядра нет.
"""
from __future__ import annotations

from typing import Any, Protocol

from opensc3.model import Link, Live, Sc3State
from opensc3.protocol import Sc3Busy  # чистый модуль без зависимостей

LIVE_TIMEOUT = 1.0     # obs.live_status: дольше секунды не ждём
ACP_MIN_INTERVAL = 5.0  # AcpGuard: набор чтений не чаще раза в 5 с (правило 4)
SC3_BUSY = Sc3Busy.TEXT  # тот же текст печатает и CLI


class OpenFailed(Exception):
    """SC3 не открылся для опроса. `link` — FOREIGN/ERROR, если дело в самом устройстве (опрос — до
    переподключения); None — временно (занят другим процессом, нет прав): попробовать позже."""

    def __init__(self, note: str, link: Link | None = None) -> None:
        super().__init__(note)
        self.note, self.link = note, link


class Guard(Protocol):
    def check(self, live: Live) -> str: ...        # полный набор: не чаще раза в 5 с, отметка общая с CLI
    def mark(self) -> None: ...
    def check_poll(self, live: Live) -> str: ...   # лёгкий опрос: не больше одного чтения за 0,5 с
    def mark_poll(self) -> None: ...


class Watcher(Protocol):
    def fileno(self) -> int: ...
    def poll(self) -> bool: ...


class Meter(Protocol):
    def start(self) -> None: ...
    def stop(self) -> None: ...
    def peaks(self) -> tuple[float | None, float | None]: ...


class Session(Protocol):
    """SC3, открытый для лёгкого опроса (решение 9): verify() уже пройден, интерфейс держится до close()."""

    def read(self, ctrl: int) -> bytes | None: ...   # одно чтение ACP (с повторами внутри Sc3); None — не ответил
    def close(self) -> None: ...


class Core(Protocol):
    continuous_polling: bool  # guard.CONTINUOUS_POLLING: пока False — SC3 читается только по событию

    def guard(self) -> Guard: ...
    def probe(self) -> tuple[Link, str | None]: ...
    def watcher(self) -> Watcher: ...
    def read_state(self, now: float) -> Sc3State: ...          # открыть SC3, один набор чтений, закрыть
    def open_sc3(self) -> Session: ...                         # для опроса; OpenFailed — не вышло
    def live_status(self) -> tuple[Live, float | None]: ...
    def find_sc3(self) -> Any | None: ...                      # узлы SC3 в PipeWire (pipewire.Sc3Nodes)
    def get_mute(self, nodes: Any) -> bool | None: ...         # mute источника SC3 (голос в ПК)
    def set_mute(self, nodes: Any, muted: bool) -> None: ...
    def meter(self, nodes: Any) -> Meter: ...


def source_id(nodes: Any) -> int:
    """Id источника SC3 (то, что SC3 отдаёт в ПК) из `pipewire.Sc3Nodes`."""
    return nodes.source_id


class RealCore:
    """Настоящее ядро: opensc3.{device,reader,guard,obs,pipewire,hotplug}."""

    def __init__(self) -> None:
        from opensc3 import guard
        self.continuous_polling = guard.CONTINUOUS_POLLING

    def guard(self) -> Guard:
        from opensc3.guard import AcpGuard, default_stamp
        # Отметка общая с CLI: `sc3 state` и окно вместе не опросят SC3 чаще интервала.
        return AcpGuard(min_interval=ACP_MIN_INTERVAL, stamp=default_stamp())

    def probe(self) -> tuple[Link, str | None]:
        from opensc3 import hotplug
        return hotplug.probe()

    def watcher(self) -> Watcher:
        from opensc3 import hotplug
        return hotplug.Watcher()

    def read_state(self, now: float) -> Sc3State:
        from opensc3.device import Sc3
        from opensc3.reader import read_state
        with Sc3.open() as sc3:
            return read_state(sc3, now)

    def open_sc3(self) -> Session:
        from opensc3 import protocol as P
        from opensc3 import reader
        from opensc3.device import Sc3
        try:
            sc3 = Sc3.open()  # неудачный захват закрывает транспорт сам; занято — Sc3Busy с текстом SC3_BUSY
        except Sc3Busy:
            raise OpenFailed(SC3_BUSY) from None
        except P.ProtocolError as e:
            raise OpenFailed(str(e)) from None
        bad = reader.verify_link(sc3)
        if bad is not None:
            sc3.close()
            raise OpenFailed("сборка прошивки не V22 — SC3 не читаем" if bad is Link.FOREIGN
                             else "verify: SC3 не ответил", bad)
        return sc3  # Sc3.read(ctrl) и close() — ровно Session

    def live_status(self) -> tuple[Live, float | None]:
        from opensc3.obs import live_status
        return live_status(timeout=LIVE_TIMEOUT)

    def find_sc3(self) -> Any | None:
        from opensc3 import pipewire
        return pipewire.find_sc3()

    def get_mute(self, nodes: Any) -> bool | None:
        from opensc3 import pipewire
        return pipewire.get_mute(source_id(nodes))

    def set_mute(self, nodes: Any, muted: bool) -> None:
        from opensc3 import pipewire
        pipewire.set_mute(source_id(nodes), muted)

    def meter(self, nodes: Any) -> Meter:
        from opensc3 import pipewire
        return pipewire.LevelMeter(nodes)
