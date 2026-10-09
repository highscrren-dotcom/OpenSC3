"""Qt без экрана — для тестов и `--screenshot`: ни окна, ни значка в трее владельца.

Вызывать ДО создания QApplication. Платформа offscreen не показывает окон; тему платформы (KDE) снимаем —
она умеет трей через D-Bus. Значок трея в таком режиме не создаётся вовсе (main.py, тесты).
"""
from __future__ import annotations

import os

SCRUB = ("QT_QPA_PLATFORMTHEME", "QT_QUICK_BACKEND", "QSG_RHI_BACKEND", "QT_SCALE_FACTOR",
         "QT_SCREEN_SCALE_FACTORS", "QMLSCENE_DEVICE")


def prepare(gpu: bool = False) -> str:
    """Окружение для офскрина. `gpu` — OpenGL через GLX (нужен DISPLAY, XWayland), иначе — программная отрисовка
    (без MultiEffect: окно переходит на плоский вид). Возвращает выбранный бэкенд: "opengl" | "software"."""
    for k in SCRUB:
        os.environ.pop(k, None)
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    os.environ["QT_FORCE_STDERR_LOGGING"] = "1"           # иначе без TTY журнал Qt уходит в journald
    os.environ["QSG_DISTANCEFIELD_ANTIALIASING"] = "gray"  # без цветной каймы субпикселей в PNG
    if gpu and os.environ.get("DISPLAY"):
        os.environ["QT_QUICK_BACKEND"] = "rhi"             # на offscreen Qt иначе молча берёт software
        os.environ["QSG_RHI_BACKEND"] = "opengl"
        return "opengl"
    os.environ["QT_QUICK_BACKEND"] = "software"
    return "software"
