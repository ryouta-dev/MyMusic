"""Кэш обложек: максимум 5 МиБ на загрузку, 50 МиБ на диске, 256x256."""
from __future__ import annotations

import hashlib
import time
from pathlib import Path

from PySide6.QtCore import QObject, QTimer, QUrl, Qt, Signal
from PySide6.QtGui import QImage
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest

from ..providers.audius import host_allowed

MAX_DOWNLOAD_BYTES = 5 * 1024 * 1024
MAX_CACHE_BYTES = 50 * 1024 * 1024


class ArtworkCache(QObject):
    ready = Signal(str, str)  # artwork_url key, local path

    def __init__(self, cache_dir: Path, parent=None):
        super().__init__(parent)
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._nam = QNetworkAccessManager(self)
        self._pending: dict[str, QNetworkReply] = {}

    @staticmethod
    def key_for(url: str) -> str:
        return hashlib.sha256(url.encode("utf-8")).hexdigest()[:32]

    def cached_path(self, url: str) -> str | None:
        path = self.cache_dir / f"{self.key_for(url)}.jpg"
        if path.is_file():
            try:
                path.touch()
            except OSError:
                pass
            return str(path)
        return None

    def request(self, url: str) -> str | None:
        cached = self.cached_path(url)
        if cached:
            return cached
        if url in self._pending or not host_allowed(url):
            return None
        request = QNetworkRequest(QUrl(url))
        request.setHeader(QNetworkRequest.UserAgentHeader, "MyMusic/0.1")
        request.setAttribute(QNetworkRequest.Http2AllowedAttribute, False)
        reply = self._nam.get(request)
        self._pending[url] = reply
        timer = QTimer(reply)
        timer.setSingleShot(True)
        timer.setInterval(15_000)
        timer.timeout.connect(reply.abort)
        reply.finished.connect(timer.stop)
        timer.start()
        reply.finished.connect(lambda: self._on_finished(url, reply))
        return None

    def _on_finished(self, url: str, reply: QNetworkReply) -> None:
        self._pending.pop(url, None)
        reply.deleteLater()
        if reply.error() != QNetworkReply.NoError:
            return
        data = bytes(reply.readAll())
        if not data or len(data) > MAX_DOWNLOAD_BYTES:
            return
        image = QImage.fromData(data)
        if image.isNull():
            return
        image = image.scaled(256, 256, Qt.AspectRatioMode.KeepAspectRatio,
                             Qt.TransformationMode.SmoothTransformation)
        path = self.cache_dir / f"{self.key_for(url)}.jpg"
        tmp = path.with_suffix(".tmp")
        if image.save(str(tmp), "JPG", 85):
            tmp.replace(path)
            self._evict()
            self.ready.emit(url, str(path))

    def _evict(self) -> None:
        files = []
        total = 0
        for path in self.cache_dir.glob("*.jpg"):
            try:
                stat = path.stat()
            except OSError:
                continue
            files.append((stat.st_mtime, stat.st_size, path))
            total += stat.st_size
        if total <= MAX_CACHE_BYTES:
            return
        for _, size, path in sorted(files):
            try:
                path.unlink()
            except OSError:
                continue
            total -= size
            if total <= MAX_CACHE_BYTES:
                break
