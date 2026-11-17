"""Диагностика памяти: переключение треков с обложками и без них."""
from __future__ import annotations

import argparse
import tempfile
import time
from pathlib import Path

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from mymusic.application.app_controller import ApplicationController
from mymusic.benchmark import ProcessSampler
from mymusic.domain.models import PlaybackState
from mymusic.util import pump_events, wait_until


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--transitions", type=int, default=12)
    parser.add_argument("--seconds", type=float, default=8.0)
    parser.add_argument("--no-artwork", action="store_true")
    parser.add_argument("--clear-source", action="store_true")
    parser.add_argument("--new-player", action="store_true")
    args = parser.parse_args()

    app = QApplication([])
    data_dir = Path(tempfile.mkdtemp(prefix="mymusic-probe-"))
    controller = ApplicationController(app, data_dir)
    controller.main_window.hide()
    controller.widget.hide()
    controller.player.set_ui_visible(False)
    controller.player.backend.set_volume(0.0)
    controller.player.backend.audio.setMuted(True)
    if args.no_artwork:
        controller.artwork.request = lambda url: None
    if args.clear_source:
        from PySide6.QtCore import QUrl
        backend = controller.player.backend
        original_load = backend.load

        def load_clearing(url: str) -> None:
            backend.player.stop()
            backend.player.setSource(QUrl())
            app.processEvents()
            original_load(url)

        backend.load = load_clearing
    if args.new_player:
        from PySide6.QtCore import QUrl
        from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
        backend = controller.player.backend

        def load_new_player(url: str) -> None:
            old_player, old_audio = backend.player, backend.audio
            old_player.stop()
            old_player.setAudioOutput(None)
            old_player.setSource(QUrl())
            old_player.deleteLater()
            old_audio.deleteLater()
            player = QMediaPlayer(backend)
            audio = QAudioOutput(backend)
            player.setAudioOutput(audio)
            player.playbackStateChanged.connect(backend._on_state)
            player.mediaStatusChanged.connect(backend._on_status)
            player.positionChanged.connect(backend.position_changed)
            player.durationChanged.connect(backend.duration_changed)
            player.errorOccurred.connect(backend._on_error)
            backend.player, backend.audio = player, audio
            audio.setVolume(0.0)
            audio.setMuted(True)
            backend._source_loaded = True
            player.setSource(QUrl(url))
            app.processEvents()

        backend.load = load_new_player

    controller.search_music("daft punk")
    wait_until(app, lambda: controller.search.state in ("ready", "error"), 45)
    if controller.search.state != "ready" or not controller.search.tracks:
        print("search failed", controller.search.state)
        return 1
    controller.play_result(0)
    wait_until(app, lambda: controller.player.state in (
        PlaybackState.PLAYING, PlaybackState.ERROR), 45)

    sampler = ProcessSampler()
    first = sampler.private_bytes() / (1024 * 1024)
    print(f"start {first:.2f} MiB state={controller.player.state.value}")
    for index in range(args.transitions):
        pump_events(app, args.seconds)
        snapshot = controller.player.snapshot()
        private = sampler.private_bytes() / (1024 * 1024)
        title = snapshot.track.title[:28] if snapshot.track else "-"
        print(f"{index + 1:02d} {private:7.2f} MiB delta={private - first:6.2f} "
              f"state={snapshot.state.value:9s} tracks={title}")
        controller.next()
    pump_events(app, 3.0)
    final = sampler.private_bytes() / (1024 * 1024)
    print(f"end {final:.2f} MiB total_delta={final - first:.2f}")
    sampler.close()
    controller._shutdown()
    QTimer.singleShot(0, app.quit)
    app.exec()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
