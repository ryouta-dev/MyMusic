"""Фейки провайдера, backend и хранилища для детерминированных тестов."""
from __future__ import annotations

from PySide6.QtCore import QObject, Signal

from mymusic.domain.models import Availability, PlaybackHandle, Track, TrackRef
from mymusic.storage.settings import DEFAULTS


def make_track(number: int, availability: Availability = Availability.FULL,
               title: str | None = None) -> Track:
    return Track(
        ref=TrackRef("audius", f"track-{number}"),
        title=title or f"Трек {number}",
        artist=f"Исполнитель {number}",
        duration_ms=180_000,
        availability=availability,
    )


class FakeSettings:
    def __init__(self, **overrides):
        self.values = dict(DEFAULTS)
        self.values.update(overrides)
        self.save_calls = 0

    def get(self, key):
        return self.values.get(key, DEFAULTS.get(key))

    def set(self, key, value):
        self.values[key] = value

    def save(self):
        self.save_calls += 1


class FakeRepository:
    def __init__(self, entries=None, current_entry_id=None, position_ms=0):
        self.entries = list(entries or [])
        self.current_entry_id = current_entry_id
        self.position_ms = position_ms
        self.favorites: set[tuple[str, str]] = set()
        self.saved_queues: list[tuple] = []
        self.saved_sessions: list[tuple] = []
        self.closed = False

    def load_queue(self):
        return list(self.entries), self.current_entry_id, self.position_ms

    def save_queue(self, entries, current_entry_id, position_ms):
        self.entries = list(entries)
        self.current_entry_id = current_entry_id
        self.position_ms = position_ms
        self.saved_queues.append((list(entries), current_entry_id, position_ms))

    def save_session(self, current_entry_id, position_ms):
        self.current_entry_id = current_entry_id
        self.position_ms = position_ms
        self.saved_sessions.append((current_entry_id, position_ms))

    def favorite_keys(self):
        return set(self.favorites)

    def set_favorite(self, track, favorite: bool):
        if favorite:
            self.favorites.add(track.key)
        else:
            self.favorites.discard(track.key)

    def clear_favorites(self):
        self.favorites.clear()

    def close(self):
        self.closed = True


class FakeProvider(QObject):
    """Провайдер, который не ходит в сеть; ответы эмитируются вручную."""
    search_done = Signal(int, object)
    search_failed = Signal(int, object)
    resolve_done = Signal(int, object)
    resolve_failed = Signal(int, object)
    provider_status = Signal(str)

    def __init__(self, auto_resolve: bool = True, auto_fail=None):
        super().__init__()
        self.auto_resolve = auto_resolve
        self.auto_fail = auto_fail
        self.searches: list[tuple] = []
        self.resolves: list[tuple] = []
        self.cancel_calls = 0

    def search(self, query, offset, generation, limit=30):
        self.searches.append((query, offset, generation, limit))

    def resolve(self, track_ref, generation):
        self.resolves.append((track_ref, generation))
        if self.auto_fail is not None:
            self.resolve_failed.emit(generation, self.auto_fail)
        elif self.auto_resolve:
            handle = PlaybackHandle(url=f"https://media.example/{track_ref.track_id}.mp3")
            self.resolve_done.emit(generation, handle)

    def cancel_all(self):
        self.cancel_calls += 1


class FakeBackend(QObject):
    playing = Signal()
    paused = Signal()
    stopped = Signal()
    buffering = Signal()
    position_changed = Signal("qlonglong")
    duration_changed = Signal("qlonglong")
    ended = Signal()
    error = Signal(str)

    def __init__(self):
        super().__init__()
        self.loaded_urls: list[str] = []
        self.seeks: list[int] = []
        self.volumes: list[float] = []
        self.play_calls = 0
        self.pause_calls = 0
        self.stop_calls = 0
        self.release_calls = 0
        self.has_media = False
        self.current_duration_ms = 0

    def load(self, url):
        self.loaded_urls.append(url)
        self.has_media = True

    def play(self):
        self.play_calls += 1
        self.playing.emit()

    def pause(self):
        self.pause_calls += 1
        self.paused.emit()

    def stop(self):
        self.stop_calls += 1
        self.has_media = False
        self.stopped.emit()

    def seek(self, position):
        self.seeks.append(int(position))

    def set_volume(self, volume):
        self.volumes.append(float(volume))

    def duration(self):
        return self.current_duration_ms

    def has_source(self):
        return self.has_media

    def release(self):
        self.release_calls += 1
        self.has_media = False
