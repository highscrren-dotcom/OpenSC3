"""Значок SC3 в трее (StatusNotifierItem через Qt) и его меню (бриф №8: окно + трей).

Значок — по состоянию (view.tray_icon): подключён / заглушён / отключён / эфир / эфир + заглушён; картинки —
`icons/png/` (их рисует design/panel/icons/draw.py + export.py). Готовые PNG Plasma не перекрашивает, поэтому
вариант под тёмную или светлую панель выбирается по палитре приложения.
"""
from __future__ import annotations

import time
from pathlib import Path

from PySide6.QtCore import QObject, QSize
from PySide6.QtGui import QGuiApplication, QIcon, QPalette
from PySide6.QtWidgets import QMenu, QSystemTrayIcon

from opensc3.model import AppState

from . import view

PNG = Path(__file__).resolve().parent / "icons" / "png"
SIZES = (22, 32)


def icon_files(name: str, theme: str) -> list[tuple[Path, int]]:
    """Файлы значка `name` для темы панели `theme` ("dark" | "light") с их размером в пикселях."""
    out = []
    for size in SIZES:
        out.append((PNG / f"sc3-{name}-{size}-{theme}.png", size))
        out.append((PNG / f"sc3-{name}-{size}-{theme}@2x.png", size * 2))
    return out


def panel_theme() -> str:
    """"dark" — светлый знак для тёмной панели (Breeze Dark), "light" — наоборот."""
    window = QGuiApplication.palette().color(QPalette.ColorRole.Window)
    return "dark" if window.lightness() < 128 else "light"


class Tray(QObject):
    def __init__(self, backend, *, show_window, toggle_window, quit_app, visible: bool = True) -> None:
        super().__init__(backend)
        self._backend = backend
        self._icons: dict[tuple[str, str], QIcon] = {}
        self._shown: tuple[str, str, str] | None = None

        self.menu = QMenu()
        profiles = self.menu.addAction("Профилей пока нет")
        profiles.setEnabled(False)
        self.menu.addSeparator()
        self.mute = self.menu.addAction("Заглушить микрофон")
        self.mute.setCheckable(True)
        self.mute.triggered.connect(backend.setMicMute)
        self.menu.addAction("Открыть окно SC3").triggered.connect(show_window)
        self.menu.addSeparator()
        self.menu.addAction("Выход").triggered.connect(quit_app)

        self.icon = QSystemTrayIcon(self)
        self.icon.setContextMenu(self.menu)
        self.icon.activated.connect(
            lambda reason: toggle_window() if reason == QSystemTrayIcon.ActivationReason.Trigger else None)
        backend.appStateChanged.connect(self.update)
        QGuiApplication.styleHints().colorSchemeChanged.connect(self._theme_changed)
        self.update(backend.state)
        if visible:  # тесты: без show() значок нигде не регистрируется
            self.icon.show()

    def _icon(self, name: str) -> QIcon:
        key = (name, panel_theme())
        if key not in self._icons:
            icon = QIcon()
            for path, size in icon_files(*key):
                icon.addFile(str(path), QSize(size, size))
            self._icons[key] = icon
        return self._icons[key]

    def _theme_changed(self, *_args) -> None:
        self._icons.clear()
        self._shown = None
        self.update(self._backend.state)

    def update(self, st: AppState) -> None:
        # Опрос SC3 обновляет состояние дважды в секунду: значок и подсказку трогаем, только когда они меняются.
        shown = (view.tray_icon(st), view.tray_tooltip(st, time.time()), panel_theme())
        if shown != self._shown:
            self._shown = shown
            self.icon.setIcon(self._icon(shown[0]))
            self.icon.setToolTip(shown[1])
        self.mute.setEnabled(st.audio.present)
        self.mute.setChecked(st.audio.pw_muted is True)

    def hide(self) -> None:
        self.icon.hide()
