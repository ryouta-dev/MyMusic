"""Аудиобэкенд Qt Multimedia: единственный экземпляр QMediaPlayer."""
from __future__ import annotations

from PySide6.QtCore import QObject, QUrl, Signal
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer


class QtAudioBackend(QObject):
    playing = Signal()
    paused = Signal()
    stopped = Signal()
    buffering = Signal(bool)
    position_changed = Signal("qlonglong")
    duration_changed = Signal("qlonglong")
    ended = Signal()
    error = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.player = QMediaPlayer(self)
        self.audio = QAudioOutput(self)
        self.player.setAudioOutput(self.audio)
        self.player.playbackStateChanged.connect(self._on_state)
        self.player.mediaStatusChanged.connect(self._on_status)
        self.player.positionChanged.connect(self.position_changed)
        self.player.durationChanged.connect(self.duration_changed)
        self.player.errorOccurred.connect(self._on_error)
        self._source_loaded = False

    def load(self, url: str) -> None:
        self._source_loaded = True
        self.player.setSource(QUrl(url))

    def play(self) -> None:
        if self._source_loaded:
            self.player.play()

    def pause(self) -> None:
        self.player.pause()

    def stop(self) -> None:
        self.player.stop()

    def seek(self, position_ms: int) -> None:
        if self._source_loaded:
            self.player.setPosition(max(0, int(position_ms)))

    def set_volume(self, volume: float) -> None:
        self.audio.setVolume(min(1.0, max(0.0, float(volume))))

    def position(self) -> int:
        return int(self.player.position())

    def duration(self) -> int:
        return int(self.player.duration())

    def has_source(self) -> bool:
        return self._source_loaded

    def release(self) -> None:
        try:
            self.player.stop()
            self.player.setSource(QUrl())
            self.player.setAudioOutput(None)
        except RuntimeError:
            pass

    def _on_state(self, state) -> None:
        if state == QMediaPlayer.PlayingState:
            self.playing.emit()
        elif state == QMediaPlayer.PausedState:
            self.paused.emit()
        elif state == QMediaPlayer.StoppedState:
            self.stopped.emit()

    def _on_status(self, status) -> None:
        if status in (QMediaPlayer.BufferingMedia, QMediaPlayer.StalledMedia):
            self.buffering.emit(True)
        elif status in (QMediaPlayer.BufferedMedia, QMediaPlayer.LoadedMedia):
            self.buffering.emit(False)
        elif status == QMediaPlayer.EndOfMedia:
            self.ended.emit()
        elif status == QMediaPlayer.InvalidMedia:
            self.error.emit("Не удалось воспроизвести трек: неподдерживаемый формат или поток.")

    def _on_error(self, error, message: str) -> None:
        if error == QMediaPlayer.NoError:
            return
        self.error.emit("Не удалось воспроизвести трек. Попробуйте следующий.")
