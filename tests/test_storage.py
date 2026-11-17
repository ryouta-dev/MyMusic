"""Хранилище SQLite: миграции, очередь/сессия, избранное, отсутствие секретов."""
from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from mymusic.domain.models import Availability, Track, TrackRef
from mymusic.domain.queue import QueueEntry
from mymusic.storage.repository import SCHEMA_VERSION, Repository

from .support import make_track


class RepositoryTests(unittest.TestCase):
    def setUp(self):
        self._temp = tempfile.TemporaryDirectory(prefix="mymusic-tests-")
        self.path = Path(self._temp.name) / "library.db"
        self.repo = Repository(self.path)

    def tearDown(self):
        self.repo.close()
        self._temp.cleanup()

    def test_schema_version_and_wal(self):
        version = self.repo._db.execute("PRAGMA user_version").fetchone()[0]
        journal = self.repo._db.execute("PRAGMA journal_mode").fetchone()[0]
        self.assertEqual(version, SCHEMA_VERSION)
        self.assertEqual(journal.lower(), "wal")

    def test_queue_roundtrip_with_cyrillic(self):
        tracks = [
            Track(TrackRef("audius", "one"), "Песня о Москве", "Ёлка", 181_000,
                  "https://example.invalid/art.jpg", "https://audius.co/x",
                  Availability.FULL, "Audius"),
            Track(TrackRef("audius", "two"), "Второй трек", "Исполнитель", 200_000,
                  availability=Availability.PREVIEW),
        ]
        entries = [QueueEntry.create(t) for t in tracks]
        self.repo.save_queue(entries, entries[1].entry_id, 42_500)

        loaded, current, position = self.repo.load_queue()
        self.assertEqual([e.track.title for e in loaded], ["Песня о Москве", "Второй трек"])
        self.assertEqual([e.track.artist for e in loaded], ["Ёлка", "Исполнитель"])
        self.assertEqual(loaded[0].track.duration_ms, 181_000)
        self.assertEqual(loaded[1].track.availability, Availability.PREVIEW)
        self.assertEqual(current, entries[1].entry_id)
        self.assertEqual(position, 42_500)
        self.assertEqual([e.entry_id for e in loaded], [e.entry_id for e in entries])

    def test_reorder_and_clear_persist(self):
        tracks = [make_track(i) for i in range(3)]
        entries = [QueueEntry.create(t) for t in tracks]
        self.repo.save_queue(entries, entries[0].entry_id, 1000)
        reordered = [entries[2], entries[0], entries[1]]
        self.repo.save_queue(reordered, entries[2].entry_id, 2000)
        loaded, current, position = self.repo.load_queue()
        self.assertEqual([e.track.title for e in loaded],
                         ["Трек 2", "Трек 0", "Трек 1"])
        self.assertEqual(current, entries[2].entry_id)
        self.assertEqual(position, 2000)

        self.repo.save_queue([], None, 0)
        loaded, current, position = self.repo.load_queue()
        self.assertEqual(loaded, [])
        self.assertIsNone(current)
        self.assertEqual(position, 0)

    def test_dangling_session_entry_is_rejected(self):
        entries = [QueueEntry.create(make_track(0))]
        self.repo.save_queue(entries, entries[0].entry_id, 500)
        with self.assertRaises(sqlite3.IntegrityError):
            self.repo.save_session("deleted-entry", 900)
        _, current, _ = self.repo.load_queue()
        self.assertEqual(current, entries[0].entry_id)

    def test_save_session_position_clamped(self):
        entries = [QueueEntry.create(make_track(0))]
        self.repo.save_queue(entries, entries[0].entry_id, 0)
        self.repo.save_session(entries[0].entry_id, -50)
        _, _, position = self.repo.load_queue()
        self.assertEqual(position, 0)

    def test_favorites_add_list_clear(self):
        first, second = make_track(1), make_track(2)
        self.repo.set_favorite(first, True)
        self.repo.set_favorite(second, True)
        self.assertEqual(self.repo.favorite_keys(), {first.key, second.key})
        favorites = self.repo.list_favorites()
        self.assertEqual({t.key for t in favorites}, {first.key, second.key})
        self.repo.set_favorite(first, False)
        self.assertEqual(self.repo.favorite_keys(), {second.key})
        self.repo.clear_favorites()
        self.assertEqual(self.repo.favorite_keys(), set())
        self.assertEqual(self.repo.list_favorites(), [])

    def test_clear_all(self):
        tracks = [make_track(i) for i in range(2)]
        entries = [QueueEntry.create(t) for t in tracks]
        self.repo.save_queue(entries, entries[0].entry_id, 321)
        self.repo.set_favorite(tracks[0], True)
        self.repo.clear_all()
        loaded, current, position = self.repo.load_queue()
        self.assertEqual(loaded, [])
        self.assertIsNone(current)
        self.assertEqual(position, 0)
        self.assertEqual(self.repo.favorite_keys(), set())

    def test_unknown_future_schema_rejected(self):
        path = Path(self._temp.name) / "future.db"
        connection = sqlite3.connect(path)
        connection.execute("PRAGMA user_version = 99")
        connection.commit()
        connection.close()
        with self.assertRaises(RuntimeError):
            Repository(path)

    def test_reopen_keeps_data(self):
        entries = [QueueEntry.create(make_track(5))]
        self.repo.save_queue(entries, entries[0].entry_id, 777)
        self.repo.close()
        self.repo = Repository(self.path)
        loaded, current, position = self.repo.load_queue()
        self.assertEqual(len(loaded), 1)
        self.assertEqual(current, entries[0].entry_id)
        self.assertEqual(position, 777)

    def test_database_contains_no_credentials(self):
        tracks = [make_track(0), make_track(1)]
        self.repo.save_queue([QueueEntry.create(t) for t in tracks], None, 0)
        self.repo.close()
        raw = self.path.read_bytes().lower()
        for marker in (b"bearer ", b"access_token", b"client_secret", b"api_key"):
            self.assertNotIn(marker, raw)


if __name__ == "__main__":
    unittest.main()
