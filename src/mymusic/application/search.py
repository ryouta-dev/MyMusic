"""Поиск с отменой устаревших запросов и постраничной выдачей."""
from __future__ import annotations

import logging

from PySide6.QtCore import QObject, Signal

from ..domain.models import ProviderError, Track
from ..providers.audius import AudiusClient

log = logging.getLogger(__name__)


class SearchController(QObject):
    results_changed = Signal(object)          # list[Track]
    state_changed = Signal(str, str, bool)    # state, message, can_retry
    has_more_changed = Signal(bool)

    def __init__(self, provider: AudiusClient, parent=None):
        super().__init__(parent)
        self.provider = provider
        self.query = ""
        self.tracks: list[Track] = []
        self.next_offset: int | None = None
        self.state = "idle"
        self.generation = 0
        self._loading_more = False
        self._last_error: ProviderError | None = None
        self._retry_more = False
        provider.search_done.connect(self._on_done)
        provider.search_failed.connect(self._on_failed)

    def start_search(self, query: str) -> None:
        query = query.strip()
        self.generation += 1
        self.query = query
        self.tracks = []
        self.next_offset = None
        self._retry_more = False
        self.results_changed.emit([])
        self.has_more_changed.emit(False)
        if not query:
            self.state = "idle"
            self._loading_more = False
            self.state_changed.emit("idle", "Введите название песни или исполнителя.", False)
            return
        self._loading_more = False
        self.state = "loading"
        self.state_changed.emit("loading", "Поиск…", False)
        self.provider.search(query, 0, self.generation)

    def load_more(self) -> None:
        if self.state == "loading" and not self._loading_more:
            return
        if self.next_offset is None and self._last_error is None:
            return
        if self.state == "error" and not self._retry_more:
            return
        self.generation += 1
        self._loading_more = True
        self.state = "loading"
        self._retry_more = False
        self.state_changed.emit("loading", "Загрузка следующей страницы…", False)
        self.provider.search(self.query, self.next_offset or 0, self.generation)

    def retry(self) -> None:
        if self._retry_more and self.next_offset is not None:
            self.load_more()
        else:
            self.start_search(self.query)

    def _on_done(self, generation: int, page) -> None:
        if generation != self.generation:
            return
        seen = {(t.ref.provider_id, t.ref.track_id) for t in self.tracks}
        fresh = [t for t in page.tracks
                 if (t.ref.provider_id, t.ref.track_id) not in seen]
        if self._loading_more:
            self.tracks.extend(fresh)
        else:
            self.tracks = fresh
        self._loading_more = False
        self.next_offset = page.next_offset
        self.state = "ready" if self.tracks else "empty"
        self.results_changed.emit(list(self.tracks))
        self.has_more_changed.emit(self.next_offset is not None)
        message = "" if self.tracks else "Ничего не найдено. Уточните запрос."
        self.state_changed.emit(self.state, message, False)
        log.info("search completed results=%d more=%s", len(self.tracks),
                 self.next_offset is not None)

    def _on_failed(self, generation: int, error: ProviderError) -> None:
        if generation != self.generation:
            return
        self._last_error = error
        self._retry_more = self._loading_more and bool(self.tracks)
        self._loading_more = False
        self.state = "error"
        self.has_more_changed.emit(self.next_offset is not None)
        self.state_changed.emit("error", error.user_message, True)
        log.warning("search failed kind=%s", error.kind.value)
