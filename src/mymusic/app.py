"""Точка входа MyMusic и служебные режимы (self-test, скриншоты, замеры)."""
from __future__ import annotations

import argparse
import ctypes
import json
import os
import platform
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

APP_VERSION = "0.1.0"


def default_data_dir() -> Path:
    base = os.environ.get("LOCALAPPDATA")
    root = Path(base) if base else Path.home() / "AppData" / "Local"
    return root / "MyMusic"


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="MyMusic", description="Лёгкий плеер Audius")
    parser.add_argument("--self-test", action="store_true",
                        help="автономная проверка поиска, потока и хранилища")
    parser.add_argument("--play-seconds", type=int, default=8,
                        help="сколько секунд проверить реальное воспроизведение")
    parser.add_argument("--report", default="", help="путь JSON-отчёта self-test")
    parser.add_argument("--screenshot", default="", help="папка для снимков интерфейса")
    parser.add_argument("--perf", choices=["idle", "playing", "search"], default=None,
                        help="режим замера ресурсов")
    parser.add_argument("--perf-seconds", type=int, default=60)
    parser.add_argument("--perf-warmup", type=int, default=60,
                        help="секунды прогрева перед выборкой")
    parser.add_argument("--perf-widget", action="store_true",
                        help="показать виджет во время замера")
    parser.add_argument("--perf-report", default="")
    parser.add_argument("--perf-volume", type=float, default=0.0,
                        help="громкость на время замера (по умолчанию беззвучно)")
    parser.add_argument("--data-dir", default="")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(sys.argv[1:] if argv is None else argv)
    if args.self_test:
        from .selftest import run_self_test
        return run_self_test(play_seconds=max(1, args.play_seconds),
                             report_path=args.report or None)

    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication

    from .application.app_controller import ApplicationController
    from .logging_setup import setup_logging
    from .ui.icons import icon

    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("MyMusic.Desktop")
    except Exception:
        pass

    app = QApplication(sys.argv[:1])
    app.setApplicationName("MyMusic")
    app.setApplicationDisplayName("MyMusic")
    app.setOrganizationName("MyMusic")
    app.setQuitOnLastWindowClosed(False)
    app.setWindowIcon(icon("music"))

    service_mode = bool(args.screenshot) or args.perf is not None
    if args.data_dir:
        data_dir = Path(args.data_dir)
    elif service_mode:
        data_dir = Path(tempfile.mkdtemp(prefix="mymusic-run-"))
    else:
        data_dir = default_data_dir()
    setup_logging(data_dir / "logs", console=not getattr(sys, "frozen", False))

    single_instance = None
    if not service_mode:
        from .platform.single_instance import SingleInstance
        single_instance = SingleInstance()
        if not single_instance.acquire():
            return 0

    controller = ApplicationController(app, data_dir)
    if single_instance is not None:
        single_instance.activated.connect(controller.show_main)

    if args.screenshot:
        QTimer.singleShot(150, lambda: _run_screenshot(app, controller, Path(args.screenshot)))
    elif args.perf:
        QTimer.singleShot(150, lambda: _run_perf(
            app, controller, args.perf, max(10, args.perf_seconds),
            args.perf_report or None, args.perf_widget,
            max(0, args.perf_warmup), max(0.0, min(1.0, args.perf_volume))))
    return app.exec()


