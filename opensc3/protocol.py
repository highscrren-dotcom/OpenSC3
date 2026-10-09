"""Протокол ACP микшера fifine SC3 (USB 3142:0c33, интерфейс 4) — кадры, белый список, разбор ответов.

Кадр: `A5 5A <ctrl> <len> <тело…> 16`, `len = 0` — чтение. На проводе — SET_REPORT Output (256 байт, без
Report ID) и GET_REPORT Input. Устройство само ничего не шлёт и на непонятную команду отдаёт ПРЕДЫДУЩИЙ ответ,
поэтому ctrl ответа сверяется всегда. Подробно — docs/RESEARCH.md, разделы 4 и 12.

Кадры собирает только `frame()`, и каждый сразу проходит `check_frame`. Запись (этап 3, docs/WRITE.md) — один
параметр узла: `A5 5A <узел> 03 <idx> <int16 LE> 16`. Какие узлы, параметры и границы — белый список в write.py
(данные); `check_frame` спрашивает его последним рубежом перед USB, а запреты ниже действуют независимо от него.
Запреты — исключениями, а не assert: `python -O` их не отключит.
"""
from __future__ import annotations

import struct

VID, PID = 0x3142, 0x0C33
IFACE = 4
REPORT = 256  # байт отчёта на проводе; сверяется с дескриптором интерфейса 4 перед первым кадром

# Ответ заводской V22 на 0x00 (так её опознаёт RGB-Plus). По SDK MVsilicon это сигнатура сборки, а не номер
# Fifine: чип 0x31, конфигурация эффектов 0.1.1, аудиобиблиотека 1.33.5.
V22_VERSION = bytes.fromhex("31000101012105")
STOCK_FC = bytes.fromhex("ff01020304")  # 0xFC на непатченной прошивке

SYSTEM = {0x00: "version", 0x01: "system", 0x02: "query", 0x03: "PGA0", 0x04: "ADC0", 0x06: "PGA1",
          0x07: "ADC1", 0x08: "AGC1", 0x09: "DAC0", 0x0A: "DAC1", 0x0B: "I2S0", 0x0C: "I2S1", 0x0D: "SPDIF"}
NODE_MIN, NODE_MAX = 0x81, 0xB6  # 54 узла; выше 0xB6 — мусор, затем весь ACP молчит до переоткрытия
NODE_COUNT = NODE_MAX - NODE_MIN + 1
SCRATCH, NAMES = 0xFC, 0x80
READ_CTRLS = frozenset(SYSTEM) | frozenset(range(NODE_MIN, NODE_MAX + 1)) | {SCRATCH}
# 0x11 — запись во флеш, 0xFB — длина без проверки, 0xFD — вне массива узлов, 0xFE — OTA (уход в загрузчик),
# 0xFF — шифрование (в одном бите от 0xFE). Не посылаются никогда, ни в каком виде.
NEVER = frozenset((0x11, 0xFB, 0xFD, 0xFE, 0xFF))
# Запись — только в узлы 0x81…0xB6 и никогда в узел ползунка Line In (его держит ползунок, как громкость 0x07 —
# ползунок Mic). Блоки системы (0x00–0x0D: сон/сброс 0x01, громкость 0x07), 0x80 и 0xFC не пишутся вовсе.
LINE_IN_FADER = 0xB6
WRITE_NEVER = frozenset({LINE_IN_FADER})
WRITE_LEN = 3  # один параметр: индекс + int16. Группы (DRC) и «все параметры сразу» (0xFF) — нет

SAMPLE_RATES = (8000, 11025, 12000, 16000, 22050, 24000, 32000, 44100, 48000)


class ProtocolError(Exception):
    pass


class Sc3Busy(ProtocolError):
    """Интерфейс 4 уже захвачен другим процессом (LIBUSB_ERROR_BUSY): обычно окно, которое опрашивает SC3
    (решение 9). Временное: можно попробовать позже."""
    TEXT = "SC3 занят другим процессом (окно SC3?)"

    def __init__(self, msg: str = TEXT):
        super().__init__(msg)


def check_frame(f: bytes) -> bytes:
    """Единственные кадры, которые можно послать: чтение из белого списка, имя узла 0…54 и запись одного
    параметра узла из белого списка записи (write.py)."""
    if len(f) < 5 or f[0] != 0xA5 or f[1] != 0x5A:
        raise ProtocolError(f"не кадр ACP: {f.hex(' ')}")
    ctrl, ln = f[2], f[3]
    if ctrl in NEVER:
        raise ProtocolError(f"запрещённая команда {ctrl:#04x}")
    if len(f) != 5 + ln or f[-1] != 0x16:
        raise ProtocolError(f"кривой кадр: {f.hex(' ')}")
    if ctrl == NAMES:
        if ln != 1 or f[4] > NODE_COUNT:
            raise ProtocolError(f"0x80 — только с одним байтом-индексом 0…{NODE_COUNT}: {f.hex(' ')}")
    elif ln == 0:
        if ctrl not in READ_CTRLS:
            raise ProtocolError(f"команды {ctrl:#04x} нет в белом списке чтения")
    else:
        _check_write(f)
    return f


