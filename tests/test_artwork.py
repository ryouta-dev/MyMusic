import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QBuffer, QIODevice, Qt
from PySide6.QtGui import QImage
from PySide6.QtNetwork import QNetworkReply
from PySide6.QtWidgets import QApplication

from mymusic.ui import artwork as artwork_module
from mymusic.ui.artwork import ArtworkCache


class _FakeReply:
    def __init__(self, data: bytes):
        self._data = data

    def error(self):
        return QNetworkReply.NetworkError.NoError

    def readAll(self):
        return self._data

    def deleteLater(self):
        pass


def _png_bytes() -> bytes:
    image = QImage(32, 16, QImage.Format.Format_RGB32)
    image.fill(Qt.GlobalColor.darkRed)
    buffer = QBuffer()
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    image.save(buffer, "PNG")
    return bytes(buffer.data())


class ArtworkCacheTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.cache_dir = Path(self.temp.name) / "artwork"
        self.cache = ArtworkCache(self.cache_dir)

    def test_cache_key_is_stable_and_path_is_under_cache_dir(self):
        url = "https://cdn.audius.co/art.jpg"
        self.assertEqual(ArtworkCache.key_for(url), ArtworkCache.key_for(url))
        self.assertNotEqual(ArtworkCache.key_for(url), ArtworkCache.key_for(url + "?2"))
        self.assertIsNone(self.cache.cached_path(url))

    def test_insecure_url_is_not_requested(self):
        self.assertIsNone(self.cache.request("http://cdn.audius.co/art.jpg"))
        self.assertIsNone(self.cache.request("https://evil.example/art.jpg"))

    def test_downloaded_image_is_scaled_and_cached(self):
        ready = []
        self.cache.ready.connect(lambda url, path: ready.append((url, path)))
        url = "https://cdn.audius.co/art.png"
        self.cache._on_finished(url, _FakeReply(_png_bytes()))
        self.assertEqual(len(ready), 1)
        self.assertEqual(ready[0][0], url)
        path = Path(ready[0][1])
        self.assertTrue(path.is_file())
        stored = QImage(str(path))
        self.assertFalse(stored.isNull())
        self.assertLessEqual(max(stored.width(), stored.height()), 256)

    def test_eviction_removes_oldest_files_until_under_limit(self):
        now = time.time()
        files = []
        for index in range(6):
            path = self.cache_dir / f"{index:032x}.jpg"
            path.write_bytes(b"x" * 4096)
            os.utime(path, (now - 100 + index, now - 100 + index))
            files.append(path)
        with mock.patch.object(artwork_module, "MAX_CACHE_BYTES", 10_000):
            self.cache._evict()
        remaining = sorted(self.cache_dir.glob("*.jpg"))
        total = sum(path.stat().st_size for path in remaining)
        self.assertLessEqual(total, 10_000)
        self.assertNotIn(files[0], remaining)
        self.assertIn(files[-1], remaining)

    def test_eviction_keeps_files_when_under_limit(self):
        path = self.cache_dir / "keep.jpg"
        path.write_bytes(b"x" * 100)
        self.cache._evict()
        self.assertTrue(path.is_file())


if __name__ == "__main__":
    unittest.main()
