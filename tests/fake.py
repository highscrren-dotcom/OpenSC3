"""Поддельный SC3 для тестов без железа. Повторяет два свойства транспорта: ответ забирается GET_REPORT,
а на непонятную/неотвеченную команду устройство отдаёт ПРЕДЫДУЩИЙ ответ. Имена узлов — синтетические
(настоящие — данные Fifine, в репо их нет: docs/DECISIONS.md, решение 5)."""
import struct

from opensc3 import protocol as P

# Настоящий дескриптор интерфейса 4 SC3 (стандартный USB-дескриптор, снят 07.10.2026)
DESC4 = bytes.fromhex("0600ff0aaa55a101150026ff00750896000109018102960001090191029508 0901b102c0".replace(" ", ""))
# Настоящие тела блоков SC3 (только числа регистров), дамп 07.10.2026 11:05
BLOCKS = {
    0x01: "ff00000000010007000100000001 00",
    0x02: "ffbc0016010140014001",
    0x06: "ff010001000f0000000f00000000000100 0100",
    0x07: "ff03000000fc0ffc0f070000000000000000000100",
    0x08: "ff0000000000000000000000000a000a000a000a000000050000000000",
}


class FakeTransport:
    """`nodes` — значения узлов {адрес: [enable, p1, …]} (остальные узлы — [1, 0, 4096]); `blocks` — тела блоков
    поверх BLOCKS; `silent` — команды, на которые устройство молчит (GET_REPORT отдаст прошлый ответ);
    `broken` — команды, на которых рвётся транспорт (ProtocolError из set_output); `types` — таблица типов узлов
    (0x80, индекс 0) вместо синтетической.

    Запись (LEN > 0 в узел) меняет `nodes` и отвечает подтверждением `<узел> 00 00 …` (SDK). `stuck` — узлы, где
    запись подтверждается, но значение не меняется (его держит прошивка); `no_ack` — запись меняет значение, но
    подтверждения нет (GET_REPORT отдаст прошлый ответ). `clock` — часы: момент каждого кадра в `times`."""

    def __init__(self, version=P.V22_VERSION, desc=DESC4, drop_names=(), nodes=None, blocks=None, silent=(),
                 broken=(), types=None, stuck=(), no_ack=(), clock=None):
        self.version, self.desc, self.drop_names = version, desc, set(drop_names)
        self.nodes, self.blocks = {a: list(v) for a, v in (nodes or {}).items()}, dict(blocks or {})
        self.silent, self.broken = set(silent), set(broken)
        self.types, self.stuck, self.no_ack, self.clock = types, set(stuck), set(no_ack), clock
        self.sent, self.last, self.claimed, self.closed = [], bytes(256), False, False
        self.writes, self.times = [], []  # writes: (узел, индекс, значения) — что устройство приняло

    def claim(self):
        self.claimed = True

    def report_descriptor(self):
        return self.desc

    def _reply(self, ctrl, body):
        r = bytearray(256)
        r[0:4] = bytes([0xA5, 0x5A, ctrl, len(body)])
        r[4: 4 + len(body)] = body
        r[4 + len(body)] = 0x16
        self.last = bytes(r)

    def _write(self, ctrl, frame):
        idx, (value,) = frame[4], struct.unpack("<h", frame[5:7])  # один параметр: индекс = место в ответе чтения
        self.writes.append((ctrl, idx, value))
        if ctrl not in self.stuck:
            self.nodes.setdefault(ctrl, [1, 0, 4096])[idx] = value
        if ctrl not in self.no_ack:
            self.last = bytes([ctrl]) + bytes(255)

    def set_output(self, frame):
        P.check_frame(frame)  # настоящий транспорт делает то же
        self.sent.append(bytes(frame))
        if self.clock is not None:
            self.times.append(self.clock())
        ctrl = frame[2]
        if ctrl in self.broken:
            raise P.ProtocolError(f"control 0x21/0x09: LIBUSB_ERROR_NO_DEVICE ({ctrl:#04x})")
        if ctrl in self.silent:
            return
        if frame[3] and ctrl != P.NAMES:
            self._write(ctrl, frame)
            return
        if ctrl in self.blocks:
            self._reply(ctrl, self.blocks[ctrl])
        elif ctrl in self.nodes:
            v = self.nodes[ctrl]
            self._reply(ctrl, b"\xff" + struct.pack(f"<{len(v)}h", *v))
        elif ctrl == 0x00:
            self._reply(0, self.version)
        elif ctrl == P.SCRATCH:
            self._reply(ctrl, P.STOCK_FC)
        elif ctrl == P.NAMES:
            i = frame[4]
            if i == 0:
                table = self.types or [15 if k >= 38 else k % 30 for k in range(P.NODE_COUNT)]
                types = b"".join(struct.pack("<H", t) for t in table)
                self._reply(ctrl, bytes([0, P.NODE_COUNT]) + types)
            elif i not in self.drop_names:
                self._reply(ctrl, bytes([i]) + f"1:Fake {i}".encode())
            # иначе молчит — GET_REPORT вернёт прошлый ответ
        elif P.NODE_MIN <= ctrl <= P.NODE_MAX:
            self._reply(ctrl, b"\xff" + struct.pack("<hhh", 1, 0, 4096))
        elif ctrl in BLOCKS:
            self._reply(ctrl, bytes.fromhex(BLOCKS[ctrl].replace(" ", "")))
        elif ctrl in P.SYSTEM:
            self._reply(ctrl, b"\xff" + bytes(8))

    def get_input(self):
        return self.last

    def close(self):
        self.closed = True
