"""SC3 целиком: проверка перед опросом, чтения с повторами и счётчиками, полный дамп. Только чтение.

Порядок обязателен: `verify()` (дескриптор интерфейса 4 → сборка прошивки) — и лишь потом остальные чтения.
Чужая сборка — отказ: адреса и смысл узлов у другой версии могут отличаться.
"""
from __future__ import annotations

import time

from . import protocol as P
from .protocol import Sc3Busy

__all__ = ["Sc3", "Sc3Busy"]


class Sc3:
    DELAY, RETRIES = 0.010, 4  # измерено dank0i: 0 % потерь на 400 чтениях; 50 мс задержки теряют всё

    def __init__(self, transport):
        self.t = transport
        self.ok = self.fail = 0
        self.descriptor: bytes | None = None
        self.version: bytes | None = None
        self._verified = False

    @classmethod
    def open(cls, factory=None) -> Sc3:
        """Открыть и захватить интерфейс 4. Захват не удался — транспорт закрывается (открытые узлы USB не
        копятся, если окно пробует снова); занято другим процессом — `Sc3Busy`. `factory` — для тестов."""
        if factory is None:
            from .usb import LibusbTransport
            factory = LibusbTransport
        t = factory()
        try:
            t.claim()
        except BaseException:
            t.close()
            raise
        return cls(t)

    def close(self) -> None:
        self.t.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    # -- проверка --------------------------------------------------------------------------------------

    def check_descriptor(self) -> dict:
        self.descriptor = self.t.report_descriptor()
        parsed = P.parse_hid(self.descriptor)
        if not P.interface4_ok(parsed):
            raise P.ProtocolError(f"дескриптор интерфейса 4 не такой, как ожидалось ({parsed}) — ACP не трогаю")
        return parsed

    def verify(self) -> bytes:
        """Дескриптор, затем 0x00. Возвращает тело версии; чужая сборка — исключение."""
        self.check_descriptor()
        self.version = self._read(0x00)
        if self.version != P.V22_VERSION:
            got = self.version.hex(" ") if self.version is not None else "нет ответа"
            raise P.ProtocolError(f"сборка прошивки не V22 ({got}) — дальше не иду")
        self._verified = True
        return self.version

    # -- чтения ----------------------------------------------------------------------------------------

    def _transact(self, frame: bytes, echo: int | None = None) -> bytes | None:
        for _ in range(self.RETRIES + 1):
            self.t.set_output(frame)
            time.sleep(self.DELAY)
            try:
                r = self.t.get_input()
            except P.ProtocolError:
                continue
            body = P.reply_body(r, frame[2], echo)
            if body is not None:
                self.ok += 1
                return body
        self.fail += 1
        return None

    def _read(self, ctrl: int) -> bytes | None:
        return self._transact(P.read_frame(ctrl))

    def _need(self) -> None:
        if not self._verified:
            raise P.ProtocolError("сначала verify(): дескриптор и сборка не проверены")

    def read(self, ctrl: int) -> bytes | None:
        self._need()
        return self._read(ctrl)

    def node(self, addr: int) -> list[int] | None:
        if not P.NODE_MIN <= addr <= P.NODE_MAX:
            raise P.ProtocolError(f"узел {addr:#04x} вне {P.NODE_MIN:#04x}…{P.NODE_MAX:#04x}")
        body = self.read(addr)
        return None if body is None else P.node_values(body)

    def name(self, addr: int) -> str | None:
        self._need()
        i = addr - P.NODE_MIN + 1
        body = self._transact(P.name_frame(i), echo=i)
        return None if body is None else bytes(c for c in body[1:] if 32 <= c < 127).decode().strip() or None

    def types(self) -> list[int] | None:
        self._need()
        body = self._transact(P.name_frame(0), echo=0)
        if body is None or len(body) < 2:
            return None
        cnt = body[1]
        return [body[2 + 2 * k] | body[3 + 2 * k] << 8 for k in range(min(cnt, (len(body) - 2) // 2))]

    def dump(self) -> dict:
        """Всё, что читается: блоки, типы, имена и значения 54 узлов. ~123 чтения, ~2 с."""
        self._need()
        res: dict = {"time": time.strftime("%Y-%m-%d %H:%M:%S"),
                     "descriptor_if4": self.descriptor.hex(" ") if self.descriptor else None,
                     "version": self.version.hex(" ") if self.version else None}
        fc = self.read(P.SCRATCH)
        res["fc"] = fc.hex(" ") if fc is not None else None
        res["system"] = {}
        for ctrl, label in P.SYSTEM.items():
            b = self.version if ctrl == 0x00 else self.read(ctrl)
            res["system"][f"{ctrl:#04x} {label}"] = b.hex(" ") if b is not None else None
        res["types"] = types = self.types()
        res["nodes"] = {}
        for k, addr in enumerate(range(P.NODE_MIN, P.NODE_MAX + 1)):
            body = self.read(addr)
            res["nodes"][f"{addr:#04x}"] = {
                "name": self.name(addr),
                "type": types[k] if types and k < len(types) else None,
                "raw": body.hex(" ") if body else None,
                "values": P.node_values(body) if body is not None else None,
            }
        res["counters"] = {"ok": self.ok, "fail": self.fail}
        return res
