"""Подделка ядра для `--fake` и тестов: SC3, OBS и PipeWire без железа, без сети и без PipeWire.

Повторяет договор `core.Core` и поведение настоящих модулей там, где оно важно окну: гвард — настоящий
`opensc3.guard.AcpGuard` (без файла-отметки), набор чтений даёт то же, что умеет `reader.read_state`
(ползунки Mic и Line In, Mute микрофона, ELECTRIC, «голос выкл.», поправка MIC; остальное — None), сессия опроса —
настоящий `device.Sc3` поверх поддельного транспорта (`FakeAcp`): verify, чтения и запись `write.apply` идут тем же
кодом, что у настоящего, а тела ответов — в раскладке SC3 (их разбирает настоящий `reader`). Hotplug — канал
`os.pipe()` под QSocketNotifier. Настройки и журнал записи — в памяти (`MemorySettings`, `journal = None`):
`--fake` не трогает ни настройки окна владельца, ни его `writes.jsonl`. Счётчики вызовов, кадры, моменты чтений и
потоки — для тестов.
"""
from __future__ import annotations

import math
import os
import struct
import threading
import time
from dataclasses import dataclass, replace
from pathlib import Path

from opensc3 import protocol as P
from opensc3 import reader as R
from opensc3 import write as W
from opensc3.device import Sc3
from opensc3.model import Channel, Link, Live, Sc3State

from .core import SC3_BUSY, WRITE_KEY, OpenFailed

# Сценарии `python3 -m opensc3.app --fake <имя>`.
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
    "write": "запись в SC3 разрешена (предохранитель включён), поправка MIC +2,5 дБ",
    "write-onair": "как write, затем эфир: ручка-поправка под замком",
}
WRITE_SCENARIOS = ("write", "write-onair")   # предохранитель включён, поправка MIC уже +2,5 дБ
# Дескриптор интерфейса 4 (синтетический, минимальный): вендорская страница, без Report ID, вход и выход по 256
# байт — ровно то, что проверяет verify().
DESC4 = bytes.fromhex("0600ff0901a101150026ff00750896000109018102960001090191 02c0".replace(" ", ""))
TYPES = [30] * P.NODE_COUNT   # таблица типов узлов (0x80, индекс 0): синтетика, кроме узлов записи
for _addr, _type in W.NODE_TYPES.items():
    TYPES[_addr - P.NODE_MIN] = _type


def eq_node(*slots: tuple[int, int, int, int, int]) -> list[int]:
    """Узел EQ: включён, предусиление 0, число включённых, слоты (вкл., тип, f0, Q Q6.10, усиление Q8.8), пустые —
    нули. Числа синтетические (решение 5): похожи по виду на заводские, но не взяты с устройства."""
    flat = [x for sl in slots for x in sl]
    vals = [1, 0, sum(sl[0] for sl in slots)] + flat
    return vals + [0] * (53 - len(vals))


# «Как с завода» подделки: ФВЧ 60 Гц выкл., ФНЧ 15 кГц, полка НЧ 400 Гц +1 дБ; шумодав выкл. (как tests/test_write.py)
EQ_PLAIN = eq_node((0, 4, 60, 700, 0), (1, 3, 15000, 700, 0), (1, 1, 400, 720, 256))
GATE_PLAIN = [0, -5000, 2, 4, 90]
# Пресет голоса подделки (кнопка CHANGE VOICE): ФВЧ 90 Гц вкл., ФНЧ 11 кГц; шумодав вкл., −42 дБ, 1:3
EQ_VOICE = eq_node((1, 4, 90, 700, 0), (1, 3, 11000, 700, 0))
GATE_VOICE = [1, -4200, 3, 2, 100]
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


