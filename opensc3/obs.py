"""Идёт ли эфир или запись в OBS — для правила «Эфир» (CLAUDE.md, правило 3). Только два запроса на чтение.

obs-websocket v5 на 127.0.0.1; порт и пароль — из настроек самой OBS (как ~/dev/stream-style/tools/obsws.py),
в репо их нет. Спрашиваем ровно `GetStreamStatus` и `GetRecordStatus` (tests/test_safety.py следит), без подписки
на события. OBS не запущена → OFF; запущена, но ответа нет (сервер выключен, пароль не тот, таймаут) → UNKNOWN —
и с SC3 тогда обращаемся как в эфире. Библиотека `websockets` (python-websockets) импортируется внутри функции:
ядро без неё импортируется, а `live_status()` честно вернёт UNKNOWN.
"""
from __future__ import annotations

import base64
import hashlib
import json
import time
from pathlib import Path

from .model import Live

CONFIG = Path.home() / ".config/obs-studio/plugin_config/obs-websocket/config.json"
HOST = "127.0.0.1"
REQUESTS = ("GetStreamStatus", "GetRecordStatus")  # больше ничего OBS не шлём
PROC = Path("/proc")


class ObsError(Exception):
    pass


def obs_running(proc: Path = PROC) -> bool:
    """Есть ли процесс `obs` (comm; так же называется и во flatpak)."""
    try:
        entries = list(proc.iterdir())
    except OSError:
        return True  # не знаем — считаем, что запущена: дальше это даст UNKNOWN, а не OFF
    for d in entries:
        if not d.name.isdigit():
            continue
        try:
            if (d / "comm").read_text().strip() == "obs":
                return True
        except OSError:
            continue
    return False


def _auth(password: str, salt: str, challenge: str) -> str:
    secret = base64.b64encode(hashlib.sha256((password + salt).encode()).digest()).decode()
    return base64.b64encode(hashlib.sha256((secret + challenge).encode()).digest()).decode()


def _ask(url: str, password: str, timeout: float) -> dict[str, dict]:
    """Одно соединение: Hello → Identify (без событий) → два запроса. Ответы по requestType."""
    from websockets.sync.client import connect
    from websockets.typing import Subprotocol

    deadline = time.monotonic() + timeout

    def left() -> float:
        r = deadline - time.monotonic()
        if r <= 0:
            raise TimeoutError("OBS не ответила вовремя")
        return r

    def recv(ws) -> dict:
        msg = json.loads(ws.recv(timeout=left()))
        if not isinstance(msg, dict) or not isinstance(msg.get("d"), dict):
            raise ObsError(f"непонятное сообщение: {str(msg)[:80]}")
        return msg

    with connect(url, subprotocols=[Subprotocol("obswebsocket.json")], open_timeout=timeout, close_timeout=0.2,
                 proxy=None, compression=None, max_size=2**20) as ws:
        hello = recv(ws)
        if hello.get("op") != 0:
            raise ObsError("нет Hello")
        ident: dict = {"rpcVersion": 1, "eventSubscriptions": 0}
        a = hello["d"].get("authentication")
        if a:
            ident["authentication"] = _auth(password, a["salt"], a["challenge"])
        ws.send(json.dumps({"op": 1, "d": ident}))
        if recv(ws).get("op") != 2:
            raise ObsError("не пустили (пароль?)")
        for i, rtype in enumerate(REQUESTS):
            ws.send(json.dumps({"op": 6, "d": {"requestType": rtype, "requestId": str(i), "requestData": {}}}))
        out: dict[str, dict] = {}
        while len(out) < len(REQUESTS):
            msg = recv(ws)
            d = msg["d"]
            if msg.get("op") != 7 or d.get("requestType") not in REQUESTS:
                continue  # события не заказывали; чужое — пропускаем
            if not d.get("requestStatus", {}).get("result"):
                raise ObsError(f"{d.get('requestType')}: {d.get('requestStatus')}")
            out[d["requestType"]] = d.get("responseData") or {}
        return out


def interpret(answers: dict[str, dict], now: float) -> tuple[Live, float | None]:
    """Ответы → (ON/OFF, time.time() начала). Запись на паузе — всё ещё ON. Начало — самого раннего из идущих."""
    active = [r for r in (answers.get(t, {}) for t in REQUESTS) if r.get("outputActive")]
    if not active:
        return Live.OFF, None
    durations = [r["outputDuration"] for r in active if isinstance(r.get("outputDuration"), (int, float))]
    return Live.ON, (now - max(durations) / 1000 if durations else None)


def live_status(timeout: float = 1.0) -> tuple[Live, float | None]:
    """OFF — OBS не запущена или ничего не ведёт; ON — эфир или запись (и с какого момента); UNKNOWN — не узнать.
    Блокирует до `timeout` секунд (для окна — вызывать не в потоке интерфейса)."""
    if not obs_running():
        return Live.OFF, None
    try:
        c = json.loads(CONFIG.read_text())
        if not c.get("server_enabled", True):
            return Live.UNKNOWN, None
        url = f"ws://{HOST}:{int(c.get('server_port', 4455))}"
        answers = _ask(url, str(c.get("server_password", "")) if c.get("auth_required", True) else "", timeout)
    except Exception:  # noqa: BLE001 — нет библиотеки, отказ, таймаут, мусор: любая ошибка значит «не знаем»
        return Live.UNKNOWN, None
    return interpret(answers, time.time())
