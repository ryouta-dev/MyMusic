"""Настройки приложения: источник, тема, виджет, автозапуск, данные."""
from __future__ import annotations

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QFrame, QHBoxLayout,
                               QLabel, QMessageBox, QPushButton, QVBoxLayout)

from .theme import apply_theme, resolve_theme


class SettingsDialog(QDialog):
    def __init__(self, controller):
        super().__init__(controller.main_window)
        self.controller = controller
        self.setWindowTitle("Настройки MyMusic")
        self.setModal(True)
        self.setMinimumWidth(480)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(12)

        title = QLabel("Настройки")
        title.setStyleSheet("font-size: 14pt; font-weight: 600;")
        layout.addWidget(title)

        source = QFrame()
        source_layout = QVBoxLayout(source)
        source_layout.setContentsMargins(12, 10, 12, 10)
        source_title = QLabel("Источник музыки")
        source_title.setStyleSheet("font-weight: 600;")
        source_text = QLabel("Audius — открытый музыкальный каталог.\n"
                             "Ключ и аккаунт не требуются. Поиск и стриминг работают через "
                             "публичный API; при отсутствии сети появится понятная ошибка.")
        source_text.setWordWrap(True)
        source_text.setObjectName("muted")
        self.source_status = QLabel("Статус: проверяется при поиске")
        self.source_status.setObjectName("muted")
        source_layout.addWidget(source_title)
        source_layout.addWidget(source_text)
        source_layout.addWidget(self.source_status)
        layout.addWidget(source)

        theme_row = QHBoxLayout()
        theme_row.addWidget(QLabel("Тема оформления"))
        self.theme_combo = QComboBox()
        self.theme_combo.addItem("Как в системе", "system")
        self.theme_combo.addItem("Светлая", "light")
        self.theme_combo.addItem("Тёмная", "dark")
        current_theme = controller.settings.get("theme")
        for index in range(self.theme_combo.count()):
            if self.theme_combo.itemData(index) == current_theme:
                self.theme_combo.setCurrentIndex(index)
        self.theme_combo.currentIndexChanged.connect(self._theme_changed)
        theme_row.addWidget(self.theme_combo, 1)
        layout.addLayout(theme_row)

        widget_title = QLabel("Виджет")
        widget_title.setStyleSheet("font-weight: 600;")
        layout.addWidget(widget_title)
        self.widget_check = QCheckBox("Показывать виджет на рабочем столе")
        self.widget_check.setChecked(controller.widget.isVisible())
        self.widget_check.toggled.connect(controller.set_widget_visible)
        self.topmost_check = QCheckBox("Виджет поверх остальных окон")
        self.topmost_check.setChecked(bool(controller.settings.get("widget_topmost")))
        self.topmost_check.toggled.connect(controller.set_topmost)
        layout.addWidget(self.widget_check)
        layout.addWidget(self.topmost_check)

        self.autostart_check = QCheckBox("Запускать MyMusic при входе в Windows")
        self.autostart_check.setChecked(bool(controller.settings.get("autostart")))
        self.autostart_check.toggled.connect(self._autostart_changed)
        layout.addWidget(self.autostart_check)

        data_row = QHBoxLayout()
        open_data = QPushButton("Папка данных")
        open_data.clicked.connect(self._open_data_dir)
        clear_data = QPushButton("Очистить локальные данные…")
        clear_data.clicked.connect(self._clear_data)
        data_row.addWidget(open_data)
        data_row.addWidget(clear_data)
        data_row.addStretch(1)
        layout.addLayout(data_row)
        layout.addStretch(1)

        hint = QLabel("Выход из приложения останавливает звук и завершает процесс. "
                      "Автозапуск включается только вручную.")
        hint.setObjectName("muted")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        close_button = QPushButton("Закрыть")
        close_button.setDefault(True)
        close_button.clicked.connect(self.accept)
        buttons.addWidget(close_button)
        layout.addLayout(buttons)

        controller.provider.provider_status.connect(self.source_status.setText)
        self.source_status.setText("Статус: Audius подключён" if controller.provider_connected
                                   else "Статус: проверяется при поиске")

    def _theme_changed(self) -> None:
        theme = self.theme_combo.currentData()
        self.controller.set_theme(theme)
        apply_theme(self.controller.app, theme)
        self.controller.widget.update()
        self.style().unpolish(self)
        self.style().polish(self)

    def _autostart_changed(self, enabled: bool) -> None:
        ok = self.controller.set_autostart(enabled)
        if not ok:
            self.autostart_check.blockSignals(True)
            self.autostart_check.setChecked(False)
            self.autostart_check.blockSignals(False)

    def _open_data_dir(self) -> None:
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.controller.data_dir)))

    def _clear_data(self) -> None:
        answer = QMessageBox.question(
            self, "Очистить локальные данные",
            "Будут удалены очередь, избранное, настройки и кэш обложек, "
            "автозапуск будет выключен. Продолжить?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if answer != QMessageBox.Yes:
            return
        self.controller.clear_data()
        self.theme_combo.blockSignals(True)
        self.theme_combo.setCurrentIndex(0)
        self.theme_combo.blockSignals(False)
        self.widget_check.blockSignals(True)
        self.widget_check.setChecked(False)
        self.widget_check.blockSignals(False)
        self.topmost_check.blockSignals(True)
        self.topmost_check.setChecked(False)
        self.topmost_check.blockSignals(False)
        self.autostart_check.blockSignals(True)
        self.autostart_check.setChecked(False)
        self.autostart_check.blockSignals(False)
        QMessageBox.information(self, "MyMusic", "Локальные данные очищены.")
