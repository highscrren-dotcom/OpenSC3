"""SC3 в PipeWire: узлы входа и выхода, mute входа, пиковые уровни. SC3 по ACP здесь не опрашивается вовсе.

Узлы ищутся по `pw-dump` (JSON): устройство ALSA с `device.vendor.id`/`device.product.id` = 3142:0c33 (серийник
20190808 общий для устройств MVsilicon — по нему нельзя), запасной признак — `alsa.components` = USB3142:0c33.

⚠ `set_mute` на узле входа SC3 — не чисто программный mute: у маршрута analog-input-mic есть аппаратный
выключатель (ALSA «Mic Capture Switch», Feature Unit 5), и WirePlumber ставит mute через него — это стандартный
запрос USB Audio Class к SC3 (не ACP). Вызывается только из окна (tests/test_safety.py), CLI его не зовёт.

Уровни — `LevelMeter`: два процесса `pw-record` в режиме пиков (`resample.peaks`, как индикаторы pavucontrol через
pipewire-pulse): 25 значений в секунду, звук никуда не пишется, ссылки пассивные — спящий узел не будят, формат
и частоту устройства не меняют, на другое устройство не переезжают (`node.dont-fallback`, `node.dont-reconnect`).
"""
from __future__ import annotations

import json
import math
import os
import struct
import subprocess
import threading
import time
from dataclasses import dataclass

VID, PID = 0x3142, 0x0C33
ALSA_COMPONENTS = "USB3142:0c33"
TIMEOUT = 3.0


class PipeWireError(Exception):
    pass


@dataclass(frozen=True)
class Sc3Nodes:
    """Узлы SC3 в PipeWire. Вход («в ПК») — Audio/Source, выход («из ПК», наушники) — Audio/Sink."""
    source_id: int | None
    source_name: str | None   # node.name — по нему цепляется LevelMeter (переживает переподключение)
    sink_id: int | None
    sink_name: str | None


def _hex(v) -> int | None:
    try:
        return int(str(v), 16)
    except ValueError:
        return None


def parse_dump(objects: list) -> Sc3Nodes | None:
    """Разбор вывода `pw-dump`. Несколько узлов одного класса (профиль pro-audio) — берётся первый по id."""
    devices = set()
    for o in objects:
        p = (o.get("info") or {}).get("props") or {}
        if o.get("type") == "PipeWire:Interface:Device" and \
                (_hex(p.get("device.vendor.id")), _hex(p.get("device.product.id"))) == (VID, PID):
            devices.add(o.get("id"))
    found: dict[str, tuple[int, str]] = {}
    for o in sorted((o for o in objects if o.get("type") == "PipeWire:Interface:Node"), key=lambda o: o.get("id", 0)):
        p = (o.get("info") or {}).get("props") or {}
        cls = p.get("media.class")
        if cls not in ("Audio/Source", "Audio/Sink") or cls in found:
            continue
        if p.get("device.id") in devices or p.get("alsa.components") == ALSA_COMPONENTS:
            found[cls] = (o["id"], p.get("node.name"))
    if not found:
        return None
    src, snk = found.get("Audio/Source", (None, None)), found.get("Audio/Sink", (None, None))
    return Sc3Nodes(source_id=src[0], source_name=src[1], sink_id=snk[0], sink_name=snk[1])


def find_sc3(run=subprocess.run) -> Sc3Nodes | None:
    """Узлы SC3 или None (нет SC3, нет PipeWire). ~60 мс — для событий, не для частого опроса."""
    try:
        r = run(["pw-dump"], capture_output=True, text=True, timeout=TIMEOUT, check=False)
        if r.returncode != 0:
            return None
        objects = json.loads(r.stdout)
    except (OSError, subprocess.SubprocessError, ValueError):
        return None
    return parse_dump(objects) if isinstance(objects, list) else None


