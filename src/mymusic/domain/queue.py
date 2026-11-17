"""Очередь воспроизведения. Чистая логика без Qt — покрыта unit-тестами."""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from .models import Track


@dataclass
class QueueEntry:
    entry_id: str
    track: Track

    @classmethod
    def create(cls, track: Track) -> "QueueEntry":
        return cls(uuid.uuid4().hex, track)


@dataclass
class QueueModel:
    _entries: list[QueueEntry] = field(default_factory=list)
    current_entry_id: str | None = None

    @property
    def entries(self) -> tuple[QueueEntry, ...]:
        return tuple(self._entries)

    def __len__(self) -> int:
        return len(self._entries)

    def __iter__(self):
        return iter(self._entries)

    @property
    def current_index(self) -> int:
        if self.current_entry_id is None:
            return -1
        for i, entry in enumerate(self._entries):
            if entry.entry_id == self.current_entry_id:
                return i
        return -1

    @property
    def current_entry(self) -> QueueEntry | None:
        idx = self.current_index
        return self._entries[idx] if idx >= 0 else None

    def replace(self, tracks: list[Track], start_index: int = 0) -> QueueEntry | None:
        self._entries = [QueueEntry.create(t) for t in tracks]
        if not self._entries:
            self.current_entry_id = None
            return None
        start_index = max(0, min(start_index, len(self._entries) - 1))
        self.current_entry_id = self._entries[start_index].entry_id
        return self.current_entry

    def add(self, track: Track) -> QueueEntry:
        entry = QueueEntry.create(track)
        self._entries.append(entry)
        return entry

    def remove(self, entry_id: str) -> tuple[bool, QueueEntry | None]:
        """Вернуть (был_ли_текущим, следующий_выбранный_элемент).

        Удаление текущей записи выбирает следующую на паузе; если следующей нет,
        очередь становится idle (current_entry_id = None), как требует docs/01.
        """
        idx = next((i for i, e in enumerate(self._entries) if e.entry_id == entry_id), -1)
        if idx < 0:
            return False, self.current_entry
        was_current = self._entries[idx].entry_id == self.current_entry_id
        del self._entries[idx]
        if not was_current:
            return False, self.current_entry
        if idx < len(self._entries):
            self.current_entry_id = self._entries[idx].entry_id
            return True, self.current_entry
        self.current_entry_id = None
        return True, None

    def move(self, source_index: int, target_index: int) -> bool:
        if not (0 <= source_index < len(self._entries) and 0 <= target_index < len(self._entries)):
            return False
        if source_index == target_index:
            return False
        entry = self._entries.pop(source_index)
        self._entries.insert(target_index, entry)
        return True

    def select(self, entry_id: str) -> QueueEntry | None:
        if any(e.entry_id == entry_id for e in self._entries):
            self.current_entry_id = entry_id
            return self.current_entry
        return None

    def next_entry(self) -> QueueEntry | None:
        idx = self.current_index
        if idx < 0:
            return self._entries[0] if self._entries else None
        return self._entries[idx + 1] if idx + 1 < len(self._entries) else None

    def previous_entry(self) -> QueueEntry | None:
        idx = self.current_index
        if idx <= 0:
            return None
        return self._entries[idx - 1]

    def index_of(self, entry_id: str) -> int:
        return next((i for i, e in enumerate(self._entries) if e.entry_id == entry_id), -1)
