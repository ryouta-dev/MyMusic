"""Единый владелец состояния воспроизведения и очереди."""
from __future__ import annotations

import logging

from PySide6.QtCore import QObject, QTimer, Signal

from ..domain.models import (Availability, ErrorKind, PlaybackSnapshot, PlaybackState,
                             ProviderError, Track)
from ..domain.queue import QueueModel
from ..providers.audius import AudiusClient
from ..storage.repository import Repository

log = logging.getLogger(__name__)


class PlayerController(QObject):
    snapshot_changed = Signal(object)
    queue_changed = Signal()
    favorites_changed = Signal()
    notice = Signal(str)

    def __init__(self, repository: Repository, provider: AudiusClient, backend,
                 settings, parent=None):
        super().__init__(parent)
        self.repository = repository
        self.provider = provider
        self.backend = backend
        self.settings = settings
        self.queue = QueueModel()
        self.state = PlaybackState.IDLE
        self.error_message: str | None = None
        self._generation = 0
        self._position_ms = 0
        self._duration_ms: int | None = None
        self._volume = float(settings.get("volume"))
        self._ui_visible = True
        self._advancing = False
        self._resume_at: int | None = None
        self._favorites: set[tuple[str, str]] = set()

        self._ui_timer = QTimer(self)
        self._ui_timer.setInterval(500)
        self._ui_timer.timeout.connect(self._emit_snapshot)
        self._save_timer = QTimer(self)
        self._save_timer.setInterval(15_000)
        self._save_timer.timeout.connect(self._save_position)
        self._volume_save_timer = QTimer(self)
        self._volume_save_timer.setSingleShot(True)
        self._volume_save_timer.setInterval(600)
        self._volume_save_timer.timeout.connect(self._persist_volume)

        provider.resolve_done.connect(self._on_resolved)
        provider.resolve_failed.connect(self._on_resolve_failed)
        backend.playing.connect(self._on_playing)
        backend.paused.connect(self._on_paused)
        backend.stopped.connect(self._on_stopped)
        backend.ended.connect(self._on_ended)
        backend.error.connect(self._on_backend_error)
        backend.position_changed.connect(self._on_position)
        backend.duration_changed.connect(self._on_duration)
        backend.set_volume(self._volume)

    # ---- восстановление -------------------------------------------------
    def restore(self) -> None:
        entries, current, position = self.repository.load_queue()
        self.queue._entries = list(entries)
        self.queue.current_entry_id = current
        self._favorites = self.repository.favorite_keys()
        self._position_ms = position if current else 0
        self._resume_at = self._position_ms or None
        track = self.queue.current_entry.track if self.queue.current_entry else None
        self._duration_ms = track.duration_ms if track else None
        self.state = PlaybackState.PAUSED if track else PlaybackState.IDLE
        self.favorites_changed.emit()
        self.queue_changed.emit()
        self._emit_snapshot()

    # ---- поиск/очередь ---------------------------------------------------
    def play_from_results(self, tracks: list[Track], start_index: int) -> None:
        if not tracks:
            return
        self._resume_at = None
        self.queue.replace(list(tracks), start_index)
        self._save_queue()
        self.queue_changed.emit()
        self._play_current()

    def play_entry(self, entry_id: str) -> None:
        if self.queue.select(entry_id) is None:
            return
        self._resume_at = None
        self._save_queue()
        self.queue_changed.emit()
        self._play_current()

    def add_to_queue(self, track: Track) -> None:
        self.queue.add(track)
        self._save_queue()
        self.queue_changed.emit()
        self.notice.emit("Трек добавлен в конец очереди.")

    def remove_entry(self, entry_id: str) -> None:
        was_current, next_entry = self.queue.remove(entry_id)
        if was_current:
            self._stop_backend()
            self._generation += 1
            self._position_ms = 0
            self.error_message = None
            if next_entry is not None:
                self.state = PlaybackState.PAUSED
                self._duration_ms = next_entry.track.duration_ms
                self.notice.emit("Текущий трек удалён. Следующий выбран на паузе.")
            else:
                self.state = PlaybackState.IDLE
                self._duration_ms = None
        self._save_queue()
        self.queue_changed.emit()
        self._emit_snapshot()

    def move_entry(self, source_index: int, target_index: int) -> None:
        if self.queue.move(source_index, target_index):
            self._save_queue()
            self.queue_changed.emit()
            self._emit_snapshot()

    def clear_queue(self) -> None:
        self._generation += 1
        self._resume_at = None
        self._stop_backend()
        self.queue._entries.clear()
        self.queue.current_entry_id = None
        self.state = PlaybackState.IDLE
        self.error_message = None
        self._position_ms = 0
        self._duration_ms = None
        self._save_queue()
        self.queue_changed.emit()
        self._emit_snapshot()

    # ---- избранное -------------------------------------------------------
    @property
    def favorites(self) -> set[tuple[str, str]]:
        return set(self._favorites)

    def is_favorite(self, track: Track) -> bool:
        return track.key in self._favorites

    def toggle_favorite(self, track: Track) -> None:
        favorite = track.key not in self._favorites
        self.repository.set_favorite(track, favorite)
        if favorite:
            self._favorites.add(track.key)
        else:
            self._favorites.discard(track.key)
        self.favorites_changed.emit()
        self.notice.emit("Добавлено в избранное." if favorite else "Удалено из избранного.")

    def clear_favorites(self) -> None:
        self.repository.clear_favorites()
        self._favorites.clear()
        self.favorites_changed.emit()

    # ---- управление транспортом -----------------------------------------
    def toggle_pause(self) -> None:
        if self.state == PlaybackState.PLAYING:
            self.backend.pause()
            return
        if self.state == PlaybackState.BUFFERING:
            self.notice.emit("Трек загружается…")
            return
        if self.state == PlaybackState.RESOLVING:
            self.notice.emit("Источник готовит поток…")
            return
        if self.state == PlaybackState.PAUSED:
            if self.backend.has_source():
                self.state = PlaybackState.BUFFERING
                self._emit_snapshot()
                self.backend.play()
            else:
                self._play_current()
            return
        if self.state in (PlaybackState.IDLE, PlaybackState.ENDED, PlaybackState.ERROR):
            if self.queue.current_entry is not None:
                self._play_current()

    def next(self) -> None:
        entry = self.queue.next_entry()
        if entry is None:
            self._stop_to_idle("Очередь закончилась.")
            return
        self._resume_at = None
        self.queue.select(entry.entry_id)
        self._save_queue()
        self.queue_changed.emit()
        self._play_current()

    def previous(self) -> None:
        if self._position_ms >= 3000 and self.state in (
                PlaybackState.PLAYING, PlaybackState.PAUSED, PlaybackState.BUFFERING):
            self.backend.seek(0)
            self._position_ms = 0
            self._emit_snapshot()
            return
        entry = self.queue.previous_entry()
        if entry is None:
            if self.queue.current_entry is not None:
                self.backend.seek(0)
                self._position_ms = 0
                self._emit_snapshot()
            return
        self._resume_at = None
        self.queue.select(entry.entry_id)
        self._save_queue()
        self.queue_changed.emit()
        self._play_current()

    def seek_to(self, position_ms: int) -> None:
        if self.state not in (PlaybackState.PLAYING, PlaybackState.PAUSED,
                              PlaybackState.BUFFERING):
            return
        maximum = self._duration_ms or self.backend.duration()
        position = max(0, min(int(position_ms), maximum if maximum > 0 else int(position_ms)))
        self.backend.seek(position)
        self._position_ms = position
        self._emit_snapshot()

    def set_volume(self, volume: float) -> None:
        self._volume = min(1.0, max(0.0, float(volume)))
        self.backend.set_volume(self._volume)
        self.settings.set("volume", round(self._volume, 3))
        self._volume_save_timer.start()
        self._emit_snapshot()

    def _persist_volume(self) -> None:
        self.settings.save()

    def stop_for_suspend(self) -> None:
        if self.state in (PlaybackState.PLAYING, PlaybackState.BUFFERING):
            self.backend.pause()
            self._save_position()
            self.notice.emit("ПК уходит в сон: воспроизведение приостановлено.")

    def handle_resume(self) -> None:
        self._generation += 1
        self._stop_backend()
        if self.queue.current_entry is not None:
            self.state = PlaybackState.PAUSED
            self.notice.emit("ПК вернулся из сна. Нажмите «Играть», чтобы продолжить.")
        else:
            self.state = PlaybackState.IDLE
        self._emit_snapshot()

    def set_ui_visible(self, visible: bool) -> None:
        self._ui_visible = visible
        if not visible:
            self._ui_timer.stop()
        elif self.state == PlaybackState.PLAYING:
            self._ui_timer.start()

    # ---- внутреннее ------------------------------------------------------
    def _play_current(self) -> None:
        entry = self.queue.current_entry
        if entry is None:
            self._stop_to_idle()
            return
        track = entry.track
        if track.availability == Availability.UNAVAILABLE:
            self._generation += 1
            self._stop_backend()
            self.state = PlaybackState.ERROR
            self.error_message = "Этот трек недоступен у источника. Выберите другой."
            self._position_ms = 0
            self._emit_snapshot()
            return
        self._generation += 1
        generation = self._generation
        self._stop_backend()
        self.state = PlaybackState.RESOLVING
        self.error_message = None
        self._position_ms = 0
        self._duration_ms = track.duration_ms
        self._emit_snapshot()
        log.info("resolve requested kind=%s", track.availability.value)
        self.provider.resolve(track.ref, generation)

    def _on_resolved(self, generation: int, handle) -> None:
        if generation != self._generation or self.state == PlaybackState.SHUTTING_DOWN:
            return
        resume = self._resume_at or 0
        self._resume_at = None
        self.backend.load(handle.url)
        if resume > 0:
            self.backend.seek(resume)
            self._position_ms = resume
        self.state = PlaybackState.BUFFERING
        self._emit_snapshot()
        self.backend.play()

    def _on_resolve_failed(self, generation: int, error: ProviderError) -> None:
        if generation != self._generation or self.state == PlaybackState.SHUTTING_DOWN:
            return
        if error.kind == ErrorKind.CANCELLED:
            return
        self.state = PlaybackState.ERROR
        self.error_message = error.user_message
        log.warning("resolve failed kind=%s", error.kind.value)
        self._emit_snapshot()

    def _on_playing(self) -> None:
        if self.state in (PlaybackState.SHUTTING_DOWN, PlaybackState.ERROR):
            return
        self.state = PlaybackState.PLAYING
        self.error_message = None
        if self._ui_visible:
            self._ui_timer.start()
        self._save_timer.start()
        self._save_position()
        self._emit_snapshot()

    def _on_paused(self) -> None:
        if self.state == PlaybackState.SHUTTING_DOWN:
            return
        self.state = PlaybackState.PAUSED
        self._ui_timer.stop()
        self._save_timer.stop()
        self._save_position()
        self._emit_snapshot()

    def _on_stopped(self) -> None:
        if self.state in (PlaybackState.PLAYING, PlaybackState.BUFFERING):
            self.state = PlaybackState.PAUSED
            self._ui_timer.stop()
            self._save_timer.stop()
            self._save_position()
            self._emit_snapshot()

    def _on_ended(self) -> None:
        if self.state in (PlaybackState.SHUTTING_DOWN, PlaybackState.ERROR):
            return
        if self._advancing:
            return
        self._advancing = True
        try:
            entry = self.queue.next_entry()
            if entry is None:
                self._stop_to_idle("Очередь закончилась.")
            else:
                self.queue.select(entry.entry_id)
                self._save_queue()
                self.queue_changed.emit()
                self._play_current()
        finally:
            self._advancing = False

    def _on_backend_error(self, message: str) -> None:
        if self.state in (PlaybackState.SHUTTING_DOWN, PlaybackState.RESOLVING):
            return
        self.state = PlaybackState.ERROR
        self.error_message = message
        self._ui_timer.stop()
        self._save_timer.stop()
        self._save_position()
        log.warning("backend error")
        self._emit_snapshot()

    def _on_position(self, position: int) -> None:
        if self.state in (PlaybackState.PLAYING, PlaybackState.BUFFERING,
                          PlaybackState.PAUSED):
            self._position_ms = int(position)

    def _on_duration(self, duration: int) -> None:
        if duration > 0:
            self._duration_ms = int(duration)
            self._emit_snapshot()

    def _stop_to_idle(self, message: str | None = None) -> None:
        self._generation += 1
        self._resume_at = None
        self._stop_backend()
        self.state = PlaybackState.IDLE
        self._position_ms = 0
        self.error_message = None
        self._ui_timer.stop()
        self._save_timer.stop()
        self._save_queue()
        if message:
            self.notice.emit(message)
        self._emit_snapshot()

    def _stop_backend(self) -> None:
        self.backend.stop()

    def _save_queue(self) -> None:
        try:
            self.repository.save_queue(list(self.queue.entries),
                                       self.queue.current_entry_id, self._position_ms)
        except Exception:
            log.exception("failed to persist queue")

    def _save_position(self) -> None:
        try:
            self.repository.save_session(self.queue.current_entry_id, self._position_ms)
        except Exception:
            log.exception("failed to persist position")

    def _emit_snapshot(self) -> None:
        self.snapshot_changed.emit(self.snapshot())

    def snapshot(self) -> PlaybackSnapshot:
        entry = self.queue.current_entry
        track = entry.track if entry else None
        return PlaybackSnapshot(
            state=self.state,
            track=track,
            position_ms=self._position_ms,
            duration_ms=self._duration_ms,
            volume=self._volume,
            can_seek=True,
            error=self.error_message,
            queue_count=len(self.queue),
            queue_index=self.queue.current_index,
        )

    def shutdown(self) -> None:
        self.state = PlaybackState.SHUTTING_DOWN
        self._generation += 1
        self._ui_timer.stop()
        self._save_timer.stop()
        self.provider.cancel_all()
        self._save_queue()
        self.backend.release()
        self.repository.close()
