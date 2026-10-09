"""Есть ли SC3 на шине и можно ли к нему по USB — без единого обращения к устройству (только sysfs и права).

`probe()` → DISCONNECTED (нет на шине), NO_ACCESS (нет прав на чтение-запись USB-узла: правило udev, этап 2) или
CONNECTED — это лишь «можно пробовать verify()»: узел не открывается. `Watcher` — события udev (pyudev, импорт
внутри) для QSocketNotifier: подключили, отключили, сменились права (uaccess).
"""
from __future__ import annotations

import os
from pathlib import Path

from .model import Link
from .protocol import PID, VID

SYS_USB = Path("/sys/bus/usb/devices")
DEV_USB = Path("/dev/bus/usb")


def usb_device(sys_root: Path = SYS_USB) -> Path | None:
    """Каталог SC3 в sysfs (по VID:PID; серийник 20190808 общий для MVsilicon)."""
    try:
        entries = sorted(sys_root.iterdir())
    except OSError:
        return None
    for d in entries:
        try:
            if (d / "idVendor").read_text().strip() == f"{VID:04x}" and \
                    (d / "idProduct").read_text().strip() == f"{PID:04x}":
                return d
        except OSError:
            continue  # интерфейсы (3-13:1.0) без idVendor, устройство ушло посреди обхода
    return None


def probe(sys_root: Path = SYS_USB, dev_root: Path = DEV_USB, access=os.access) -> tuple[Link, str | None]:
    """(состояние, путь USB-узла /dev/bus/usb/BBB/DDD). Узел не открывается — только os.access."""
    d = usb_device(sys_root)
    if d is None:
        return Link.DISCONNECTED, None
    try:
        bus, num = int((d / "busnum").read_text()), int((d / "devnum").read_text())
    except (OSError, ValueError):
        return Link.DISCONNECTED, None  # ушло посреди чтения
    node = str(dev_root / f"{bus:03d}" / f"{num:03d}")
    return (Link.CONNECTED if access(node, os.R_OK | os.W_OK) else Link.NO_ACCESS), node


def _is_sc3(dev) -> bool:
    """Событие udev про SC3? У «remove» атрибутов sysfs уже нет — смотрим свойства события."""
    props = dev.properties
    if (props.get("ID_VENDOR_ID"), props.get("ID_MODEL_ID")) == (f"{VID:04x}", f"{PID:04x}"):
        return True
    prod = (props.get("PRODUCT") or "").split("/")  # «3142/c33/100» — hex без ведущих нулей
    try:
        return len(prod) >= 2 and (int(prod[0], 16), int(prod[1], 16)) == (VID, PID)
    except ValueError:
        return False


class Watcher:
    """События udev про SC3. `fileno()` — для QSocketNotifier (чтение), `poll()` — разобрать накопленное:
    True, если что-то поменялось у SC3 (тогда — заново `probe()`, а узлы PipeWire появятся чуть позже)."""

    def __init__(self, pyudev=None):
        if pyudev is None:
            import pyudev
        self._mon = pyudev.Monitor.from_netlink(pyudev.Context())
        self._mon.filter_by("usb", device_type="usb_device")
        self._mon.start()

    def fileno(self) -> int:
        return self._mon.fileno()

    def poll(self) -> bool:
        """Не блокирует. Выбирает все события из очереди."""
        changed = False
        while True:
            try:
                dev = self._mon.poll(timeout=0)
            except OSError:
                break
            if dev is None:
                break
            changed = changed or _is_sc3(dev)
        return changed
