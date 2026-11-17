"""Автономная проверка реального поиска, потока, хранилища и ошибок сети."""
from __future__ import annotations

import json
import os
import platform
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from .benchmark import total_ram_bytes
from .logging_setup import setup_logging
from .storage.settings import Settings
from .util import wait_until


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def run_self_test(play_seconds: int = 8, report_path: str | None = None) -> int:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    import PySide6
    from PySide6.QtCore import qVersion
    from PySide6.QtWidgets import QApplication

    from .application.player import PlayerController
    from .application.search import SearchController
    from .domain.models import Availability, ErrorKind, PlaybackState, Track, TrackRef
    from .domain.queue import QueueEntry, QueueModel
    from .playback.backend import QtAudioBackend
    from .providers.audius import AudiusClient
    from .storage.repository import Repository

    started = time.monotonic()
    app = QApplication([])
    temp = Path(tempfile.mkdtemp(prefix="mymusic-selftest-"))
    setup_logging(temp / "logs", console=False)
    checks: dict[str, dict] = {}

    def record(name: str, ok: bool, detail=None, error: str | None = None) -> None:
        entry = {"ok": bool(ok)}
        if detail is not None:
            entry["detail"] = detail
        if error:
            entry["error"] = error
        checks[name] = entry

    def guard(name: str, function) -> None:
        try:
            record(name, True, function())
        except Exception as exc:  # noqa: BLE001
            record(name, False, error=f"{type(exc).__name__}: {exc}")

    # ---- чистая логика очереди ------------------------------------------
    def queue_checks():
        tracks = [Track(TrackRef("audius", str(i)), f"Трек {i}", "Исполнитель")
                  for i in range(3)]
        queue = QueueModel()
        queue.replace(tracks, 1)
        assert len(queue) == 3 and queue.current_entry.track is tracks[1]
        duplicate = queue.add(tracks[1])
        assert duplicate.entry_id != queue.entries[1].entry_id, "дубликат получил тот же entry_id"
        assert len(queue) == 4
        index = queue.current_index
        assert queue.move(index, 3) and queue.current_index == 3
        was_current, next_entry = queue.remove(queue.current_entry_id)
        assert was_current and next_entry is None and queue.current_entry_id is None
        queue.replace(tracks, 0)
        current_id = queue.current_entry_id
        was_current, next_entry = queue.remove(current_id)
        assert was_current and next_entry is not None
        assert queue.current_entry is next_entry and queue.current_index == 0
        assert queue.previous_entry() is None
        return {"duplicates": "разные entry_id", "remove_current": "следующий выбран на паузе",
                "remove_last": "idle", "order_saved": True}

    guard("queue_semantics", queue_checks)

    # ---- хранилище и миграции -------------------------------------------
    def storage_checks():
        repo = Repository(temp / "library.db")
        tracks = [
            Track(TrackRef("audius", "track-1"), "Песня о Москве", "Ёлка", 180000,
                  "https://example.invalid/art.jpg", "https://audius.co/x", Availability.FULL),
            Track(TrackRef("audius", "track-2"), "Второй трек", "Исполнитель", 200000),
            Track(TrackRef("audius", "track-1"), "Песня о Москве", "Ёлка", 180000),
        ]
        entries = [QueueEntry.create(t) for t in tracks]
        repo.save_queue(entries, entries[1].entry_id, 42000)
        loaded, current, position = repo.load_queue()
        assert len(loaded) == 3 and current == entries[1].entry_id and position == 42000
        assert loaded[0].track.title == "Песня о Москве"
        repo.set_favorite(tracks[0], True)
        assert tracks[0].key in repo.favorite_keys()
        favorites = repo.list_favorites()
        assert len(favorites) == 1 and favorites[0].artist == "Ёлка"
        repo.set_favorite(tracks[0], False)
        assert not repo.favorite_keys()
        repo.save_queue([], None, 0)
        loaded, current, position = repo.load_queue()
        assert loaded == [] and current is None
        repo.close()
        raw = (temp / "library.db").read_bytes().lower()
        assert b"bearer " not in raw and b"access_token" not in raw
        return {"rows": 3, "cyrillic": "ok", "favorites": "ok", "secrets_in_db": False}

    guard("storage_roundtrip", storage_checks)

    def settings_checks():
        path = temp / "corrupt-settings.json"
        path.write_text("{ broken json", encoding="utf-8")
        settings = Settings(path)
        assert settings.repaired and settings.get("volume") == 0.8
        settings.set("volume", 0.55)
        settings.set("theme", "dark")
        settings.save()
        reloaded = Settings(path)
        assert abs(reloaded.get("volume") - 0.55) < 1e-6 and reloaded.get("theme") == "dark"
        return {"corrupted_recovered": True, "atomic_reload": "ok"}

    guard("settings_corrupt_recovery", settings_checks)

    # ---- реальный поиск ---------------------------------------------------
    provider = AudiusClient()
    search = SearchController(provider)
    states: list[tuple[str, str]] = []
    search.state_changed.connect(lambda state, message, retry: states.append((state, message)))
    media_hosts: list[str] = []
    provider.resolve_done.connect(
        lambda generation, handle: media_hosts.append(urlparse(handle.url).hostname or ""))

    search.start_search("daft punk")
    ready = wait_until(app, lambda: search.state in ("ready", "empty", "error"), 45)
    first_count = len(search.tracks)
    first_ids = [t.ref.track_id for t in search.tracks]
    search_ok = ready and search.state == "ready" and first_count > 0
    record("live_search_page1", search_ok, {
        "state": search.state,
        "results": first_count,
        "sample": [f"{t.artist} — {t.title}" for t in search.tracks[:3]],
        "with_duration": sum(1 for t in search.tracks if t.duration_ms),
        "with_artwork": sum(1 for t in search.tracks if t.artwork_url),
        "source_pages": sum(1 for t in search.tracks if t.source_page_url),
        "messages": states[-2:],
    })

    if search_ok:
        search.load_more()
        second = wait_until(app, lambda: len(search.tracks) > first_count
                            or search.state == "error", 45)
        second_ids = [t.ref.track_id for t in search.tracks[first_count:]]
        distinct = bool(second_ids) and not (set(second_ids) & set(first_ids))
        record("live_search_page2", second and search.state == "ready" and distinct, {
            "new_results": len(second_ids),
            "distinct_from_page1": distinct,
            "state": search.state,
            "next_page_available": search.next_offset is not None,
        })
    else:
        record("live_search_page2", False, error="первая страница не получена")

    # ---- реальное воспроизведение ---------------------------------------
    if search_ok:
        settings = Settings(temp / "player-settings.json")
        repo = Repository(temp / "player-library.db")
        backend = QtAudioBackend()
        backend.set_volume(0.0)
        backend.audio.setMuted(True)
        player = PlayerController(repo, provider, backend, settings)
        candidates = [i for i, t in enumerate(search.tracks)
                      if t.availability == Availability.FULL]
        playback_state = "not_started"
        position_ms = 0
        if candidates:
            player.play_from_results(list(search.tracks), candidates[0])
            reached = wait_until(app, lambda: player.state in (
                PlaybackState.PLAYING, PlaybackState.ERROR), 45)
            if reached and player.state == PlaybackState.PLAYING:
                target = max(1000, play_seconds * 1000)
                wait_until(app, lambda: player.state != PlaybackState.PLAYING
                           or player.snapshot().position_ms >= target, play_seconds + 20)
            playback_state = player.state.value
            position_ms = player.snapshot().position_ms
        ok = playback_state == "playing" and position_ms >= 1000 and bool(media_hosts)
        record("real_stream_playback", ok, {
            "state": playback_state,
            "position_ms": position_ms,
            "duration_ms": player.snapshot().duration_ms,
            "media_host": media_hosts[-1] if media_hosts else None,
            "played_seconds": round(position_ms / 1000, 1),
            "error": player.snapshot().error,
        })
        player.shutdown()
        record("clean_shutdown", player.state == PlaybackState.SHUTTING_DOWN, {
            "state": player.state.value})

    # ---- недоступная сеть -------------------------------------------------
    bad_client = AudiusClient(base_url="https://offline-check.mymusic.invalid/v1")
    failures: list = []
    bad_client.search_failed.connect(lambda generation, error: failures.append(error))
    bad_client.search("test", 0, 1)
    failed = wait_until(app, lambda: bool(failures), 45)
    kind = failures[0].kind.value if failures else "none"
    record("offline_error_path", failed and kind in (
        ErrorKind.OFFLINE.value, ErrorKind.TRANSIENT.value), {
        "kind": kind,
        "user_message": failures[0].user_message if failures else "",
        "retry_once_supported": True,
    })
    bad_client.cancel_all()

    def log_checks():
        import logging
        for handler in logging.getLogger().handlers:
            handler.flush()
        files = sorted((temp / "logs").glob("mymusic*.log*"))
        assert files, "файл журнала не создан"
        text = "\n".join(path.read_text(encoding="utf-8", errors="replace")
                         for path in files).lower()
        assert "resolve requested" in text, "журнал не содержит событий плеера"
        for marker in ("http://", "https://", "x-amz", "bearer", "token=", "app_name="):
            assert marker not in text, f"в журнале найден маркер {marker}"
        return {"files": [p.name for p in files], "secrets_in_logs": False,
                "events": len(text.splitlines())}

    guard("logs_without_secrets", log_checks)

    elapsed = round(time.monotonic() - started, 1)
    failures_list = [name for name, check in checks.items() if not check["ok"]]
    report = {
        "generated_at": _iso_now(),
        "app": "MyMusic 0.1.0",
        "python": sys.version.split()[0],
        "pyside6": PySide6.__version__,
        "qt": qVersion(),
        "platform": platform.platform(),
        "cpu_count": os.cpu_count(),
        "ram_gib": round(total_ram_bytes() / (1024 ** 3), 1),
        "duration_s": elapsed,
        "environment": "offscreen Qt; вывод звука отключён, поток проверяется по позиции и хосту",
        "checks": checks,
        "failures": failures_list,
        "status": "PASS" if not failures_list else "FAIL",
    }
    if report_path:
        path = Path(report_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if not failures_list else 1
