"""Компактный перемещаемый виджет управления воспроизведением (360x112)."""
from __future__ import annotations

from PySide6.QtCore import QPoint, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPixmap
from PySide6.QtWidgets import (QApplication, QHBoxLayout, QLabel, QToolButton,
                               QVBoxLayout, QWidget)

from ..domain.models import PlaybackSnapshot, PlaybackState
from .common import ElidedLabel
from .icons import icon

WIDGET_SIZE = (360, 112)


class MiniPlayer(QWidget):
    def __init__(self, controller):
        super().__init__()
        self.controller = controller
        self._drag_offset: QPoint | None = None
        self._current_artwork_url: str | None = None
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setFixedSize(*WIDGET_SIZE)
        self.setWindowTitle("MyMusic — виджет")
        self._build()
        self._wire()

    def _build(self) -> None:
        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 12, 12, 12)
        layout.setSpacing(12)
        self.artwork = QLabel()
        self.artwork.setFixedSize(56, 56)
        self.artwork.setAlignment(Qt.AlignCenter)
        self.artwork.setPixmap(icon("music").pixmap(44, 44))
        layout.addWidget(self.artwork)

        info = QVBoxLayout()
        info.setSpacing(2)
        self.title_label = ElidedLabel("Ничего не играет")
        self.title_label.setStyleSheet("font-size: 10.5pt; font-weight: 600;")
        self.artist_label = ElidedLabel("")
        self.artist_label.setObjectName("muted")
        info.addWidget(self.title_label)
        info.addWidget(self.artist_label)
        info.addStretch(1)
        self.controls = QHBoxLayout()
        self.controls.setSpacing(4)
        self.prev_button = self._button("previous", "Предыдущий трек", self.controller.previous)
        self.play_button = self._button("play", "Играть", self.controller.toggle_pause)
        self.next_button = self._button("next", "Следующий трек", self.controller.next)
        self.controls.addWidget(self.prev_button)
        self.controls.addWidget(self.play_button)
        self.controls.addWidget(self.next_button)
        self.controls.addStretch(1)
        info.addLayout(self.controls)
        layout.addLayout(info, 1)

        side = QVBoxLayout()
        side.setSpacing(4)
        self.open_button = self._button("open", "Открыть основное окно",
                                        self.controller.show_main)
        self.close_button = self._button("close", "Скрыть виджет",
                                         lambda: self.controller.set_widget_visible(False))
        side.addWidget(self.open_button, alignment=Qt.AlignTop | Qt.AlignRight)
        side.addStretch(1)
        side.addWidget(self.close_button, alignment=Qt.AlignBottom | Qt.AlignRight)
        layout.addLayout(side)

    def _button(self, name: str, tooltip: str, callback) -> QToolButton:
        button = QToolButton()
        button.setIcon(icon(name))
        button.setToolTip(tooltip)
        button.setAccessibleName(tooltip)
        button.setAutoRaise(True)
        button.setCursor(Qt.PointingHandCursor)
        button.clicked.connect(lambda _=False: callback())
        return button

    def _wire(self) -> None:
        self.controller.player.snapshot_changed.connect(self.update_snapshot)
        self.controller.artwork.ready.connect(self._on_artwork_ready)
        self.update_snapshot(self.controller.player_snapshot())

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        dark = self.controller.current_theme() == "dark"
        panel = QColor("#212126") if dark else QColor("#ffffff")
        border = QColor("#34343d") if dark else QColor("#d9d9e0")
        painter.setPen(border)
        painter.setBrush(panel)
        painter.drawRoundedRect(QRectF(1, 1, self.width() - 2, self.height() - 2), 16, 16)

    def update_snapshot(self, snapshot: PlaybackSnapshot) -> None:
        track = snapshot.track
        self.title_label.setText(track.title if track else "Ничего не играет")
        self.artist_label.setText(track.artist if track else "")
        if snapshot.state == PlaybackState.PLAYING:
            self.play_button.setIcon(icon("pause"))
            self.play_button.setToolTip("Пауза")
        else:
            self.play_button.setIcon(icon("play"))
            self.play_button.setToolTip("Повторить" if snapshot.state == PlaybackState.ERROR else "Играть")
        enabled = snapshot.queue_count > 0
        self.prev_button.setEnabled(enabled)
        self.next_button.setEnabled(enabled)
        if track and track.artwork_url:
            if track.artwork_url != self._current_artwork_url:
                self._current_artwork_url = track.artwork_url
                cached = self.controller.artwork.cached_path(track.artwork_url)
                if cached:
                    self._set_artwork(cached)
                else:
                    self.artwork.setPixmap(icon("music").pixmap(44, 44))
                    self.controller.artwork.request(track.artwork_url)
        else:
            self._current_artwork_url = None
            self.artwork.setPixmap(icon("music").pixmap(44, 44))

    def _set_artwork(self, path: str) -> None:
        pixmap = QPixmap(path)
        if pixmap.isNull():
            return
        pixmap = pixmap.scaled(56, 56, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
        self.artwork.setPixmap(pixmap)

    def _on_artwork_ready(self, url: str, path: str) -> None:
        if url == self._current_artwork_url:
            self._set_artwork(path)

    # ---- перетаскивание и позиция ---------------------------------------
    def apply_topmost(self, topmost: bool) -> None:
        was_visible = self.isVisible()
        self.setWindowFlag(Qt.WindowStaysOnTopHint, topmost)
        if was_visible:
            self.show()

    def restore_position(self, position) -> None:
        if isinstance(position, (list, tuple)) and len(position) == 2:
            self.move(int(position[0]), int(position[1]))
        self.ensure_on_screen()

    def ensure_on_screen(self) -> None:
        geometry = self.frameGeometry()
        for screen in QApplication.screens():
            if screen.availableGeometry().intersects(geometry):
                return
        primary = QApplication.primaryScreen()
        if primary is not None:
            area = primary.availableGeometry()
            self.move(area.right() - self.width() - 24, area.bottom() - self.height() - 24)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.LeftButton:
            self._drag_offset = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if self._drag_offset is not None and event.buttons() & Qt.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_offset)
            event.accept()

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if self._drag_offset is not None:
            self._drag_offset = None
            self.ensure_on_screen()
            self.controller.save_widget_position(self.pos())
            event.accept()

    def closeEvent(self, event) -> None:  # noqa: N802
        event.ignore()
        self.controller.set_widget_visible(False)
