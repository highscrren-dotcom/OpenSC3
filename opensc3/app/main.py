"""Окно и трей SC3: `python3 -m opensc3.app` или `opensc3`. Только чтение SC3 (решение 4).

Один экземпляр: имя на сессионной шине D-Bus; второй запуск просит первый показать окно и выходит. Закрытие
окна — в трей (если трей есть). `--fake [сценарий]` — на подделке ядра, без SC3, OBS и PipeWire.
`--screenshot файл.png` — отрисовать окно без экрана (offscreen) и выйти: ни окна, ни трея, ни D-Bus.
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from .fake import SCENARIOS

APP_ID = "opensc3"                         # имя приложения и .desktop (data/opensc3.desktop)
DBUS_SERVICE = "dev.s1dd1.opensc3"
DBUS_PATH = "/Panel"
DBUS_INTERFACE = "dev.s1dd1.opensc3.Panel"
QML_MAIN = Path(__file__).resolve().parent / "qml" / "Main.qml"
SHOT_SETTLE_MS = 2600                      # --screenshot: первые ответы подделки, эфир, анимации
SHOT_LIVE_INTERVAL = 1.0

log = logging.getLogger("opensc3.app")


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(prog="opensc3", description="Окно и трей fifine AmpliGame SC3 (только чтение).")
    ap.add_argument("--fake", nargs="?", const="normal", choices=list(SCENARIOS), metavar="СЦЕНАРИЙ",
                    help="подделка ядра вместо SC3/OBS/PipeWire: " + ", ".join(SCENARIOS) + " (по умолчанию normal)")
    ap.add_argument("--tray", action="store_true", help="запуститься в трей, не показывая окно")
    ap.add_argument("--screenshot", type=Path, metavar="PNG", help="без экрана: отрисовать окно в PNG и выйти")
    ap.add_argument("--section", choices=["mic", "voice", "electric"], help="с --screenshot: открыть этот ящик")
    ap.add_argument("--software", action="store_true", help="с --screenshot: без GPU (плоский вид)")
    ap.add_argument("-v", "--verbose", action="store_true", help="подробный журнал")
    return ap.parse_args(argv)


def claim_single_instance(on_activate):
    """True — мы первые (имя занято, `activate` вызовет on_activate); False — уже запущено, окно там показано;
    None — сессионной шины нет, живём без проверки."""
    from PySide6.QtCore import ClassInfo, QObject, Slot
    from PySide6.QtDBus import QDBusConnection, QDBusConnectionInterface, QDBusInterface

    bus = QDBusConnection.sessionBus()
    if not bus.isConnected():
        log.warning("нет сессионной шины D-Bus: второй экземпляр не узнает о первом")
        return None

    @ClassInfo({"D-Bus Interface": DBUS_INTERFACE})
    class Activator(QObject):
        @Slot()
        def activate(self) -> None:
            on_activate()

    reply = bus.interface().registerService(
        DBUS_SERVICE,
        QDBusConnectionInterface.ServiceQueueOptions.DontQueueService,
        QDBusConnectionInterface.ServiceReplacementOptions.DontAllowReplacement,
    )
    if not reply.isValid():
        log.warning("D-Bus: %s — второй экземпляр не узнает о первом", reply.error().message())
        return None
    registered = QDBusConnectionInterface.RegisterServiceReply.ServiceRegistered
    if int(reply.value()) == registered.value:  # PySide6 отдаёт здесь int, а не enum
        claim_single_instance.activator = Activator()  # жить, пока живёт процесс
        bus.registerObject(DBUS_PATH, claim_single_instance.activator, QDBusConnection.RegisterOption.ExportAllSlots)
        return True
    first = QDBusInterface(DBUS_SERVICE, DBUS_PATH, DBUS_INTERFACE, bus)
    first.setTimeout(3000)
    first.call("activate")
    return False


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    logging.basicConfig(level=logging.INFO if args.verbose else logging.WARNING, format="opensc3: %(message)s")
    if args.screenshot:
        from .headless import prepare
        prepare(gpu=not args.software)
    try:
        from PySide6.QtCore import QTimer, QUrl
        from PySide6.QtQml import QQmlApplicationEngine
        from PySide6.QtQuick import QQuickWindow  # noqa: F401 — корень Main.qml придёт как QQuickWindow, не QWindow
        from PySide6.QtWidgets import QApplication, QSystemTrayIcon
    except ImportError:
        print("opensc3: нужен PySide6 — в CachyOS: sudo pacman -S pyside6", file=sys.stderr)
        return 1
    from .backend import LIVE_INTERVAL, Backend
    from .core import RealCore
    from .fake import FakeCore

    app = QApplication(sys.argv[:1])
    app.setApplicationName(APP_ID)
    app.setApplicationDisplayName("OpenSC3")
    app.setDesktopFileName(APP_ID)
    app.setQuitOnLastWindowClosed(False)

    window = None

    def show_window() -> None:
        if window is not None:
            window.show()
            window.raise_()
            window.requestActivate()

    def toggle_window() -> None:
        if window is not None and window.isVisible():
            window.hide()
        else:
            show_window()

    if not args.screenshot and claim_single_instance(show_window) is False:
        return 0  # окно показал уже запущенный экземпляр

    core = FakeCore(args.fake, demo=True) if args.fake else RealCore()
    backend = Backend(core, live_interval=SHOT_LIVE_INTERVAL if args.screenshot else LIVE_INTERVAL)
    engine = QQmlApplicationEngine()
    engine.setInitialProperties({"sc3": backend})
    engine.load(QUrl.fromLocalFile(str(QML_MAIN)))
    if not engine.rootObjects():
        print(f"opensc3: не загрузился {QML_MAIN}", file=sys.stderr)
        return 1
    window = engine.rootObjects()[0]
    window.visibleChanged.connect(backend.set_window_visible)

    tray = None
    if not args.screenshot and QSystemTrayIcon.isSystemTrayAvailable():
        from .tray import Tray
        tray = Tray(backend, show_window=show_window, toggle_window=toggle_window, quit_app=app.quit)
    window.setProperty("closeToTray", tray is not None)
    app.aboutToQuit.connect(backend.stop)
    # Окно показывается до старта бэкенда: видимое окно сразу идёт в лёгкий опрос, без лишнего полного набора.
    if args.screenshot:
        prepare_screenshot(window, args)
    elif not (args.tray and tray is not None):
        show_window()
    backend.start()
    rc = screenshot(app, window, args, QTimer) if args.screenshot else app.exec()
    window = None
    del engine  # сначала QML, потом бэкенд: иначе привязки на выходе увидят sc3 = null
    return rc


def prepare_screenshot(window, args) -> None:
    """Окно на платформе offscreen (никуда не выводится). Размер — до show(): у offscreen-окна с OpenGL
    поверхность после показа не растёт (кадр обрезается)."""
    window.setProperty("animations", False)
    if args.section:
        window.setProperty("section", args.section)
    window.setWidth(round(window.property("designWidth")))  # 1:1, а не под экран offscreen (800×600)
    window.setHeight(round(window.property("fullHeight")))  # по содержимому: ящик целиком, без прокрутки
    window.show()


def screenshot(app, window, args, QTimer) -> int:
    """Дать подделке ответить (опрос, эфир), снять кадр и выйти."""
    result = {"rc": 1}

    def grab() -> None:
        image = window.grabWindow()
        args.screenshot.parent.mkdir(parents=True, exist_ok=True)
        if not image.isNull() and image.save(str(args.screenshot)):
            print(f"ok   {args.screenshot}  {image.width()}x{image.height()}")
            result["rc"] = 0
        else:
            print(f"opensc3: не удалось снять {args.screenshot}", file=sys.stderr)
        app.quit()

    QTimer.singleShot(SHOT_SETTLE_MS, grab)
    app.exec()
    return result["rc"]


if __name__ == "__main__":
    sys.exit(main())
