"""Семантика очереди из docs/01 (чистая модель, без Qt)."""
from __future__ import annotations

import unittest

from mymusic.domain.queue import QueueEntry, QueueModel

from .support import make_track


class QueueTests(unittest.TestCase):
    def setUp(self):
        self.tracks = [make_track(i) for i in range(3)]
        self.queue = QueueModel()

    def test_replace_selects_start_index(self):
        entry = self.queue.replace(self.tracks, 2)
        self.assertIsNotNone(entry)
        self.assertEqual(len(self.queue), 3)
        self.assertEqual(self.queue.current_index, 2)
        self.assertEqual(self.queue.current_entry.track, self.tracks[2])

    def test_replace_empty_resets_current(self):
        self.queue.replace(self.tracks, 1)
        self.assertIsNone(self.queue.replace([], 0))
        self.assertIsNone(self.queue.current_entry_id)
        self.assertEqual(len(self.queue), 0)

    def test_replace_clamps_start_index(self):
        self.queue.replace(self.tracks, 99)
        self.assertEqual(self.queue.current_index, 2)
        self.queue.replace(self.tracks, -5)
        self.assertEqual(self.queue.current_index, 0)

    def test_duplicates_get_unique_ids(self):
        self.queue.replace([self.tracks[0]], 0)
        duplicate = self.queue.add(self.tracks[0])
        self.assertNotEqual(duplicate.entry_id, self.queue.entries[0].entry_id)
        self.assertEqual(len(self.queue), 2)

    def test_add_does_not_change_current(self):
        self.queue.replace(self.tracks[:2], 1)
        current = self.queue.current_entry_id
        self.queue.add(self.tracks[2])
        self.assertEqual(self.queue.current_entry_id, current)
        self.assertEqual(len(self.queue), 3)

    def test_remove_current_selects_next_paused(self):
        self.queue.replace(self.tracks, 1)
        current_id = self.queue.current_entry_id
        was_current, next_entry = self.queue.remove(current_id)
        self.assertTrue(was_current)
        self.assertIsNotNone(next_entry)
        self.assertEqual(next_entry.track, self.tracks[2])
        self.assertEqual(self.queue.current_index, 1)
        self.assertEqual(len(self.queue), 2)

    def test_remove_last_current_becomes_idle(self):
        self.queue.replace(self.tracks, 2)
        was_current, next_entry = self.queue.remove(self.queue.current_entry_id)
        self.assertTrue(was_current)
        self.assertIsNone(next_entry)
        self.assertIsNone(self.queue.current_entry_id)
        self.assertIsNone(self.queue.current_entry)

    def test_remove_non_current_keeps_selection(self):
        self.queue.replace(self.tracks, 1)
        current_id = self.queue.current_entry_id
        was_current, next_entry = self.queue.remove(self.queue.entries[0].entry_id)
        self.assertFalse(was_current)
        self.assertEqual(self.queue.current_entry_id, current_id)
        self.assertEqual(next_entry.entry_id, current_id)
        self.assertEqual(len(self.queue), 2)

    def test_remove_unknown_id_is_noop(self):
        self.queue.replace(self.tracks, 0)
        current_id = self.queue.current_entry_id
        was_current, next_entry = self.queue.remove("missing")
        self.assertFalse(was_current)
        self.assertEqual(self.queue.current_entry_id, current_id)
        self.assertEqual(next_entry.entry_id, current_id)

    def test_move_preserves_current_entry(self):
        self.queue.replace(self.tracks, 0)
        current_id = self.queue.current_entry_id
        self.assertTrue(self.queue.move(0, 2))
        self.assertEqual(self.queue.current_entry_id, current_id)
        self.assertEqual(self.queue.current_index, 2)
        self.assertEqual([e.track for e in self.queue.entries],
                         [self.tracks[1], self.tracks[2], self.tracks[0]])

    def test_move_rejects_invalid_indexes(self):
        self.queue.replace(self.tracks, 0)
        self.assertFalse(self.queue.move(0, 0))
        self.assertFalse(self.queue.move(-1, 1))
        self.assertFalse(self.queue.move(0, 3))

    def test_next_and_previous_boundaries(self):
        self.queue.replace(self.tracks, 0)
        self.assertEqual(self.queue.next_entry().track, self.tracks[1])
        self.assertIsNone(self.queue.previous_entry())
        self.queue.select(self.queue.entries[2].entry_id)
        self.assertIsNone(self.queue.next_entry())
        self.assertEqual(self.queue.previous_entry().track, self.tracks[1])

    def test_next_without_selection_returns_first(self):
        self.queue.add(self.tracks[0])
        self.assertEqual(self.queue.next_entry().track, self.tracks[0])

    def test_select_unknown_keeps_selection(self):
        self.queue.replace(self.tracks, 1)
        current_id = self.queue.current_entry_id
        self.assertIsNone(self.queue.select("missing"))
        self.assertEqual(self.queue.current_entry_id, current_id)

    def test_entries_property_is_snapshot(self):
        self.queue.replace(self.tracks, 0)
        snapshot = self.queue.entries
        self.queue.add(self.tracks[2])
        self.assertEqual(len(snapshot), 3)

    def test_index_of(self):
        self.queue.replace(self.tracks, 0)
        self.assertEqual(self.queue.index_of(self.queue.entries[1].entry_id), 1)
        self.assertEqual(self.queue.index_of("missing"), -1)

    def test_queue_entry_create_is_unique(self):
        first = QueueEntry.create(self.tracks[0])
        second = QueueEntry.create(self.tracks[0])
        self.assertNotEqual(first.entry_id, second.entry_id)
        self.assertGreaterEqual(len(first.entry_id), 16)


if __name__ == "__main__":
    unittest.main()
