"""Поиск: отмена устаревших ответов, пагинация без дублей, ошибки и retry."""
from __future__ import annotations

import unittest

from PySide6.QtCore import QCoreApplication

from mymusic.application.search import SearchController
from mymusic.domain.models import ErrorKind, ProviderError, SearchPage

from .support import FakeProvider, make_track


def ensure_app():
    return QCoreApplication.instance() or QCoreApplication([])


class SearchControllerTests(unittest.TestCase):
    def setUp(self):
        ensure_app()
        self.provider = FakeProvider(auto_resolve=False)
        self.search = SearchController(self.provider)
        self.states: list[tuple[str, str, bool]] = []
        self.results: list[list] = []
        self.has_more: list[bool] = []
        self.search.state_changed.connect(
            lambda state, message, retry: self.states.append((state, message, retry)))
        self.search.results_changed.connect(lambda tracks: self.results.append(list(tracks)))
        self.search.has_more_changed.connect(self.has_more.append)

    def start(self, query="daft punk"):
        self.search.start_search(query)
        return self.provider.searches[-1]

    def test_empty_query_is_idle(self):
        self.search.start_search("   ")
        self.assertEqual(self.search.state, "idle")
        self.assertEqual(self.provider.searches, [])
        self.assertEqual(self.states[-1][0], "idle")

    def test_start_search_cancels_previous_generation(self):
        query, offset, first_generation, limit = self.start("daft")
        self.assertEqual((query, offset, limit), ("daft", 0, 30))
        self.assertEqual(self.search.state, "loading")
        self.assertEqual(self.results[-1], [])

        _, _, second_generation, _ = self.start("daft punk")
        self.assertGreater(second_generation, first_generation)

        stale = SearchPage([make_track(1)], 30)
        self.provider.search_done.emit(first_generation, stale)
        self.assertEqual(self.search.tracks, [])
        self.assertEqual(self.search.state, "loading")

        fresh = SearchPage([make_track(2), make_track(3)], 30)
        self.provider.search_done.emit(second_generation, fresh)
        self.assertEqual([t.ref.track_id for t in self.search.tracks],
                         ["track-2", "track-3"])
        self.assertEqual(self.search.state, "ready")
        self.assertTrue(self.has_more[-1])

    def test_load_more_appends_and_deduplicates(self):
        _, _, generation, _ = self.start("daft")
        self.provider.search_done.emit(
            generation, SearchPage([make_track(1), make_track(2)], 30))

        self.search.load_more()
        query, offset, more_generation, _ = self.provider.searches[-1]
        self.assertEqual((query, offset), ("daft", 30))
        self.assertGreater(more_generation, generation)

        self.provider.search_done.emit(
            more_generation, SearchPage([make_track(2), make_track(3)], None))
        self.assertEqual([t.ref.track_id for t in self.search.tracks],
                         ["track-1", "track-2", "track-3"])
        self.assertFalse(self.has_more[-1])
        self.assertEqual(self.search.state, "ready")

    def test_duplicate_only_page_still_clears_loading(self):
        _, _, generation, _ = self.start("daft")
        self.provider.search_done.emit(generation, SearchPage([make_track(1)], 30))
        self.search.load_more()
        _, _, more_generation, _ = self.provider.searches[-1]
        self.provider.search_done.emit(more_generation, SearchPage([make_track(1)], None))
        self.assertEqual(len(self.search.tracks), 1)
        self.assertEqual(self.search.state, "ready")

    def test_empty_result_state(self):
        _, _, generation, _ = self.start("zzzz")
        self.provider.search_done.emit(generation, SearchPage([], None))
        self.assertEqual(self.search.state, "empty")
        self.assertEqual(self.states[-1][0], "empty")
        self.assertIn("Ничего не найдено", self.states[-1][1])

    def test_failure_exposes_retry(self):
        _, _, generation, _ = self.start("daft")
        error = ProviderError(ErrorKind.OFFLINE, "Нет подключения к интернету.")
        self.provider.search_failed.emit(generation, error)
        self.assertEqual(self.search.state, "error")
        self.assertEqual(self.states[-1], ("error", error.user_message, True))

        self.search.retry()
        self.assertEqual(self.provider.searches[-1][1], 0)
        self.assertEqual(self.search.state, "loading")

    def test_stale_failure_is_ignored(self):
        _, _, first_generation, _ = self.start("daft")
        _, _, second_generation, _ = self.start("daft punk")
        self.provider.search_failed.emit(
            first_generation, ProviderError(ErrorKind.TRANSIENT, "stale"))
        self.assertEqual(self.search.state, "loading")
        self.provider.search_failed.emit(
            second_generation, ProviderError(ErrorKind.TRANSIENT, "fresh"))
        self.assertEqual(self.search.state, "error")

    def test_load_more_failure_retries_same_offset(self):
        _, _, generation, _ = self.start("daft")
        self.provider.search_done.emit(generation, SearchPage([make_track(1)], 30))
        self.search.load_more()
        _, _, more_generation, _ = self.provider.searches[-1]
        self.provider.search_failed.emit(
            more_generation, ProviderError(ErrorKind.TRANSIENT, "timeout"))
        self.assertEqual(self.search.state, "error")
        self.search.retry()
        self.assertEqual(self.provider.searches[-1][1], 30)
        self.assertEqual(self.search.state, "loading")

    def test_load_more_ignored_before_first_page(self):
        self.start("daft")
        calls = len(self.provider.searches)
        self.search.load_more()
        self.assertEqual(len(self.provider.searches), calls)

    def test_load_more_ignored_when_no_next_page(self):
        _, _, generation, _ = self.start("daft")
        self.provider.search_done.emit(generation, SearchPage([make_track(1)], None))
        calls = len(self.provider.searches)
        self.search.load_more()
        self.assertEqual(len(self.provider.searches), calls)


if __name__ == "__main__":
    unittest.main()