class FakeAcp:
    """Поддельный транспорт к интерфейсу 4 — как usb.LibusbTransport: кадр уходит (`set_output`, каждый проходит
    protocol.check_frame), ответ забирается (`get_input`). Ответы — в раскладке SC3 (синтетические числа, решение 5).
    Запись (LEN > 0) меняет узел и отвечает подтверждением `<узел> 00 …`, как в SDK; `core.trim_stuck` — запись
    подтверждается, а значение не меняется (чтение назад не сойдётся). Каждый кадр — в `core.acp`, запись — ещё и
    в `core.writes`. Состояние устройства живёт в подделке ядра (`core.sc3_nodes`) и переживает сессии."""

    def __init__(self, core: FakeCore) -> None:
        self.core = core
        self.last = bytes(P.REPORT)

    def claim(self) -> None:
        pass

    def report_descriptor(self) -> bytes:
        return DESC4

    def set_output(self, frame: bytes) -> None:
        P.check_frame(frame)  # настоящий транспорт делает то же
        core = self.core
        ctrl, ln = frame[2], frame[3]
        core.acp.append((ctrl, ln, time.monotonic(), threading.current_thread().name))
        if ln and ctrl != P.NAMES:                       # запись одного параметра: индекс = место в ответе чтения
            idx, (value,) = frame[4], struct.unpack("<h", frame[5:7])
            core.writes.append((ctrl, idx, value))
            if not core.trim_stuck:
                core.sc3_nodes[ctrl][idx] = value
            self.last = bytes([ctrl]) + bytes(P.REPORT - 1)
            return
        body = self._body(frame)
        if body is not None:  # иначе молчит — GET_REPORT отдаст прошлый ответ, как у настоящего
            self.last = (frame[:3] + bytes([len(body)]) + body + b"\x16").ljust(P.REPORT, b"\0")

    def _body(self, frame: bytes) -> bytes | None:
        core, ctrl = self.core, frame[2]
        vol = 0 if core.hw_mute else core.mic_vol()   # MUTE на корпусе обнуляет громкость; флаг mute — всегда 0
        if ctrl == 0x00:
            return P.V22_VERSION
        if ctrl == P.NAMES:
            if frame[4] != 0:
                return None                                                   # имена узлов окну не нужны
            return bytes([0, P.NODE_COUNT]) + struct.pack(f"<{P.NODE_COUNT}H", *TYPES)
        if ctrl == R.ADC1:
            return b"\xff" + struct.pack("<10H", 3, 0, vol, vol, 7, 0, 0, 0, 0, 1)
        if ctrl == R.QUERY:
            return b"\xff" + struct.pack("<HHBHH", 100, 258, 0, 300, 320)   # загрузка 0,86
        if ctrl == R.LINE_IN:
            return _node(1, 0, R.STEP * 16)                                   # ступень 16 из 31
        if ctrl == R.AUTOTUNE:
            return _node(*core.autotune)                                     # буква SDK «B» — на панели «C»
        if ctrl == R.PITCH:
            return _node(*core.pitch)                                        # голос выкл. (высота от Elder)
        if ctrl in core.sc3_nodes:
            return _node(*core.sc3_nodes[ctrl])
        return None

    def get_input(self) -> bytes:
        return self.last

    def close(self) -> None:
        pass


class FakeSession(Sc3):
    """SC3, открытый для опроса: настоящий `device.Sc3` поверх `FakeAcp`. `read` ещё и отмечает каждое чтение для
    тестов (`core.poll_reads`) и умеет не ответить (`core.fail_reads`, без кадра)."""

    def __init__(self, core: FakeCore) -> None:
        super().__init__(FakeAcp(core))
        self.core = core
        self.closed = False

    def read(self, ctrl: int) -> bytes | None:
        core = self.core
        if self.closed:
            raise AssertionError("чтение из закрытой сессии")
        if core.fail_reads > 0:
            core.fail_reads -= 1
            body = None
        else:
            body = super().read(ctrl)
        core.poll_reads.append((ctrl, time.monotonic(), threading.current_thread().name))
        if core.live_after_reads and len(core.poll_reads) >= core.live_after_reads and core.live is Live.OFF:
            core.live, core.live_since = Live.ON, time.time() - ON_AIR_FOR
        return body

    def close(self) -> None:
        if not self.closed:
            self.closed = True
            self.core.open_sessions -= 1
            super().close()


