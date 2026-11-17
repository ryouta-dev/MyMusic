"""Основное окно: поиск, результаты, очередь, избранное, панель плеера."""
from __future__ import annotations

from PySide6.QtCore import QSize, Qt, QTimer, QUrl
from PySide6.QtGui import QDesktopServices, QKeySequence, QPixmap, QShortcut
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QLineEdit, QListWidget,
                               QListWidgetItem, QMainWindow, QPushButton, QSizePolicy,
                               QSlider, QTabWidget, QToolButton, QVBoxLayout, QWidget)

from ..domain.models import Availability, PlaybackSnapshot, PlaybackState, Track
from .common import ElidedLabel, format_ms
from .icons import icon

ROW_HEIGHT = 66


class MainWindow(QMainWindow):
    def __init__(self, controller):
        super().__init__()
        self.controller = controller
        self.setWindowTitle("MyMusic")
        self.resize(1000, 700)
        self.setMinimumSize(780, 540)
        self._allow_close = False
        self._seeking = False
        self._current_artwork_url: str | None = None
        self._notice_timer = QTimer(self)
        self._notice_timer.setSingleShot(True)
        self._notice_timer.timeout.connect(self._clear_notice)
        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(350)
        self._search_timer.timeout.connect(self._run_search)
        self._build()
        self._wire()

    # ---- построение ------------------------------------------------------
    def _build(self) -> None:
        root = QWidget()
        self.setCentralWidget(root)
        layout = QVBoxLayout(root)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(10)

        header = QHBoxLayout()
        brand = QLabel("MyMusic")
        brand.setStyleSheet("font-size: 15pt; font-weight: 700;")
        provider = QLabel("Audius · открытый музыкальный каталог")
        provider.setObjectName("muted")
        self.settings_button = QToolButton()
        self.settings_button.setIcon(icon("settings"))
        self.settings_button.setToolTip("Настройки")
        self.settings_button.setAccessibleName("Настройки")
        self.settings_button.setAutoRaise(True)
        self.settings_button.clicked.connect(self.controller.show_settings)
        header.addWidget(brand)
        header.addSpacing(10)
        header.addWidget(provider)
        header.addStretch(1)
        header.addWidget(self.settings_button)
        layout.addLayout(header)

        search_row = QHBoxLayout()
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("Поиск песни или исполнителя")
        self.search_edit.setClearButtonEnabled(True)
        self.search_edit.setAccessibleName("Поиск музыки")
        self.search_edit.textChanged.connect(lambda: self._search_timer.start())
        self.search_edit.returnPressed.connect(self._search_now)
        self.search_button = QPushButton("Найти")
        self.search_button.setObjectName("accent")
        self.search_button.setAccessibleName("Найти")
        self.search_button.clicked.connect(self._search_now)
        search_row.addWidget(self.search_edit, 1)
        search_row.addWidget(self.search_button)
        layout.addLayout(search_row)

        self.notice = QLabel("")
        self.notice.setObjectName("muted")
        self.notice.setWordWrap(True)
        self.notice.setMinimumHeight(18)
        layout.addWidget(self.notice)

        self.tabs = QTabWidget()
        layout.addWidget(self.tabs, 1)

        # Результаты
        results_page = QWidget()
        results_layout = QVBoxLayout(results_page)
        results_layout.setContentsMargins(8, 8, 8, 8)
        results_layout.setSpacing(6)
        state_row = QHBoxLayout()
        self.state_label = QLabel("Введите название песни или исполнителя.")
        self.state_label.setObjectName("muted")
        self.state_label.setWordWrap(True)
        self.retry_button = QPushButton("Повторить")
        self.retry_button.setVisible(False)
        self.retry_button.clicked.connect(self.controller.retry_search)
        state_row.addWidget(self.state_label, 1)
        state_row.addWidget(self.retry_button)
        results_layout.addLayout(state_row)
        self.results_list = QListWidget()
        self.results_list.setAccessibleName("Результаты поиска")
        self.results_list.setVerticalScrollMode(QListWidget.ScrollPerPixel)
        self.results_list.itemDoubleClicked.connect(self._play_result_item)
        results_layout.addWidget(self.results_list, 1)
        self.more_button = QPushButton("Показать ещё 30")
        self.more_button.setVisible(False)
        self.more_button.clicked.connect(self.controller.load_more)
        results_layout.addWidget(self.more_button)
        self.tabs.addTab(results_page, "Результаты")

        # Очередь
        queue_page = QWidget()
        queue_layout = QVBoxLayout(queue_page)
        queue_layout.setContentsMargins(8, 8, 8, 8)
        queue_header = QHBoxLayout()
        self.queue_summary = QLabel("Очередь пуста")
        self.queue_summary.setObjectName("muted")
        self.clear_queue_button = QPushButton("Очистить")
        self.clear_queue_button.setVisible(False)
        self.clear_queue_button.clicked.connect(self.controller.clear_queue)
        queue_header.addWidget(self.queue_summary, 1)
        queue_header.addWidget(self.clear_queue_button)
        queue_layout.addLayout(queue_header)
        self.queue_list = QListWidget()
        self.queue_list.setAccessibleName("Очередь воспроизведения")
        self.queue_list.setVerticalScrollMode(QListWidget.ScrollPerPixel)
        queue_layout.addWidget(self.queue_list, 1)
        self.tabs.addTab(queue_page, "Очередь")

        # Избранное
        fav_page = QWidget()
        fav_layout = QVBoxLayout(fav_page)
        fav_layout.setContentsMargins(8, 8, 8, 8)
        self.favorites_summary = QLabel("Избранное хранится локально")
        self.favorites_summary.setObjectName("muted")
        fav_layout.addWidget(self.favorites_summary)
        self.favorites_list = QListWidget()
        self.favorites_list.setAccessibleName("Избранные треки")
        self.favorites_list.setVerticalScrollMode(QListWidget.ScrollPerPixel)
        fav_layout.addWidget(self.favorites_list, 1)
        self.tabs.addTab(fav_page, "Избранное")

        # Панель плеера
        player_bar = QFrame()
        player_bar.setObjectName("playerBar")
        player_bar.setFixedHeight(88)
        bar = QHBoxLayout(player_bar)
        bar.setContentsMargins(12, 8, 12, 8)
        bar.setSpacing(12)
        self.artwork_label = QLabel()
        self.artwork_label.setFixedSize(58, 58)
        self.artwork_label.setAlignment(Qt.AlignCenter)
        self.artwork_label.setStyleSheet("background: transparent; border-radius: 8px;")
        bar.addWidget(self.artwork_label)

        info = QVBoxLayout()
        info.setSpacing(2)
        self.title_label = ElidedLabel("Ничего не играет")
        self.title_label.setObjectName("title")
        self.artist_label = ElidedLabel("")
        self.artist_label.setObjectName("muted")
        info.addWidget(self.title_label)
        info.addWidget(self.artist_label)
        info.addStretch(1)
        info_widget = QWidget()
        info_widget.setLayout(info)
        info_widget.setMinimumWidth(160)
        info_widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        bar.addWidget(info_widget, 2)

        self.prev_button = QToolButton()
        self.prev_button.setObjectName("transport")
        self.prev_button.setIcon(icon("previous"))
        self.prev_button.setToolTip("Предыдущий трек")
        self.prev_button.setAccessibleName("Предыдущий трек")
        self.prev_button.clicked.connect(self.controller.previous)
        self.play_button = QToolButton()
        self.play_button.setObjectName("primary")
        self.play_button.setIcon(icon("play"))
        self.play_button.setToolTip("Играть")
        self.play_button.setAccessibleName("Играть или пауза")
        self.play_button.clicked.connect(self.controller.toggle_pause)
        self.next_button = QToolButton()
        self.next_button.setObjectName("transport")
        self.next_button.setIcon(icon("next"))
        self.next_button.setToolTip("Следующий трек")
        self.next_button.setAccessibleName("Следующий трек")
        self.next_button.clicked.connect(self.controller.next)
        bar.addWidget(self.prev_button)
        bar.addWidget(self.play_button)
        bar.addWidget(self.next_button)

        progress = QVBoxLayout()
        progress.setSpacing(2)
        self.position_slider = QSlider(Qt.Horizontal)
        self.position_slider.setRange(0, 0)
        self.position_slider.setAccessibleName("Позиция трека")
        self.position_slider.sliderPressed.connect(self._begin_seek)
        self.position_slider.sliderReleased.connect(self._end_seek)
        times = QHBoxLayout()
        self.time_current = QLabel("0:00")
        self.time_total = QLabel("--:--")
        self.time_current.setObjectName("muted")
        self.time_total.setObjectName("muted")
        times.addWidget(self.time_current)
        times.addStretch(1)
        times.addWidget(self.time_total)
        progress.addLayout(times)
        progress.addWidget(self.position_slider)
        progress_widget = QWidget()
        progress_widget.setLayout(progress)
        progress_widget.setMinimumWidth(180)
        bar.addWidget(progress_widget, 3)

        volume_icon = QLabel()
        volume_icon.setPixmap(icon("volume").pixmap(18, 18))
        self.volume_slider = QSlider(Qt.Horizontal)
        self.volume_slider.setRange(0, 100)
        self.volume_slider.setFixedWidth(110)
        self.volume_slider.setAccessibleName("Громкость")
        self.volume_slider.valueChanged.connect(
            lambda value: self.controller.set_volume(value / 100))
        bar.addWidget(volume_icon)
        bar.addWidget(self.volume_slider)
        layout.addWidget(player_bar)

        shortcut = QShortcut(QKeySequence("Ctrl+F"), self)
        shortcut.activated.connect(self._focus_search)
        QShortcut(QKeySequence("Ctrl+P"), self).activated.connect(self.controller.toggle_pause)
        QShortcut(QKeySequence("Ctrl+Right"), self).activated.connect(self.controller.next)
        QShortcut(QKeySequence("Ctrl+Left"), self).activated.connect(self.controller.previous)

    def _wire(self) -> None:
        self.controller.search.results_changed.connect(self._on_results)
        self.controller.search.state_changed.connect(self._on_search_state)
        self.controller.search.has_more_changed.connect(self.more_button.setVisible)
        self.controller.player.snapshot_changed.connect(self.update_snapshot)
        self.controller.player.queue_changed.connect(self.refresh_queue)
        self.controller.player.favorites_changed.connect(self._on_favorites_changed)
        self.controller.player.notice.connect(self.show_notice)
        self.controller.artwork.ready.connect(self._on_artwork_ready)
        snapshot = self.controller.player_snapshot()
        self.update_snapshot(snapshot)
        self.refresh_queue()
        self._refresh_favorites()

    # ---- поиск -----------------------------------------------------------
    def _focus_search(self) -> None:
        self.search_edit.setFocus()
        self.search_edit.selectAll()

    def _run_search(self) -> None:
        self.controller.search_music(self.search_edit.text())

    def _search_now(self) -> None:
        self._search_timer.stop()
        self.controller.search_music(self.search_edit.text())

    def _on_search_state(self, state: str, message: str, can_retry: bool) -> None:
        self.state_label.setText(message)
        self.state_label.setObjectName("danger" if state == "error" else "muted")
        self.state_label.style().unpolish(self.state_label)
        self.state_label.style().polish(self.state_label)
        self.retry_button.setVisible(can_retry)
        if state == "loading":
            self.search_button.setEnabled(False)
        else:
            self.search_button.setEnabled(True)

    def _on_results(self, tracks: list[Track]) -> None:
        self.results_list.clear()
        favorites = self.controller.player.favorites
        for index, track in enumerate(tracks):
            row = self._build_track_row(
                track,
                primary=lambda _=False, i=index: self.controller.play_result(i),
                on_add=lambda _=False, t=track: self.controller.add_track(t),
                favorite=track.key in favorites,
                on_favorite=lambda _=False, t=track: self.controller.toggle_favorite(t))
            item = QListWidgetItem()
            item.setSizeHint(QSize(0, ROW_HEIGHT))
            item.setData(Qt.UserRole, index)
            self.results_list.addItem(item)
            self.results_list.setItemWidget(item, row)

    def _play_result_item(self, item: QListWidgetItem) -> None:
        index = item.data(Qt.UserRole)
        if isinstance(index, int):
            self.controller.play_result(index)

    # ---- очередь ---------------------------------------------------------
    def refresh_queue(self) -> None:
        self.queue_list.clear()
        player = self.controller.player
        entries = player.queue.entries
        self.queue_summary.setText(
            f"Треков в очереди: {len(entries)}" if entries else "Очередь пуста")
        self.clear_queue_button.setVisible(bool(entries))
        for index, entry in enumerate(entries):
            track = entry.track
            is_current = entry.entry_id == player.queue.current_entry_id
            state_text = " · выбран" if is_current else ""
            row = self._build_track_row(
                track,
                subtitle_prefix=state_text,
                primary=lambda _=False, e=entry.entry_id: self.controller.play_entry(e),
                on_remove=lambda _=False, e=entry.entry_id: self.controller.remove_entry(e),
                on_up=(lambda _=False, i=index: self.controller.move_entry(i, i - 1))
                if index > 0 else None,
                on_down=(lambda _=False, i=index: self.controller.move_entry(i, i + 1))
                if index < len(entries) - 1 else None,
                highlight=is_current)
            item = QListWidgetItem()
            item.setSizeHint(QSize(0, ROW_HEIGHT))
            self.queue_list.addItem(item)
            self.queue_list.setItemWidget(item, row)

    # ---- избранное -------------------------------------------------------
    def _on_favorites_changed(self) -> None:
        self._refresh_favorites()
        self._on_results(self.controller.search.tracks)

    def _refresh_favorites(self) -> None:
        self.favorites_list.clear()
        favorites = self.controller.player_favorites()
        self.favorites_summary.setText(
            f"Избранных треков: {len(favorites)}" if favorites
            else "Избранное пусто. Нажмите ☆ у трека.")
        for index, track in enumerate(favorites):
            row = self._build_track_row(
                track,
                primary=lambda _=False, i=index: self.controller.play_favorite(i),
                on_add=lambda _=False, t=track: self.controller.add_track(t),
                favorite=True,
                on_favorite=lambda _=False, t=track: self.controller.toggle_favorite(t))
            item = QListWidgetItem()
            item.setSizeHint(QSize(0, ROW_HEIGHT))
            self.favorites_list.addItem(item)
            self.favorites_list.setItemWidget(item, row)

    # ---- строка трека ----------------------------------------------------
    def _build_track_row(self, track: Track, primary, on_add=None, on_remove=None,
                         on_up=None, on_down=None, favorite: bool = False,
                         on_favorite=None, subtitle_prefix: str = "",
                         highlight: bool = False) -> QWidget:
        row = QWidget()
        row.setMinimumHeight(ROW_HEIGHT - 2)
        layout = QHBoxLayout(row)
        layout.setContentsMargins(10, 6, 8, 6)
        layout.setSpacing(8)
        text = QVBoxLayout()
        text.setSpacing(1)
        title_line = QHBoxLayout()
        title_line.setSpacing(8)
        title = ElidedLabel(track.title)
        title.setObjectName("title")
        title_line.addWidget(title, 1)
        if highlight:
            badge = QLabel("Сейчас")
            badge.setObjectName("accentBadge")
            title_line.addWidget(badge, 0)
        text.addLayout(title_line)
        subtitle_bits = [track.artist, format_ms(track.duration_ms), "Audius"]
        if track.availability == Availability.PREVIEW:
            subtitle_bits.append("только фрагмент")
        elif track.availability == Availability.UNAVAILABLE:
            subtitle_bits.append("недоступен")
        subtitle = ElidedLabel(" · ".join(subtitle_bits) + subtitle_prefix)
        subtitle.setObjectName("muted")
        text.addWidget(subtitle)
        layout.addLayout(text, 1)

        def button(name: str, tooltip: str, callback, enabled: bool = True) -> QToolButton:
            btn = QToolButton()
            btn.setIcon(icon(name))
            btn.setToolTip(tooltip)
            btn.setAccessibleName(tooltip)
            btn.setEnabled(enabled)
            btn.setCursor(Qt.PointingHandCursor)
            if callback is not None:
                btn.clicked.connect(callback)
            layout.addWidget(btn)
            return btn

        play_enabled = track.availability != Availability.UNAVAILABLE
        button("play", "Играть трек" if play_enabled else "Трек недоступен",
               primary, play_enabled)
        if on_add is not None:
            button("add", "Добавить в очередь", on_add, play_enabled)
        if on_up is not None:
            button("up", "Переместить выше", on_up)
        if on_down is not None:
            button("down", "Переместить ниже", on_down)
        if on_favorite is not None:
            button("star" if favorite else "star_outline",
                   "Убрать из избранного" if favorite else "Добавить в избранное",
                   on_favorite)
        if on_remove is not None:
            button("trash", "Удалить из очереди", on_remove)
        return row

    # ---- состояние плеера ------------------------------------------------
    def update_snapshot(self, snapshot: PlaybackSnapshot) -> None:
        track = snapshot.track
        if track is not None:
            self.title_label.setText(track.title)
            self.artist_label.setText(track.artist + " · Audius")
            if track.artwork_url and track.artwork_url != self._current_artwork_url:
                self._current_artwork_url = track.artwork_url
                cached = self.controller.artwork.cached_path(track.artwork_url)
                if cached:
                    self._set_artwork(cached)
                else:
                    self.artwork_label.setPixmap(icon("music").pixmap(48, 48))
                    self.controller.artwork.request(track.artwork_url)
            elif not track.artwork_url:
                self._current_artwork_url = None
                self.artwork_label.setPixmap(icon("music").pixmap(48, 48))
        else:
            self.title_label.setText("Ничего не играет")
            self.artist_label.setText("")
            self.artwork_label.setPixmap(icon("music").pixmap(48, 48))
            self._current_artwork_url = None

        if snapshot.state == PlaybackState.PLAYING:
            self.play_button.setIcon(icon("pause"))
            self.play_button.setToolTip("Пауза")
        elif snapshot.state == PlaybackState.ERROR:
            self.play_button.setIcon(icon("play"))
            self.play_button.setToolTip("Повторить")
        else:
            self.play_button.setIcon(icon("play"))
            self.play_button.setToolTip("Играть")

        self.play_button.setEnabled(True)
        self.prev_button.setEnabled(snapshot.queue_count > 0)
        self.next_button.setEnabled(snapshot.queue_count > 0)

        duration = snapshot.duration_ms or 0
        self.position_slider.setRange(0, max(duration, 0))
        if not self._seeking:
            self.position_slider.setValue(max(0, min(snapshot.position_ms, duration)))
            self.time_current.setText(format_ms(snapshot.position_ms))
        self.time_total.setText(format_ms(snapshot.duration_ms))
        if self.volume_slider.value() != int(round(snapshot.volume * 100)):
            self.volume_slider.blockSignals(True)
            self.volume_slider.setValue(int(round(snapshot.volume * 100)))
            self.volume_slider.blockSignals(False)
        if snapshot.error:
            self.show_notice(snapshot.error, error=True)
        self.setWindowTitle(
            f"{track.title} — MyMusic" if track else "MyMusic")

    def _set_artwork(self, path: str) -> None:
        pixmap = QPixmap(path)
        if pixmap.isNull():
            return
        pixmap = pixmap.scaled(58, 58, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
        self.artwork_label.setPixmap(pixmap)

    def _on_artwork_ready(self, url: str, path: str) -> None:
        if url == self._current_artwork_url:
            self._set_artwork(path)

    def _begin_seek(self) -> None:
        self._seeking = True

    def _end_seek(self) -> None:
        self._seeking = False
        self.controller.seek(self.position_slider.value())

    # ---- уведомления -----------------------------------------------------
    def show_notice(self, message: str, error: bool = False) -> None:
        self.notice.setText(message)
        self.notice.setObjectName("danger" if error else "muted")
        self.notice.style().unpolish(self.notice)
        self.notice.style().polish(self.notice)
        self._notice_timer.start(6000 if error else 4000)

    def _clear_notice(self) -> None:
        self.notice.setText("")

    # ---- окно ------------------------------------------------------------
    def open_source_page(self, track: Track) -> None:
        if track.source_page_url:
            QDesktopServices.openUrl(QUrl(track.source_page_url))

    def closeEvent(self, event) -> None:  # noqa: N802
        if self._allow_close:
            self.controller.player.shutdown()
            event.accept()
            return
        event.ignore()
        self.hide()
        self.controller.on_main_hidden()

    def close_for_quit(self) -> None:
        self._allow_close = True
        self.close()
