"""Системный трей: открыть, виджет, пауза, настройки, выход."""
from __future__ import annotations

from PySide6.QtGui import QAction
from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

from ..domain.models import PlaybackSnapshot, PlaybackState
from .icons import icon


class Tray(QSystemTrayIcon):
    def __init__(self, controller):
        super().__init__(icon("music"), controller.app)
        self.controller = controller
        self.setToolTip("MyMusic")
        text_color = "#1b1b1f"
        self._icon = icon("music", color="#4b5cf0")
        self.setIcon(self._icon)
        menu = QMenu()
        self.open_action = QAction("Открыть MyMusic", menu)
        self.open_action.triggered.connect(controller.show_main)
        self.widget_action = QAction("Показать виджет", menu)
        self.widget_action.setCheckable(True)
        self.widget_action.toggled.connect(controller.set_widget_visible)
        self.play_action = QAction("Пауза", menu)
        self.play_action.triggered.connect(controller.toggle_pause)
        settings_action = QAction("Настройки…", menu)
        settings_action.triggered.connect(controller.show_settings)
        quit_action = QAction("Выйти", menu)
        quit_action.triggered.connect(controller.quit)
        menu.addAction(self.open_action)
        menu.addAction(self.widget_action)
        menu.addSeparator()
        menu.addAction(self.play_action)
        menu.addAction(settings_action)
        menu.addSeparator()
        menu.addAction(quit_action)
        self._menu = menu
        self.setContextMenu(menu)
        self.activated.connect(self._on_activated)
        self.update_snapshot(controller.player_snapshot())
        self.show()

    def _on_activated(self, reason) -> None:
        if reason in (QSystemTrayIcon.Trigger, QSystemTrayIcon.DoubleClick):
            self.controller.show_main()

    def update_snapshot(self, snapshot: PlaybackSnapshot) -> None:
        if snapshot.state == PlaybackState.PLAYING:
            self.play_action.setText("Пауза")
        else:
            self.play_action.setText("Продолжить")
        track = snapshot.track
        if track is not None:
            self.setToolTip(f"{track.title} — {track.artist}")
        else:
            self.setToolTip("MyMusic")

    def sync_widget(self, visible: bool) -> None:
        self.widget_action.blockSignals(True)
        self.widget_action.setChecked(visible)
        self.widget_action.setText("Скрыть виджет" if visible else "Показать виджет")
        self.widget_action.blockSignals(False)
