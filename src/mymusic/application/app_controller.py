"""Связывает окна, плеер, поиск, хранилище, трей и системные события."""
from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import QObject
from PySide6.QtWidgets import QSystemTrayIcon

from ..domain.models import Track
from ..platform import autostart
from ..platform.power import install as install_power_filter
from ..playback.backend import QtAudioBackend
from ..providers.audius import AudiusClient
from ..storage.repository import Repository
from ..storage.settings import DEFAULTS, Settings
from ..ui.app_tray import Tray
from ..ui.artwork import ArtworkCache
from ..ui.main_window import MainWindow
from ..ui.mini_player import MiniPlayer
from ..ui.settings_dialog import SettingsDialog
from ..ui.theme import apply_theme, resolve_theme
from .player import PlayerController
from .search import SearchController

log = logging.getLogger(__name__)


class ApplicationController(QObject):
    def __init__(self, app, data_dir: Path):
        super().__init__()
        self.app = app
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.settings = Settings(self.data_dir / "settings.json")
        self.repository = Repository(self.data_dir / "library.db")
        self.provider = AudiusClient(self)
        self.backend = QtAudioBackend(self)
        self.player = PlayerController(self.repository, self.provider, self.backend,
                                       self.settings, self)
        self.search = SearchController(self.provider, self)
        self.artwork = ArtworkCache(self.data_dir / "cache" / "artwork", self)
        self.provider_connected = False
        self._quitting = False
        self._shutdown_done = False
        self._power_filter = None

        self.player.restore()
        self.main_window = MainWindow(self)
        self.widget = MiniPlayer(self)
        self.tray = Tray(self)

        apply_theme(self.app, self.settings.get("theme"))
        self.player.snapshot_changed.connect(self.tray.update_snapshot)
        self.provider.provider_status.connect(self._on_provider_status)

        self.main_window.show()
        self.player.set_ui_visible(True)
        if bool(self.settings.get("widget_visible")):
            self.set_widget_visible(True)
        else:
            self.tray.sync_widget(False)

        self._power_filter = install_power_filter(
            self.app, self.player.stop_for_suspend, self._on_resume)
        self.app.aboutToQuit.connect(self._shutdown)

    # ---- прокси для интерфейса ------------------------------------------
    def player_snapshot(self):
        return self.player.snapshot()

    def player_favorites(self) -> list[Track]:
        return self.repository.list_favorites()

    def current_theme(self) -> str:
        return resolve_theme(self.settings.get("theme"))

    def search_music(self, query: str) -> None:
        self.search.start_search(query)

    def load_more(self) -> None:
        self.search.load_more()

    def retry_search(self) -> None:
        self.search.retry()

    def play_result(self, index: int) -> None:
        self.player.play_from_results(list(self.search.tracks), index)

    def play_favorite(self, index: int) -> None:
        favorites = self.player_favorites()
        if 0 <= index < len(favorites):
            self.player.play_from_results(favorites, index)

    def add_track(self, track: Track) -> None:
        self.player.add_to_queue(track)

    def toggle_favorite(self, track: Track) -> None:
        self.player.toggle_favorite(track)

    def play_entry(self, entry_id: str) -> None:
        self.player.play_entry(entry_id)

    def remove_entry(self, entry_id: str) -> None:
        self.player.remove_entry(entry_id)

    def move_entry(self, source: int, target: int) -> None:
        self.player.move_entry(source, target)

    def clear_queue(self) -> None:
        self.player.clear_queue()

    def toggle_pause(self) -> None:
        self.player.toggle_pause()

    def next(self) -> None:
        self.player.next()

    def previous(self) -> None:
        self.player.previous()

    def seek(self, position_ms: int) -> None:
        self.player.seek_to(position_ms)

    def set_volume(self, volume: float) -> None:
        self.player.set_volume(volume)

    # ---- окна и системная интеграция ------------------------------------
    def show_main(self) -> None:
        self.main_window.showNormal()
        self.main_window.raise_()
        self.main_window.activateWindow()
        self._refresh_visibility()

    def on_main_hidden(self) -> None:
        self._refresh_visibility()
        if not bool(self.settings.get("tray_notice_shown")):
            self.tray.showMessage(
                "MyMusic продолжает работать",
                "Окно скрыто в трей. Управление доступно из виджета и меню трея.",
                QSystemTrayIcon.MessageIcon.Information,
                6000)
            self.settings.set("tray_notice_shown", True)
            self.settings.save()

    def toggle_widget(self) -> None:
        self.set_widget_visible(not self.widget.isVisible())

    def set_widget_visible(self, visible: bool) -> None:
        if visible:
            self.widget.restore_position(self.settings.get("widget_position"))
            self.widget.apply_topmost(bool(self.settings.get("widget_topmost")))
            self.widget.show()
            self.widget.raise_()
        else:
            self.widget.hide()
        self.settings.set("widget_visible", bool(visible))
        self.settings.save()
        self.tray.sync_widget(bool(visible))
        self._refresh_visibility()

    def save_widget_position(self, position) -> None:
        self.settings.set("widget_position", [int(position.x()), int(position.y())])
        self.settings.save()

    def set_topmost(self, topmost: bool) -> None:
        self.settings.set("widget_topmost", bool(topmost))
        self.settings.save()
        self.widget.apply_topmost(bool(topmost))

    def set_theme(self, name: str) -> None:
        self.settings.set("theme", name)
        self.settings.save()
        apply_theme(self.app, name)
        self.widget.update()

    def set_autostart(self, enabled: bool) -> bool:
        try:
            autostart.set_enabled(bool(enabled))
        except OSError as error:
            log.warning("autostart update failed: %s", error.__class__.__name__)
            self.main_window.show_notice(
                "Не удалось изменить автозапуск. Проверьте права пользователя.", error=True)
            return False
        self.settings.set("autostart", bool(enabled))
        self.settings.save()
        return True

    def show_settings(self) -> None:
        dialog = SettingsDialog(self)
        dialog.exec()

    def clear_data(self) -> None:
        self.player.clear_queue()
        self.player.clear_favorites()
        self.player.set_volume(DEFAULTS["volume"])
        self.repository.clear_all()
        self.settings.values = dict(DEFAULTS)
        self.settings.save()
        try:
            if autostart.is_enabled():
                autostart.set_enabled(False)
        except OSError:
            pass
        for path in (self.data_dir / "cache" / "artwork").glob("*.jpg"):
            try:
                path.unlink()
            except OSError:
                pass
        if self.widget.isVisible():
            self.set_widget_visible(False)
        self.main_window.search_edit.clear()
        apply_theme(self.app, self.settings.get("theme"))
        self.widget.update()
        self.main_window.show_notice("Локальные данные очищены.")
        log.info("local data cleared")

    def _refresh_visibility(self) -> None:
        self.player.set_ui_visible(
            self.main_window.isVisible() or self.widget.isVisible())

    def _on_provider_status(self, status: str) -> None:
        self.provider_connected = "подключено" in status

    def _on_resume(self) -> None:
        self.player.handle_resume()

    # ---- завершение ------------------------------------------------------
    def quit(self) -> None:
        if self._quitting:
            return
        self._quitting = True
        self._shutdown()
        self.app.quit()

    def _shutdown(self) -> None:
        if self._shutdown_done:
            return
        self._shutdown_done = True
        self.player.shutdown()
        self.tray.hide()
        self.widget.hide()
        self.main_window._allow_close = True
        self.main_window.hide()
        log.info("shutdown complete")
