"""Плеер: очередь, гонки поколений, пауза/сон, восстановление и завершение."""
from __future__ import annotations

import unittest

from PySide6.QtCore import QCoreApplication

from mymusic.application.player import PlayerController
from mymusic.domain.models import (Availability, ErrorKind, PlaybackHandle, PlaybackState,
                                   ProviderError)
from mymusic.domain.queue import QueueEntry

from .support import (FakeBackend, FakeProvider, FakeRepository, FakeSettings, make_track)


def ensure_app():
    return QCoreApplication.instance() or QCoreApplication([])


class PlayerControllerTests(unittest.TestCase):
    def setUp(self):
        self.make_player()

    def make_player(self, provider=None, repository=None, settings=None):
        ensure_app()
        self.provider = provider or FakeProvider()
        self.backend = FakeBackend()
        self.repo = repository or FakeRepository()
        self.settings = settings or FakeSettings()
        self.player = PlayerController(self.repo, self.provider, self.backend, self.settings)
        self.notices: list[str] = []
        self.player.notice.connect(self.notices.append)
        self.snapshots = []
        self.player.snapshot_changed.connect(self.snapshots.append)
        return self.player

    def play(self, tracks, index=0):
        self.player.play_from_results(list(tracks), index)
        return self.player.snapshot()

    def tearDown(self):
        if getattr(self, "player", None) is not None:
            self.player._ui_timer.stop()
            self.player._save_timer.stop()
            self.player._volume_save_timer.stop()

    def test_play_from_results_replaces_queue(self):
        tracks = [make_track(i) for i in range(3)]
        snapshot = self.play(tracks, 1)
        self.assertEqual(snapshot.state, PlaybackState.PLAYING)
        self.assertEqual(snapshot.track, tracks[1])
        self.assertEqual(snapshot.queue_count, 3)
        self.assertEqual(snapshot.queue_index, 1)
        self.assertEqual(self.backend.loaded_urls, ["https://media.example/track-1.mp3"])
        self.assertTrue(self.repo.saved_queues)

    def test_add_to_queue_keeps_playing_and_appends(self):
        tracks = [make_track(0), make_track(1)]
        self.play(tracks, 0)
        loads = len(self.backend.loaded_urls)
        self.player.add_to_queue(make_track(2))
        self.assertEqual(self.player.snapshot().state, PlaybackState.PLAYING)
        self.assertEqual(self.player.snapshot().queue_index, 0)
        self.assertEqual(len(self.player.queue), 3)
        self.assertEqual(len(self.backend.loaded_urls), loads)
        self.assertIn("Трек добавлен в конец очереди.", self.notices)

    def test_remove_current_selects_next_paused(self):
        tracks = [make_track(i) for i in range(3)]
        self.play(tracks, 1)
        second = self.player.queue.current_entry
        loads = len(self.backend.loaded_urls)
        self.player.remove_entry(second.entry_id)
        snapshot = self.player.snapshot()
        self.assertEqual(snapshot.state, PlaybackState.PAUSED)
        self.assertEqual(snapshot.track, tracks[2])
        self.assertEqual(self.player.queue.current_index, 1)
        self.assertEqual(len(self.backend.loaded_urls), loads)
        self.assertTrue(any("Следующий выбран на паузе" in n for n in self.notices))

    def test_remove_current_last_becomes_idle(self):
        self.play([make_track(0)], 0)
        self.player.remove_entry(self.player.queue.current_entry.entry_id)
        self.assertEqual(self.player.snapshot().state, PlaybackState.IDLE)
        self.assertIsNone(self.player.queue.current_entry)
        self.assertIsNone(self.player.snapshot().track)

    def test_remove_non_current_does_not_interrupt(self):
        self.play([make_track(i) for i in range(3)], 1)
        current_id = self.player.queue.current_entry_id
        loads = len(self.backend.loaded_urls)
        self.player.remove_entry(self.player.queue.entries[0].entry_id)
        self.assertEqual(self.player.snapshot().state, PlaybackState.PLAYING)
        self.assertEqual(self.player.queue.current_entry_id, current_id)
        self.assertEqual(len(self.backend.loaded_urls), loads)

    def test_move_does_not_interrupt(self):
        self.play([make_track(i) for i in range(3)], 1)
        current_id = self.player.queue.current_entry_id
        loads = len(self.backend.loaded_urls)
        self.player.move_entry(0, 2)
        self.assertEqual(self.player.snapshot().state, PlaybackState.PLAYING)
        self.assertEqual(self.player.queue.current_entry_id, current_id)
        self.assertEqual([e.track.title for e in self.player.queue.entries],
                         ["Трек 1", "Трек 2", "Трек 0"])
        self.assertEqual(len(self.backend.loaded_urls), loads)
        self.assertEqual(self.repo.entries[-1].track.title, "Трек 0")

    def test_next_advances_and_last_next_stops(self):
        self.play([make_track(i) for i in range(2)], 0)
        self.player.next()
        self.assertEqual(self.player.snapshot().state, PlaybackState.PLAYING)
        self.assertEqual(self.player.snapshot().track, make_track(1))
        self.player.next()
        self.assertEqual(self.player.snapshot().state, PlaybackState.IDLE)
        self.assertIn("Очередь закончилась.", self.notices)

    def test_previous_before_three_seconds_goes_back(self):
        self.play([make_track(i) for i in range(3)], 1)
        self.backend.position_changed.emit(1_500)
        loads = len(self.backend.loaded_urls)
        self.player.previous()
        self.assertEqual(self.player.queue.current_index, 0)
        self.assertEqual(len(self.backend.loaded_urls), loads + 1)
        self.assertEqual(self.backend.loaded_urls[-1], "https://media.example/track-0.mp3")

    def test_previous_after_three_seconds_seeks_to_start(self):
        self.play([make_track(i) for i in range(3)], 1)
        self.backend.position_changed.emit(4_200)
        loads = len(self.backend.loaded_urls)
        resolves = len(self.provider.resolves)
        self.player.previous()
        self.assertEqual(self.player.queue.current_index, 1)
        self.assertIn(0, self.backend.seeks)
        self.assertEqual(self.player.snapshot().position_ms, 0)
        self.assertEqual(len(self.backend.loaded_urls), loads)
        self.assertEqual(len(self.provider.resolves), resolves)

    def test_end_of_track_advances(self):
        self.play([make_track(0), make_track(1)], 0)
        self.backend.ended.emit()
        self.assertEqual(self.player.snapshot().state, PlaybackState.PLAYING)
        self.assertEqual(self.player.queue.current_index, 1)

    def test_end_of_queue_stops(self):
        self.play([make_track(0)], 0)
        self.backend.ended.emit()
        self.assertEqual(self.player.snapshot().state, PlaybackState.IDLE)
        self.assertIn("Очередь закончилась.", self.notices)

    def test_rapid_next_only_last_track_is_active(self):
        tracks = [make_track(i) for i in range(10)]
        self.play(tracks, 0)
        for _ in range(9):
            self.player.next()
        self.assertEqual(self.player.queue.current_index, 9)
        self.assertEqual(self.player.snapshot().track, tracks[9])
        self.assertEqual(self.backend.loaded_urls[-1], "https://media.example/track-9.mp3")
        self.assertEqual(self.player.snapshot().state, PlaybackState.PLAYING)

    def test_stale_resolve_is_ignored(self):
        player = self.make_player(provider=FakeProvider(auto_resolve=False))
        tracks = [make_track(0), make_track(1)]
        player.play_from_results(tracks, 0)
        stale_generation = self.provider.resolves[-1][1]
        second_id = player.queue.entries[1].entry_id
        player.play_entry(second_id)
        fresh_generation = self.provider.resolves[-1][1]
        self.assertNotEqual(stale_generation, fresh_generation)

        self.provider.resolve_done.emit(
            stale_generation, PlaybackHandle(url="https://media.example/stale.mp3"))
        self.assertEqual(self.backend.loaded_urls, [])
        self.assertEqual(player.snapshot().state, PlaybackState.RESOLVING)

        self.provider.resolve_done.emit(
            fresh_generation, PlaybackHandle(url="https://media.example/fresh.mp3"))
        self.assertEqual(self.backend.loaded_urls, ["https://media.example/fresh.mp3"])
        self.assertEqual(player.snapshot().state, PlaybackState.PLAYING)

    def test_stale_resolve_failure_is_ignored(self):
        player = self.make_player(provider=FakeProvider(auto_resolve=False))
        player.play_from_results([make_track(0)], 0)
        stale_generation = self.provider.resolves[-1][1]
        player.play_from_results([make_track(1)], 0)
        self.provider.resolve_failed.emit(
            stale_generation, ProviderError(ErrorKind.TRANSIENT, "stale"))
        self.assertEqual(player.snapshot().state, PlaybackState.RESOLVING)

    def test_cancelled_resolve_keeps_state(self):
        player = self.make_player(provider=FakeProvider(auto_resolve=False))
        player.play_from_results([make_track(0)], 0)
        generation = self.provider.resolves[-1][1]
        self.provider.resolve_failed.emit(
            generation, ProviderError(ErrorKind.CANCELLED, "cancelled"))
        self.assertEqual(player.snapshot().state, PlaybackState.RESOLVING)

    def test_unavailable_track_never_loads(self):
        track = make_track(0, availability=Availability.UNAVAILABLE)
        self.play([track], 0)
        snapshot = self.player.snapshot()
        self.assertEqual(snapshot.state, PlaybackState.ERROR)
        self.assertIn("недоступен", snapshot.error)
        self.assertEqual(self.provider.resolves, [])
        self.assertEqual(self.backend.loaded_urls, [])

    def test_restore_paused_and_resume_at_position(self):
        entries = [QueueEntry.create(make_track(i)) for i in range(3)]
        repo = FakeRepository(entries, entries[1].entry_id, 4_200)
        repo.favorites.add(make_track(0).key)
        player = self.make_player(repository=repo)
        player.restore()
        snapshot = player.snapshot()
        self.assertEqual(snapshot.state, PlaybackState.PAUSED)
        self.assertEqual(snapshot.track.title, "Трек 1")
        self.assertEqual(snapshot.position_ms, 4_200)
        self.assertEqual(player.favorites, {make_track(0).key})
        self.assertEqual(self.backend.loaded_urls, [])

        player.toggle_pause()
        self.assertEqual(player.snapshot().state, PlaybackState.PLAYING)
        self.assertEqual(self.backend.seeks, [4_200])
        self.assertEqual(self.backend.loaded_urls,
                         ["https://media.example/track-1.mp3"])

    def test_restore_empty_queue_is_idle(self):
        player = self.make_player()
        player.restore()
        self.assertEqual(player.snapshot().state, PlaybackState.IDLE)
        self.assertIsNone(player.snapshot().track)
        self.assertEqual(player.queue.current_entry_id, None)

    def test_pause_saves_position(self):
        self.play([make_track(0)], 0)
        self.backend.position_changed.emit(12_345)
        self.player.toggle_pause()
        self.assertEqual(self.player.snapshot().state, PlaybackState.PAUSED)
        self.assertEqual(self.repo.saved_sessions[-1], (self.player.queue.current_entry_id,
                                                       12_345))

    def test_suspend_pauses_and_resume_never_autoplays(self):
        self.play([make_track(0)], 0)
        plays = self.backend.play_calls
        self.player.stop_for_suspend()
        self.assertEqual(self.player.snapshot().state, PlaybackState.PAUSED)
        self.assertTrue(any("сон" in n for n in self.notices))

        self.player.handle_resume()
        self.assertEqual(self.player.snapshot().state, PlaybackState.PAUSED)
        self.assertEqual(self.backend.play_calls, plays)
        self.assertTrue(any("из сна" in n for n in self.notices))

    def test_backend_error_is_reported(self):
        self.play([make_track(0)], 0)
        self.backend.error.emit("Не удалось открыть поток.")
        snapshot = self.player.snapshot()
        self.assertEqual(snapshot.state, PlaybackState.ERROR)
        self.assertEqual(snapshot.error, "Не удалось открыть поток.")

    def test_clear_queue_stops(self):
        self.play([make_track(i) for i in range(2)], 0)
        self.player.clear_queue()
        self.assertEqual(self.player.snapshot().state, PlaybackState.IDLE)
        self.assertEqual(len(self.player.queue), 0)
        self.assertEqual(self.repo.entries, [])

    def test_favorites_toggle_and_clear(self):
        track = make_track(0)
        self.player.toggle_favorite(track)
        self.assertIn(track.key, self.player.favorites)
        self.assertIn(track.key, self.repo.favorites)
        self.player.toggle_favorite(track)
        self.assertNotIn(track.key, self.player.favorites)
        self.player.toggle_favorite(track)
        self.player.clear_favorites()
        self.assertEqual(self.player.favorites, set())
        self.assertEqual(self.repo.favorites, set())

    def test_volume_is_clamped_and_saved(self):
        self.player.set_volume(1.7)
        self.assertAlmostEqual(self.player.snapshot().volume, 1.0)
        self.player.set_volume(-2)
        self.assertAlmostEqual(self.player.snapshot().volume, 0.0)
        self.assertAlmostEqual(self.settings.get("volume"), 0.0)
        self.assertAlmostEqual(self.backend.volumes[-1], 0.0)

    def test_shutdown_releases_everything_and_ignores_late_events(self):
        player = self.make_player(provider=FakeProvider(auto_resolve=False))
        player.play_from_results([make_track(0)], 0)
        generation = self.provider.resolves[-1][1]
        player.shutdown()

        self.assertEqual(player.state, PlaybackState.SHUTTING_DOWN)
        self.assertEqual(self.backend.release_calls, 1)
        self.assertEqual(self.provider.cancel_calls, 1)
        self.assertTrue(self.repo.closed)
        self.assertTrue(self.repo.saved_queues)
        self.assertFalse(player._ui_timer.isActive())
        self.assertFalse(player._save_timer.isActive())

        self.provider.resolve_done.emit(
            generation, PlaybackHandle(url="https://media.example/late.mp3"))
        self.backend.error.emit("late")
        self.assertEqual(self.backend.loaded_urls, [])
        self.assertEqual(player.state, PlaybackState.SHUTTING_DOWN)

    def test_toggle_pause_while_resolving_does_not_restart(self):
        player = self.make_player(provider=FakeProvider(auto_resolve=False))
        player.play_from_results([make_track(0)], 0)
        resolves = len(self.provider.resolves)
        player.toggle_pause()
        self.assertEqual(len(self.provider.resolves), resolves)
        self.assertEqual(player.snapshot().state, PlaybackState.RESOLVING)
        self.assertTrue(any("готовит поток" in n for n in self.notices))


if __name__ == "__main__":
    unittest.main()