def _node(node_id) -> str:
    """Только числовой id: «@DEFAULT_AUDIO_SOURCE@» и имена сюда не пролезут — mute не уйдёт не туда."""
    if isinstance(node_id, bool) or not isinstance(node_id, int) or node_id <= 0:
        raise PipeWireError(f"нужен числовой id узла, а не {node_id!r}")
    return str(node_id)


def get_mute(node_id, run=subprocess.run) -> bool | None:
    """mute узла по `wpctl get-volume` («Volume: 1.00 [MUTED]»); None — не узнать."""
    try:
        r = run(["wpctl", "get-volume", _node(node_id)], capture_output=True, text=True, timeout=TIMEOUT,
                check=False)
    except (OSError, subprocess.SubprocessError, PipeWireError):
        return None
    if r.returncode != 0 or not r.stdout.startswith("Volume:"):
        return None
    return "[MUTED]" in r.stdout


def set_mute(node_id, muted: bool, run=subprocess.run) -> None:
    """mute узла через `wpctl set-mute`. Только из окна; ошибка — PipeWireError."""
    try:
        r = run(["wpctl", "set-mute", _node(node_id), "1" if muted else "0"], capture_output=True, text=True,
                timeout=TIMEOUT, check=False)
    except (OSError, subprocess.SubprocessError) as e:
        raise PipeWireError(f"wpctl set-mute: {e}") from None
    if r.returncode != 0:
        raise PipeWireError(f"wpctl set-mute {node_id}: {(r.stderr or r.stdout).strip() or r.returncode}")


# -- уровни ------------------------------------------------------------------------------------------------------

RATE = 25          # значений в секунду (как у pavucontrol); ≤ 30 Гц
FLOOR_DB = -100.0  # цифровая тишина и всё, что тише
STALE = 0.5        # нет свежих данных дольше — уровень неизвестен (None)
RETRY = (2.0, 30.0)  # перезапуск потока после выхода pw-record: от 2 с, удваиваясь до 30 с
FRAME = struct.Struct("<ff")  # f32 LE, два канала


def to_db(peak: float) -> float:
    return FLOOR_DB if peak <= 0 else max(FLOOR_DB, 20 * math.log10(peak))


def record_cmd(target: str, sink: bool, latency: str = "1024/48000") -> list[str]:
    """Команда пикового потока. `stdbuf -o0`: pw-record пишет через stdio, иначе 8 байт кадра копились бы
    в буфере 4 КиБ (~20 с). `node.latency` = обычный квант графа — поток не меняет квант устройства."""
    props = {
        "node.name": "opensc3-meter-" + ("out" if sink else "in"),
        "node.description": "OpenSC3: индикатор " + ("из ПК" if sink else "в ПК"),
        "resample.peaks": "true",       # ресемплер отдаёт пик |x| за период, а не звук
        "stream.monitor": "true",       # быстрый конвертер; в задержке соседей не учитывается
        "node.passive": "true",         # не будит спящий узел и не держит его
        "node.dont-fallback": "true",   # нет SC3 — не цепляться к устройству по умолчанию
        "node.dont-reconnect": "true",  # SC3 пропал — не переезжать, а выйти
        "node.latency": latency,
    }
    if sink:
        props["stream.capture.sink"] = "true"  # монитор выхода SC3
    spa = " ".join(f"{k} = {v if v == 'true' else json.dumps(v, ensure_ascii=False)}" for k, v in props.items())
    return ["stdbuf", "-o0", "pw-record", "--target", target, "--rate", str(RATE), "--channels", "2",
            "--format", "f32", "--raw", "-P", "{ " + spa + " }", "-"]


