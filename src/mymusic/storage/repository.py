"""Локальное хранилище SQLite: очередь, избранное, метаданные, сессия."""
from __future__ import annotations

import sqlite3
from pathlib import Path

from ..domain.models import Availability, Track, TrackRef
from ..domain.queue import QueueEntry

SCHEMA_VERSION = 1


class Repository:
    """Соединение принадлежит потоку, создавшему объект (UI-поток)."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(self.path)
        self._db.row_factory = sqlite3.Row
        self._db.execute("PRAGMA foreign_keys = ON")
        self._db.execute("PRAGMA journal_mode = WAL")
        try:
            self._migrate()
        except Exception:
            self._db.close()
            raise

    def _migrate(self) -> None:
        version = self._db.execute("PRAGMA user_version").fetchone()[0]
        if version < 1:
            with self._db:
                self._db.executescript(
                    """
                    CREATE TABLE IF NOT EXISTS tracks(
                        provider_id TEXT NOT NULL,
                        track_id TEXT NOT NULL,
                        title TEXT NOT NULL,
                        artist TEXT NOT NULL,
                        duration_ms INTEGER NULL,
                        source_page_url TEXT NOT NULL DEFAULT '',
                        artwork_url TEXT NULL,
                        availability TEXT NOT NULL DEFAULT 'full',
                        attribution TEXT NULL,
                        metadata_updated_at INTEGER NOT NULL,
                        PRIMARY KEY(provider_id, track_id)
                    );
                    CREATE TABLE IF NOT EXISTS favorites(
                        provider_id TEXT NOT NULL,
                        track_id TEXT NOT NULL,
                        added_at INTEGER NOT NULL,
                        PRIMARY KEY(provider_id, track_id),
                        FOREIGN KEY(provider_id, track_id)
                            REFERENCES tracks(provider_id, track_id) ON DELETE CASCADE
                    );
                    CREATE TABLE IF NOT EXISTS queue_items(
                        entry_id TEXT PRIMARY KEY,
                        provider_id TEXT NOT NULL,
                        track_id TEXT NOT NULL,
                        ordinal INTEGER NOT NULL UNIQUE,
                        FOREIGN KEY(provider_id, track_id)
                            REFERENCES tracks(provider_id, track_id) ON DELETE CASCADE
                    );
                    CREATE TABLE IF NOT EXISTS playback_session(
                        id INTEGER PRIMARY KEY CHECK (id = 1),
                        current_entry_id TEXT NULL,
                        position_ms INTEGER NOT NULL DEFAULT 0,
                        updated_at INTEGER NOT NULL,
                        FOREIGN KEY(current_entry_id) REFERENCES queue_items(entry_id)
                            ON DELETE SET NULL
                    );
                    """
                )
                self._db.execute("PRAGMA user_version = 1")
        if self._db.execute("PRAGMA user_version").fetchone()[0] != SCHEMA_VERSION:
            raise RuntimeError("Неизвестная версия схемы library.db")

    def close(self) -> None:
        try:
            self._db.close()
        except sqlite3.Error:
            pass

    def upsert_tracks(self, tracks: list[Track]) -> None:
        now = _now_ms()
        with self._db:
            for track in tracks:
                self._db.execute(
                    """
                    INSERT INTO tracks(provider_id, track_id, title, artist, duration_ms,
                        source_page_url, artwork_url, availability, attribution, metadata_updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(provider_id, track_id) DO UPDATE SET
                        title=excluded.title, artist=excluded.artist,
                        duration_ms=excluded.duration_ms,
                        source_page_url=excluded.source_page_url,
                        artwork_url=excluded.artwork_url,
                        availability=excluded.availability,
                        attribution=excluded.attribution,
                        metadata_updated_at=excluded.metadata_updated_at
                    """,
                    (track.ref.provider_id, track.ref.track_id, track.title, track.artist,
                     track.duration_ms, track.source_page_url, track.artwork_url,
                     track.availability.value, track.attribution, now),
                )

    def set_favorite(self, track: Track, favorite: bool) -> None:
        self.upsert_tracks([track])
        with self._db:
            if favorite:
                self._db.execute(
                    "INSERT OR REPLACE INTO favorites(provider_id, track_id, added_at) VALUES (?, ?, ?)",
                    (track.ref.provider_id, track.ref.track_id, _now_ms()),
                )
            else:
                self._db.execute(
                    "DELETE FROM favorites WHERE provider_id=? AND track_id=?",
                    (track.ref.provider_id, track.ref.track_id),
                )

    def favorite_keys(self) -> set[tuple[str, str]]:
        rows = self._db.execute("SELECT provider_id, track_id FROM favorites").fetchall()
        return {(r["provider_id"], r["track_id"]) for r in rows}

    def clear_favorites(self) -> None:
        with self._db:
            self._db.execute("DELETE FROM favorites")

    def list_favorites(self) -> list[Track]:
        rows = self._db.execute(
            """
            SELECT t.* FROM favorites f
            JOIN tracks t ON t.provider_id=f.provider_id AND t.track_id=f.track_id
            ORDER BY f.added_at DESC
            """
        ).fetchall()
        return [_row_to_track(r) for r in rows]

    def save_queue(self, entries: list[QueueEntry], current_entry_id: str | None,
                   position_ms: int) -> None:
        tracks = [e.track for e in entries]
        now = _now_ms()
        with self._db:
            for track in tracks:
                self._db.execute(
                    """
                    INSERT INTO tracks(provider_id, track_id, title, artist, duration_ms,
                        source_page_url, artwork_url, availability, attribution, metadata_updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(provider_id, track_id) DO UPDATE SET
                        title=excluded.title, artist=excluded.artist,
                        duration_ms=excluded.duration_ms,
                        source_page_url=excluded.source_page_url,
                        artwork_url=excluded.artwork_url,
                        availability=excluded.availability,
                        attribution=excluded.attribution,
                        metadata_updated_at=excluded.metadata_updated_at
                    """,
                    (track.ref.provider_id, track.ref.track_id, track.title, track.artist,
                     track.duration_ms, track.source_page_url, track.artwork_url,
                     track.availability.value, track.attribution, now),
                )
            self._db.execute("DELETE FROM queue_items")
            self._db.executemany(
                "INSERT INTO queue_items(entry_id, provider_id, track_id, ordinal) VALUES (?, ?, ?, ?)",
                [(e.entry_id, e.track.ref.provider_id, e.track.ref.track_id, i)
                 for i, e in enumerate(entries)],
            )
            self._db.execute(
                "INSERT OR REPLACE INTO playback_session(id, current_entry_id, position_ms, updated_at) "
                "VALUES (1, ?, ?, ?)",
                (current_entry_id, max(0, int(position_ms)), now),
            )

    def save_session(self, current_entry_id: str | None, position_ms: int) -> None:
        with self._db:
            self._db.execute(
                "INSERT OR REPLACE INTO playback_session(id, current_entry_id, position_ms, updated_at) "
                "VALUES (1, ?, ?, ?)",
                (current_entry_id, max(0, int(position_ms)), _now_ms()),
            )

    def load_queue(self) -> tuple[list[QueueEntry], str | None, int]:
        rows = self._db.execute(
            """
            SELECT q.entry_id, t.* FROM queue_items q
            JOIN tracks t ON t.provider_id=q.provider_id AND t.track_id=q.track_id
            ORDER BY q.ordinal
            """
        ).fetchall()
        entries = [QueueEntry(r["entry_id"], _row_to_track(r)) for r in rows]
        session = self._db.execute(
            "SELECT current_entry_id, position_ms FROM playback_session WHERE id=1"
        ).fetchone()
        current = session["current_entry_id"] if session else None
        if current and not any(e.entry_id == current for e in entries):
            current = None
        position = int(session["position_ms"]) if session else 0
        return entries, current, position

    def clear_all(self) -> None:
        with self._db:
            self._db.execute("DELETE FROM playback_session")
            self._db.execute("DELETE FROM queue_items")
            self._db.execute("DELETE FROM favorites")
            self._db.execute("DELETE FROM tracks")


def _now_ms() -> int:
    import time
    return int(time.time() * 1000)


def _row_to_track(row: sqlite3.Row) -> Track:
    try:
        availability = Availability(row["availability"])
    except ValueError:
        availability = Availability.UNAVAILABLE
    return Track(
        ref=TrackRef(row["provider_id"], row["track_id"]),
        title=row["title"],
        artist=row["artist"],
        duration_ms=row["duration_ms"],
        artwork_url=row["artwork_url"],
        source_page_url=row["source_page_url"],
        availability=availability,
        attribution=row["attribution"],
    )