# ---- режим скриншотов ----------------------------------------------------
def _run_screenshot(app, controller, out_dir: Path) -> None:
    from .domain.models import PlaybackState
    from .util import pump_events, wait_until

    out_dir.mkdir(parents=True, exist_ok=True)
    window = controller.main_window
    window.search_edit.setText("daft punk")
    ready = wait_until(app, lambda: controller.search.state in ("ready", "empty", "error"), 45)
    tracks = list(controller.search.tracks)
    playback_state = "not_started"
    if tracks:
        controller.play_result(0)
        wait_until(app, lambda: controller.player.state in (
            PlaybackState.PLAYING, PlaybackState.ERROR), 45)
        playback_state = controller.player.state.value
    if len(tracks) > 2:
        controller.add_track(tracks[1])
        controller.add_track(tracks[2])
    if tracks:
        controller.toggle_favorite(tracks[0])
    pump_events(app, 1.0)

    window.tabs.setCurrentIndex(0)
    pump_events(app, 0.4)
    window.grab().save(str(out_dir / "main-results.png"))
    window.tabs.setCurrentIndex(1)
    pump_events(app, 0.4)
    window.grab().save(str(out_dir / "queue.png"))
    window.tabs.setCurrentIndex(2)
    pump_events(app, 0.4)
    window.grab().save(str(out_dir / "favorites.png"))
    window.tabs.setCurrentIndex(0)

    controller.set_widget_visible(True)
    pump_events(app, 0.6)
    controller.widget.grab().save(str(out_dir / "widget.png"))

    from .ui.settings_dialog import SettingsDialog
    dialog = SettingsDialog(controller)
    dialog.show()
    pump_events(app, 0.6)
    dialog.grab().save(str(out_dir / "settings.png"))
    dialog.close()

    summary = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "search_state": controller.search.state,
        "search_ready": ready,
        "results": len(tracks),
        "playback_state": playback_state,
        "current_track": (tracks[0].title if tracks else None),
        "screenshots": sorted(p.name for p in out_dir.glob("*.png")),
    }
    (out_dir / "screenshot-report.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    controller.quit()


# ---- режим замеров -------------------------------------------------------
def _run_perf(app, controller, mode: str, seconds: int,
              report_path: str | None, show_widget: bool,
              warmup: int = 60, volume: float = 0.0) -> None:
    from .benchmark import ProcessSampler, gpu_percent, percentile
    from .domain.models import Availability, PlaybackState
    from .util import pump_events, wait_until

    sampler = ProcessSampler()
    volume = max(0.0, min(1.0, volume))
    controller.player.backend.set_volume(volume)
    audio = getattr(controller.player.backend, "audio", None)
    if audio is not None:
        audio.setMuted(volume <= 0.001)
    if mode == "search":
        controller.show_main()
    else:
        controller.main_window.hide()
    if show_widget:
        controller.set_widget_visible(True)
    else:
        controller.widget.hide()
    controller.player.set_ui_visible(show_widget)

    playback_state = "idle"
    media_host = None
    search_queries = ["daft punk", "moderat", "burial", "boards of canada", "tycho"]
    next_search_at = 0.0
    search_index = 0
    if mode == "playing":
        controller.search_music("daft punk")
        wait_until(app, lambda: controller.search.state in ("ready", "error"), 45)
        tracks = list(controller.search.tracks)
        candidates = [i for i, t in enumerate(tracks) if t.availability == Availability.FULL]
        if candidates:
            resolved_hosts: list[str] = []
            from urllib.parse import urlparse
            controller.provider.resolve_done.connect(
                lambda generation, handle: resolved_hosts.append(
                    urlparse(handle.url).hostname or ""))
            controller.play_result(candidates[0])
            wait_until(app, lambda: controller.player.state in (
                PlaybackState.PLAYING, PlaybackState.ERROR), 45)
            playback_state = controller.player.state.value
            media_host = resolved_hosts[-1] if resolved_hosts else None
    elif mode == "search":
        controller.search_music(search_queries[0])
        search_index = 1
        next_search_at = 15.0
        wait_until(app, lambda: controller.search.state in ("ready", "error"), 45)

    pump_events(app, float(warmup))  # прогрев по протоколу
    previous_cpu = sampler.cpu_seconds()
    previous_time = time.monotonic()
    samples: list[dict] = []
    gpu_values: list[float] = []
    played_tracks: set[tuple[str, str]] = set()
    auto_advances = 0
    start = previous_time
    while time.monotonic() - start < seconds:
        pump_events(app, 2.0)
        if (mode == "search" and time.monotonic() - start >= next_search_at
                and seconds - (time.monotonic() - start) > 20):
            controller.search_music(search_queries[search_index % len(search_queries)])
            search_index += 1
            next_search_at += 15.0
        snapshot = controller.player.snapshot()
        if snapshot.state == PlaybackState.PLAYING and snapshot.track is not None:
            played_tracks.add(snapshot.track.key)
        elif mode == "playing" and snapshot.state == PlaybackState.ERROR and auto_advances < 30:
            auto_advances += 1
            controller.next()
        now = time.monotonic()
        cpu = sampler.cpu_seconds()
        private = sampler.private_bytes()
        wall = now - previous_time
        cpu_percent = ((cpu - previous_cpu) / wall / (os.cpu_count() or 1) * 100.0
                       if wall > 0 else 0.0)
        previous_cpu, previous_time = cpu, now
        samples.append({
            "t_s": round(now - start, 1),
            "cpu_percent": round(cpu_percent, 4),
            "private_mib": round(private / (1024 * 1024), 2),
        })
        if len(samples) % 5 == 0 and playback_state == "playing":
            value = gpu_percent(sampler.pid)
            if value is not None:
                gpu_values.append(value)

    cpu_values = [s["cpu_percent"] for s in samples]
    private_values = [s["private_mib"] for s in samples]
    if mode == "search":
        wait_until(app, lambda: controller.search.state in ("ready", "error"), 10)
    final = controller.player.snapshot()
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "mode": mode,
        "widget_visible": show_widget,
        "playback_state": playback_state,
        "playback_state_end": final.state.value,
        "position_ms_end": final.position_ms,
        "tracks_played": len(played_tracks),
        "auto_advances": auto_advances,
        "error_end": final.error,
        "search_state_end": controller.search.state,
        "search_results_end": len(controller.search.tracks),
        "media_host": media_host,
        "platform": platform.platform(),
        "cpu_count": os.cpu_count(),
        "python": sys.version.split()[0],
        "warmup_s": warmup,
        "volume": volume,
        "duration_s": seconds,
        "samples": samples,
        "cpu_percent_avg": round(sum(cpu_values) / len(cpu_values), 4) if cpu_values else 0,
        "cpu_percent_p95": round(percentile(cpu_values, 0.95), 4),
        "private_mib_avg": round(sum(private_values) / len(private_values), 2) if private_values else 0,
        "private_mib_max": max(private_values) if private_values else 0,
        "private_mib_first": private_values[0] if private_values else 0,
        "private_mib_end": private_values[-1] if private_values else 0,
        "private_mib_delta": round(private_values[-1] - private_values[0], 2) if private_values else 0,
        "gpu_percent_avg": round(sum(gpu_values) / len(gpu_values), 3) if gpu_values else None,
        "gpu_percent_max": max(gpu_values) if gpu_values else None,
        "process_count": 1,
    }
    if report_path:
        path = Path(report_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    sampler.close()
    controller.quit()


if __name__ == "__main__":
    raise SystemExit(main())