class _Stream:
    """Один пиковый поток в своём потоке Python: читает канал постоянно (pw-record не встанет на полном канале),
    при выходе процесса перезапускает его с паузой."""

    def __init__(self, cmd: list[str], spawn, clock):
        self.cmd, self.spawn, self.clock = cmd, spawn, clock
        self.lock = threading.Lock()
        self.stop_ev = threading.Event()
        self.proc = None
        self.peak: float | None = None   # максимум с прошлого peaks()
        self.last: float | None = None   # последнее значение
        self.at: float | None = None     # когда пришло
        self.thread = threading.Thread(target=self._run, name="sc3-meter", daemon=True)

    def _run(self) -> None:
        delay = RETRY[0]
        while not self.stop_ev.is_set():
            got = False
            try:
                self.proc = self.spawn(self.cmd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                       stderr=subprocess.DEVNULL, close_fds=True)
            except OSError:
                self.proc = None
            if self.proc is not None:
                buf = b""
                while not self.stop_ev.is_set():
                    try:
                        chunk = os.read(self.proc.stdout.fileno(), 4096)
                    except (OSError, ValueError):
                        chunk = b""
                    if not chunk:
                        break  # pw-record вышел: SC3 пропал, PipeWire перезапущен, нас остановили
                    buf += chunk
                    n = len(buf) // FRAME.size
                    if n:
                        v = max(max(abs(a), abs(b)) for a, b in FRAME.iter_unpack(buf[: n * FRAME.size]))
                        buf = buf[n * FRAME.size:]
                        if math.isfinite(v):
                            got = True
                            with self.lock:
                                self.peak = v if self.peak is None else max(self.peak, v)
                                self.last, self.at = v, self.clock()
                self._reap()
            delay = RETRY[0] if got else min(delay * 2, RETRY[1])
            self.stop_ev.wait(delay)

    def _reap(self) -> None:
        p, self.proc = self.proc, None
        if p is None:
            return
        try:
            if p.poll() is None:
                p.terminate()
            p.wait(timeout=2)
        except (OSError, subprocess.SubprocessError):
            try:
                p.kill()
            except OSError:
                pass
        if p.stdout:
            p.stdout.close()

    def start(self) -> None:
        self.thread.start()

    def stop(self) -> None:
        self.stop_ev.set()
        p = self.proc
        if p is not None:
            try:
                p.terminate()  # read() в потоке получит EOF
            except OSError:
                pass
        self.thread.join(timeout=3)
        self._reap()

    def take(self) -> float | None:
        with self.lock:
            if self.at is None or self.clock() - self.at > STALE:
                self.peak = None
                return None
            v = self.peak if self.peak is not None else self.last
            self.peak = None
        return to_db(v)


class LevelMeter:
    """Пиковые уровни SC3: (в ПК, из ПК) в dBFS, не чаще 25 раз в секунду, без блокировок.

    None — свежих данных нет: SC3 нет, узел спит (в выход SC3 ничего не играет — пассивный поток его не будит),
    поток ещё поднимается. Тишина — FLOOR_DB. Узлы ищутся при start(), если не даны; SC3 переподключили —
    поток сам поднимется заново (по node.name), но если узлы сменили имена — stop() и start().
    """

    def __init__(self, nodes: Sc3Nodes | None = None, *, spawn=subprocess.Popen, clock=time.monotonic,
                 find=find_sc3):
        self.nodes, self.spawn, self.clock, self.find = nodes, spawn, clock, find
        self._streams: dict[str, _Stream] = {}

    def start(self) -> None:
        if self._streams:
            return
        nodes = self.nodes or self.find()
        if nodes is None:
            return  # SC3 нет — peaks() отдаёт (None, None); позже start() ещё раз
        self.nodes = nodes
        for key, name, sink in (("in", nodes.source_name, False), ("out", nodes.sink_name, True)):
            if name:
                s = _Stream(record_cmd(name, sink), self.spawn, self.clock)
                self._streams[key] = s
                s.start()

    def stop(self) -> None:
        streams, self._streams = self._streams, {}
        for s in streams.values():
            s.stop()

    @property
    def running(self) -> bool:
        return bool(self._streams)

    def peaks(self) -> tuple[float | None, float | None]:
        """(в ПК, из ПК): максимум с прошлого вызова или последнее значение, dBFS; None — нет свежих данных."""
        return tuple(self._streams[k].take() if k in self._streams else None for k in ("in", "out"))