class MemorySettings:
    """Как QSettings, но в памяти: `--fake` и тесты не читают и не пишут настройки окна владельца."""

    def __init__(self, values: dict | None = None) -> None:
        self.values = dict(values or {})

    def value(self, key: str, default=None, type=None):  # `type` — как у QSettings
        v = self.values.get(key, default)
        return type(v) if type is not None and v is not None else v

    def setValue(self, key: str, value) -> None:
        self.values[key] = value


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
        # эфир начинается после стольких чтений опроса (write-onair: голос, нота и узлы уже прочитаны)
        self.live_after_reads = 5 if scenario == "write-onair" else 0
        self.nodes: FakeNodes | None = None if scenario == "disconnected" else FakeNodes()
        self.pw_muted = scenario in ("muted", "onair-muted")
        self.hw_mute = scenario == "hw-muted"
        self.demo = demo           # --fake: ползунок Mic медленно ходит, чтобы было видно опрос
        self.busy = False          # интерфейс держит другой процесс
        self.fail_reads = 0        # столько следующих чтений опроса не ответят
        # устройство: поправка MIC (узел 0xAC, Q12) — то, что пишет окно
        trim = W.q12(2.5) if scenario in WRITE_SCENARIOS else 4096
        self.sc3_nodes: dict[int, list[int]] = {W.MIC_TRIM: [1, 0, trim], W.VOICE_EQ: list(EQ_PLAIN),
                                                W.GATE: list(GATE_PLAIN)}
        self.pitch = [0, -40]                     # 0x85: голос выкл. (высота от Elder)
        self.autotune = [1, ord("B"), ord("u"), 0]  # 0x86: ELECTRIC, буква SDK «B» — на панели «C»
        self.trim_stuck = False    # запись подтверждается, а значение не меняется — чтение назад не сойдётся
        self.journal: Path | None = None   # журнал записи окна; None — только в памяти (не writes.jsonl владельца)
        self._settings = MemorySettings({WRITE_KEY: scenario in WRITE_SCENARIOS})
        # для тестов
        self.reads = 0
        self.read_threads: list[str] = []
        self.live_calls = 0
        self.mute_calls: list[tuple[int, bool, str]] = []
        self.probes = 0
        self.watchers: list[FakeWatcher] = []
        self.poll_reads: list[tuple[int, float, str]] = []  # (адрес, time.monotonic(), поток)
        self.acp: list[tuple[int, int, float, str]] = []     # каждый кадр ACP: (ctrl, LEN, time.monotonic(), поток)
        self.writes: list[tuple[int, int, int]] = []          # принятые кадры записи: (узел, индекс, значение)
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
        from opensc3.guard import AcpGuard
        return AcpGuard(min_interval=self.min_interval)  # без stamp: тест и показ не трогают отметку CLI

    def probe(self) -> tuple[Link, str | None]:
        self.probes += 1
        return self.link, None

    def watcher(self) -> FakeWatcher:
        w = FakeWatcher()
        self.watchers.append(w)
        return w

    def press_voice(self, voice: str) -> None:
        """Тесты: кнопка CHANGE VOICE — пресет переписывает узлы (docs/GOTCHAS.md), поправка — к 0 дБ."""
        self.pitch = [1, R.VOICE_PITCH[voice]]
        self.sc3_nodes.update({W.MIC_TRIM: [1, 0, 4096], W.VOICE_EQ: list(EQ_VOICE), W.GATE: list(GATE_VOICE)})

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
            mic=replace(Channel(fader=0.8, muted=True, muted_guess=True) if self.scenario == "hw-muted"
                        else Channel(0.8), trim_db=R.mic_trim(self.sc3_nodes[W.MIC_TRIM])),
            nodes={c: tuple(self.sc3_nodes[c]) for c in R.DSP_NODES},
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
        session = FakeSession(self)
        bad = R.verify_link(session)          # как RealCore.open_sc3: дескриптор и 0x00 (V22)
        if bad is not None:
            raise OpenFailed("verify: SC3 не ответил", bad)
        if self.live_after_read:
            self.live, self.live_since = Live.ON, time.time() - ON_AIR_FOR
        self.open_sessions += 1
        self.sessions_opened += 1
        return session

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

    # --- окно -----------------------------------------------------------------------------------------

    def settings(self) -> MemorySettings:
        return self._settings

    def journal_path(self) -> Path | None:
        return self.journal
