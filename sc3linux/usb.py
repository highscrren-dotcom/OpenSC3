"""Транспорт к интерфейсу 4 через libusb (ctypes): только control-запросы, без зависимостей кроме libusb-1.0.

Почему не hidraw: у интерфейса 4 нет ни одной конечной точки, и usbhid его не берёт («couldn't find an input
interrupt endpoint»). Почему не hidapi/pyusb: docs/DECISIONS.md, решение 2.

Чего здесь нет и не будет: set_configuration, reset, set_interface_alt_setting, detach/attach драйверов
(рвёт звук), SET/GET_FEATURE (вход в загрузчик). tests/test_safety.py проверяет это по исходнику.
"""
from __future__ import annotations

import ctypes as C

from .protocol import IFACE, PID, REPORT, VID, ProtocolError, Sc3Busy, check_frame

TIMEOUT_MS = 250
LIBUSB_ERROR_BUSY = -6


class LibusbTransport:
    def __init__(self):
        try:
            lib = C.CDLL("libusb-1.0.so.0")
        except OSError as e:
            raise ProtocolError(f"нет libusb-1.0: {e}") from None
        lib.libusb_init.argtypes = [C.POINTER(C.c_void_p)]
        lib.libusb_open_device_with_vid_pid.restype = C.c_void_p
        lib.libusb_open_device_with_vid_pid.argtypes = [C.c_void_p, C.c_uint16, C.c_uint16]
        for fn in ("libusb_kernel_driver_active", "libusb_claim_interface", "libusb_release_interface"):
            getattr(lib, fn).argtypes = [C.c_void_p, C.c_int]
        lib.libusb_control_transfer.argtypes = [C.c_void_p, C.c_uint8, C.c_uint8, C.c_uint16, C.c_uint16,
                                                C.c_void_p, C.c_uint16, C.c_uint]
        lib.libusb_close.argtypes = [C.c_void_p]
        lib.libusb_exit.argtypes = [C.c_void_p]
        lib.libusb_error_name.restype = C.c_char_p
        self.lib, self.ctx, self.h, self.claimed = lib, C.c_void_p(), None, False
        if lib.libusb_init(C.byref(self.ctx)) != 0:
            raise ProtocolError("libusb_init не удался")
        self.h = lib.libusb_open_device_with_vid_pid(self.ctx, VID, PID)
        if not self.h:
            self.close()
            raise ProtocolError("не открыть SC3: не подключён или нет прав на USB-узел (udev/70-fifine-sc3.rules)")
        if lib.libusb_kernel_driver_active(self.h, IFACE) != 0:
            self.close()
            raise ProtocolError(f"у интерфейса {IFACE} неожиданно есть драйвер ядра — не трогаю")

    def _err(self, r: int) -> str:
        return self.lib.libusb_error_name(r).decode()

    def claim(self) -> None:
        """До первого запроса: иначе usbfs захватит интерфейс сам и напишет предупреждение в журнал."""
        r = self.lib.libusb_claim_interface(self.h, IFACE)
        if r == LIBUSB_ERROR_BUSY:
            raise Sc3Busy()
        if r != 0:
            raise ProtocolError(f"claim интерфейса {IFACE}: {self._err(r)}")
        self.claimed = True

    def _ctl(self, rt: int, req: int, val: int, buf: bytearray | None, length: int) -> bytes:
        b = (C.c_uint8 * max(length, 1)).from_buffer(buf) if buf is not None else (C.c_uint8 * length)()
        r = self.lib.libusb_control_transfer(self.h, rt, req, val, IFACE, b, length, TIMEOUT_MS)
        if r < 0:
            raise ProtocolError(f"control {rt:#04x}/{req:#04x}: {self._err(r)}")
        return bytes(b)[:r]

    def report_descriptor(self) -> bytes:
        # Только интерфейс 4: интерфейс 3 держит usbhid, usbfs ответит EBUSY (его дескриптор есть в sysfs).
        return self._ctl(0x81, 0x06, 0x2200, None, 255)        # GET_DESCRIPTOR (Report), стандартный

    def set_output(self, frame: bytes) -> None:
        f = check_frame(frame)
        buf = bytearray(REPORT)
        buf[: len(f)] = f
        n = len(self._ctl(0x21, 0x09, 0x0200, buf, REPORT))  # SET_REPORT, Output, ID 0
        if n != REPORT:
            raise ProtocolError(f"SET_REPORT ушло {n} байт из {REPORT}")

    def get_input(self) -> bytes:
        return self._ctl(0xA1, 0x01, 0x0100, None, REPORT)     # GET_REPORT, Input, ID 0

    def close(self) -> None:
        if self.h:
            if self.claimed:
                self.lib.libusb_release_interface(self.h, IFACE)
            self.lib.libusb_close(self.h)
            self.h = None
        if self.ctx:
            self.lib.libusb_exit(self.ctx)
            self.ctx = None