def _check_write(f: bytes) -> None:
    """Кадр записи: сначала запреты, не зависящие от белого списка, потом сам белый список (write.py)."""
    ctrl, ln = f[2], f[3]
    if not NODE_MIN <= ctrl <= NODE_MAX:
        raise ProtocolError(f"запись запрещена: {ctrl:#04x} — не узел эффектов (с LEN={ln})")
    if ctrl in WRITE_NEVER:
        raise ProtocolError(f"запись запрещена: узел {ctrl:#04x} держит ползунок")
    if ln != WRITE_LEN or f[4] == 0xFF:
        raise ProtocolError(f"запись — только один параметр (LEN {WRITE_LEN}): {ctrl:#04x} с LEN={ln}")
    from .write import check_write_frame  # здесь, а не сверху: write.py сам строит кадры через этот модуль
    check_write_frame(f)


def frame(ctrl: int, body: bytes = b"") -> bytes:
    """`A5 5A <ctrl> <len> <тело> 16` — единственный построитель кадров. Кадр сразу проходит `check_frame`:
    вне белых списков его не собрать вовсе."""
    body = bytes(body)
    if len(body) > REPORT - 5:
        raise ProtocolError(f"тело {len(body)} байт не влезает в отчёт {REPORT}")
    return check_frame(bytes([0xA5, 0x5A, ctrl, len(body)]) + body + b"\x16")


def read_frame(ctrl: int) -> bytes:
    return frame(ctrl)


def name_frame(index: int) -> bytes:
    """0x80 с индексом: 0 — таблица типов узлов, 1…54 — имя узла 0x80 + индекс."""
    return frame(NAMES, bytes([index]))


def reply_body(r: bytes, ctrl: int, echo: int | None = None) -> bytes | None:
    """Тело ответа, если это ответ именно на `ctrl` (и на индекс `echo` у 0x80), иначе None."""
    if len(r) < 5 or r[0] != 0xA5 or r[1] != 0x5A or r[2] != ctrl:
        return None
    body = r[4: 4 + r[3]]
    if echo is not None and (len(body) < 1 or body[0] != echo):
        return None
    return body


def write_ack(r: bytes, ctrl: int) -> bool:
    """Подтверждение записи: отчёт `<ctrl> 00 00 …` — адрес узла и нули (SDK, хвост Communication_Effect_Config:
    обнулить буфер, первый байт = ctrl). Устаревший ответ (прошлое чтение `A5 5A …`) так не выглядит, а прошлое
    подтверждение того же узла — выглядит: поэтому перед записью узел всегда читается (write.py). Подтверждение —
    лишь подсказка; истина — чтение назад."""
    return len(r) >= 2 and r[0] == ctrl and not any(r[1:])


def node_values(body: bytes) -> list[int]:
    """Ответ узла: `FF <enable> <p1> …` (int16 LE) → [enable, p1, …]."""
    rest = body[1:] if body[:1] == b"\xff" else body
    k = len(rest) // 2
    return list(struct.unpack(f"<{k}h", rest[: 2 * k])) if k else []


def parse_hid(desc: bytes) -> dict:
    """Минимальный разбор дескриптора HID: страница и usage, Report ID, размеры In/Out/Feature в битах."""
    i, g = 0, {"size": 0, "count": 0}
    out = {"report_ids": [], "in": 0, "out": 0, "feature": 0, "page": None, "usage": None}
    while i < len(desc):
        pfx = desc[i]
        if pfx == 0xFE:  # long item
            i += 3 + desc[i + 1]
            continue
        n = (0, 1, 2, 4)[pfx & 3]
        data = int.from_bytes(desc[i + 1: i + 1 + n], "little")
        tag = pfx & 0xFC
        if tag == 0x04 and out["page"] is None:
            out["page"] = data
        elif tag == 0x08 and out["usage"] is None:
            out["usage"] = data
        elif tag == 0x74:
            g["size"] = data
        elif tag == 0x94:
            g["count"] = data
        elif tag == 0x84:
            out["report_ids"].append(data)
        elif tag in (0x80, 0x90, 0xB0):
            out[{0x80: "in", 0x90: "out", 0xB0: "feature"}[tag]] += g["size"] * g["count"]
        i += 1 + n
    return out


def interface4_ok(parsed: dict) -> bool:
    """Интерфейс 4 такой, каким его знаем: вендорская страница, без Report ID, вход и выход по 256 байт."""
    return (parsed["page"] == 0xFF00 and not parsed["report_ids"]
            and parsed["in"] == REPORT * 8 and parsed["out"] == REPORT * 8)
