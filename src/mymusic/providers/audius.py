"""Провайдер Audius: открытый каталог, поиск и краткоживущие direct-audio ссылки."""
from __future__ import annotations

import json
import time
from urllib.parse import quote, urljoin, urlparse

from PySide6.QtCore import QObject, QTimer, QUrl, QUrlQuery, Signal
from PySide6.QtNetwork import (QNetworkAccessManager, QNetworkReply, QNetworkRequest)

from ..domain.models import (Availability, ErrorKind, PlaybackHandle, ProviderError,
                             SearchPage, Track, TrackRef)

PROVIDER_ID = "audius"
APP_NAME = "MyMusic"
API_BASE = "https://api.audius.co/v1"
FALLBACK_BASE = "https://discoveryprovider.audius.co/v1"
REQUEST_TIMEOUT_MS = 15_000
MAX_PARALLEL = 3
PAGE_SIZE = 30

# Доверенные домены каталога и его медиа-CDNs. Redirect на любой другой хост
# отклоняется, чтобы метаданные не могли увести медиапоток на произвольный сервер.
ALLOWED_MEDIA_DOMAINS = (
    "audius.co",
    "open-audio-validator.com",
    "theblueprint.xyz",
    "monophonic.digital",
    "cloudflarestorage.com",
    "audius.foundation",
)


def host_allowed(url: str) -> bool:
    try:
        parsed = urlparse(url)
    except ValueError:
        return False
    if parsed.scheme.lower() != "https" or not parsed.hostname:
        return False
    host = parsed.hostname.lower().rstrip(".")
    return any(host == domain or host.endswith("." + domain)
               for domain in ALLOWED_MEDIA_DOMAINS)


def parse_track(item: dict) -> Track | None:
    if not isinstance(item, dict):
        return None
    track_id = item.get("id")
    if not isinstance(track_id, str) or not track_id:
        return None
    title = str(item.get("title") or "").strip() or "Без названия"
    user = item.get("user") if isinstance(item.get("user"), dict) else {}
    artist = str(user.get("name") or item.get("artist") or "Неизвестный исполнитель").strip()
    duration_ms = None
    duration = item.get("duration")
    if isinstance(duration, (int, float)) and duration > 0:
        duration_ms = int(duration * 1000)
    artwork = item.get("artwork") if isinstance(item.get("artwork"), dict) else {}
    artwork_url = None
    for size in ("480x480", "150x150", "1000x1000"):
        candidate = artwork.get(size)
        if isinstance(candidate, str) and candidate.startswith("https://"):
            artwork_url = candidate
            break
    availability = Availability.FULL
    if item.get("is_stream_gated"):
        availability = Availability.UNAVAILABLE
    elif item.get("preview") is True or (item.get("preview_cid") and item.get("is_streamable") is False):
        availability = Availability.PREVIEW
    elif item.get("is_streamable") is False:
        availability = Availability.UNAVAILABLE
    permalink = item.get("permalink")
    source_page = ""
    if isinstance(permalink, str) and permalink.startswith("/"):
        source_page = "https://audius.co" + permalink
    return Track(
        ref=TrackRef(PROVIDER_ID, track_id),
        title=title,
        artist=artist,
        duration_ms=duration_ms,
        artwork_url=artwork_url,
        source_page_url=source_page,
        availability=availability,
        attribution="Audius",
    )


def parse_search(payload: dict, offset: int, limit: int) -> SearchPage:
    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, list):
        raise ProviderError(ErrorKind.UNSUPPORTED,
                            "Источник вернул неожиданный ответ. Попробуйте позже.")
    tracks = [t for t in (parse_track(item) for item in data) if t is not None]
    next_offset = offset + len(data) if len(data) >= limit else None
    return SearchPage(tracks=tracks, next_offset=next_offset)


def classify_http(status: int, retry_after: str | None = None) -> ProviderError:
    retry_s = _retry_after_seconds(retry_after)
    if status == 401:
        return ProviderError(ErrorKind.UNAUTHORIZED,
                             "Источник требует авторизации. Подключение недоступно.")
    if status == 403:
        return ProviderError(ErrorKind.FORBIDDEN,
                             "Источник запретил доступ к этому треку.", retry_s)
    if status == 404:
        return ProviderError(ErrorKind.UNAVAILABLE, "Трек или страница не найдены.")
    if status == 429:
        hint = f" Повторите через {retry_s} с." if retry_s else " Повторите позже."
        return ProviderError(ErrorKind.RATE_LIMITED,
                             "Слишком много запросов к источнику." + hint, retry_s)
    if status == 451:
        return ProviderError(ErrorKind.UNAVAILABLE,
                             "Трек недоступен в вашем регионе.")
    if status >= 500:
        return ProviderError(ErrorKind.TRANSIENT,
                             "Источник временно недоступен. Попробуйте ещё раз.", retry_s)
    return ProviderError(ErrorKind.UNAVAILABLE,
                         "Не удалось получить данные из источника.", retry_s)


def _retry_after_seconds(value: str | None) -> int | None:
    if not value:
        return None
    try:
        seconds = int(value)
        return seconds if 0 <= seconds <= 3600 else None
    except ValueError:
        return None


def _decode_location(raw: bytes) -> str | None:
    try:
        text = raw.decode("latin-1").strip()
    except Exception:
        return None
    return text or None


class AudiusClient(QObject):
    search_done = Signal(int, object)
    search_failed = Signal(int, object)
    resolve_done = Signal(int, object)
    resolve_failed = Signal(int, object)
    provider_status = Signal(str)

    def __init__(self, parent=None, base_url: str = API_BASE):
        super().__init__(parent)
        self._base_url = base_url.rstrip("/")
        self._nam = QNetworkAccessManager(self)
        self._search_reply: QNetworkReply | None = None
        self._resolve_reply: QNetworkReply | None = None
        self._search_attempt = 0
        self._resolve_attempt = 0
        self._fail_count = 0

    # ---- поиск -------------------------------------------------------
    def search(self, query: str, offset: int, generation: int, limit: int = PAGE_SIZE) -> None:
        self.cancel_search()
        self._search_attempt = 0
        self._start_search(query, offset, generation, limit)

    def _start_search(self, query: str, offset: int, generation: int, limit: int) -> None:
        url = QUrl(self._base_url + "/tracks/search")
        params = QUrlQuery()
        params.addQueryItem("query", query)
        params.addQueryItem("limit", str(limit))
        params.addQueryItem("offset", str(offset))
        params.addQueryItem("app_name", APP_NAME)
        url.setQuery(params)
        request = self._request(url)
        reply = self._nam.get(request)
        self._search_reply = reply
        self._attach_timeout(reply)
        reply.finished.connect(
            lambda: self._on_search(reply, query, offset, generation, limit))

    def _on_search(self, reply: QNetworkReply, query: str, offset: int,
                   generation: int, limit: int) -> None:
        reply.deleteLater()
        if self._search_reply is reply:
            self._search_reply = None
        if reply.property("timed_out") or reply.error() == QNetworkReply.OperationCanceledError:
            if reply.property("timed_out") and self._search_attempt < 1:
                next_base = alternative_api_base(self._base_url)
                if next_base is not None:
                    self._search_attempt += 1
                    self._base_url = next_base
                    QTimer.singleShot(1200, lambda: self._start_search(
                        query, offset, generation, limit))
                    return
            self._emit_search_failure(generation, ProviderError(
                ErrorKind.TRANSIENT, "Источник не ответил вовремя. Попробуйте ещё раз."))
            return
        status = reply.attribute(QNetworkRequest.HttpStatusCodeAttribute) or 0
        if status == 0:
            error = self._network_error(reply)
            if (self._search_attempt < 1
                    and error.kind in (ErrorKind.TRANSIENT, ErrorKind.OFFLINE)):
                next_base = alternative_api_base(self._base_url)
                if next_base is not None:
                    self._search_attempt += 1
                    self._base_url = next_base
                    QTimer.singleShot(1200, lambda: self._start_search(
                        query, offset, generation, limit))
                    return
            self._emit_search_failure(generation, error)
            return
        body = bytes(reply.readAll())
        if status != 200:
            self._emit_search_failure(generation, classify_http(
                status, reply.rawHeader("Retry-After").data().decode() or None))
            return
        try:
            payload = json.loads(body.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            self._emit_search_failure(generation, ProviderError(
                ErrorKind.UNSUPPORTED, "Источник вернул некорректные данные."))
            return
        try:
            page = parse_search(payload, offset, limit)
        except ProviderError as error:
            self._emit_search_failure(generation, error)
            return
        self._fail_count = 0
        self.provider_status.emit("Audius: подключено")
        self.search_done.emit(generation, page)

    def _emit_search_failure(self, generation: int, error: ProviderError) -> None:
        self._fail_count += 1
        if error.kind in (ErrorKind.OFFLINE, ErrorKind.TRANSIENT):
            self.provider_status.emit("Audius: нет стабильного соединения")
        self.search_failed.emit(generation, error)

    def cancel_search(self) -> None:
        if self._search_reply is not None:
            reply = self._search_reply
            self._search_reply = None
            reply.abort()
            reply.deleteLater()

    # ---- разрешение потока -------------------------------------------
    def resolve(self, track_ref: TrackRef, generation: int) -> None:
        self.cancel_resolve()
        self._resolve_attempt = 0
        url = (f"{self._base_url}/tracks/{quote(track_ref.track_id, safe='')}"
               f"/stream?app_name={APP_NAME}")
        self._start_resolve(url, generation, hops=0, attempt=0)

    def _start_resolve(self, url: str, generation: int, hops: int, attempt: int) -> None:
        if hops > 5:
            self.resolve_failed.emit(generation, ProviderError(
                ErrorKind.FORBIDDEN, "Источник перенаправил запрос по недопустимой цепочке."))
            return
        request = self._request(QUrl(url))
        request.setAttribute(QNetworkRequest.RedirectPolicyAttribute,
                             QNetworkRequest.ManualRedirectPolicy)
        request.setRawHeader(b"Range", b"bytes=0-0")
        reply = self._nam.get(request)
        self._resolve_reply = reply
        self._attach_timeout(reply)
        reply.finished.connect(
            lambda: self._on_resolve(reply, url, generation, hops, attempt))

    def _on_resolve(self, reply: QNetworkReply, current_url: str,
                    generation: int, hops: int, attempt: int) -> None:
        reply.deleteLater()
        if self._resolve_reply is reply:
            self._resolve_reply = None
        if reply.property("timed_out") or reply.error() == QNetworkReply.OperationCanceledError:
            if reply.property("timed_out") and attempt < 2:
                QTimer.singleShot(1200, lambda: self._start_resolve(
                    current_url, generation, hops, attempt + 1))
                return
            self.resolve_failed.emit(generation, ProviderError(
                ErrorKind.TRANSIENT,
                "Источник не ответил вовремя. Проверьте соединение и повторите."))
            return
        status = reply.attribute(QNetworkRequest.HttpStatusCodeAttribute) or 0
        if status in (301, 302, 303, 307, 308):
            location = _decode_location(bytes(reply.rawHeader("Location")))
            if not location:
                self.resolve_failed.emit(generation, ProviderError(
                    ErrorKind.TRANSIENT, "Источник вернул пустое перенаправление."))
                return
            next_url = urljoin(current_url, location)
            if not host_allowed(next_url):
                self.resolve_failed.emit(generation, ProviderError(
                    ErrorKind.FORBIDDEN,
                    "Источник перенаправил на недоверенный адрес. Воспроизведение остановлено."))
                return
            self._start_resolve(next_url, generation, hops + 1, attempt)
            return
        if status == 0:
            error = self._network_error(reply)
            if attempt < 2 and error.kind == ErrorKind.TRANSIENT:
                QTimer.singleShot(1200, lambda: self._start_resolve(
                    current_url, generation, hops, attempt + 1))
                return
            self.resolve_failed.emit(generation, error)
            return
        if status in (200, 206):
            if not host_allowed(current_url):
                self.resolve_failed.emit(generation, ProviderError(
                    ErrorKind.FORBIDDEN,
                    "Источник вернул недоверенный адрес потока. Воспроизведение остановлено."))
                return
            self.resolve_done.emit(
                generation, PlaybackHandle(url=current_url, expires_at=time.time() + 7000))
            return
        self.resolve_failed.emit(generation, classify_http(
            status, reply.rawHeader("Retry-After").data().decode() or None))

    def cancel_resolve(self) -> None:
        if self._resolve_reply is not None:
            reply = self._resolve_reply
            self._resolve_reply = None
            reply.abort()
            reply.deleteLater()

    def cancel_all(self) -> None:
        self.cancel_search()
        self.cancel_resolve()

    # ---- служебное ----------------------------------------------------
    def _request(self, url: QUrl) -> QNetworkRequest:
        request = QNetworkRequest(url)
        request.setHeader(QNetworkRequest.UserAgentHeader, "MyMusic/0.1 (Windows)")
        request.setRawHeader(b"Accept", b"application/json, audio/*")
        # Qt 6.12 HTTP/2 зависает на медиа-CDN Audius; HTTP/1.1 проверен на реальном потоке.
        request.setAttribute(QNetworkRequest.Http2AllowedAttribute, False)
        request.setAttribute(QNetworkRequest.RedirectPolicyAttribute,
                             QNetworkRequest.NoLessSafeRedirectPolicy)
        return request

    def _attach_timeout(self, reply: QNetworkReply) -> None:
        timer = QTimer(reply)
        timer.setSingleShot(True)
        timer.setInterval(REQUEST_TIMEOUT_MS)
        timer.timeout.connect(lambda: (reply.setProperty("timed_out", True), reply.abort()))
        reply.finished.connect(timer.stop)
        timer.start()

    @staticmethod
    def _network_error(reply: QNetworkReply) -> ProviderError:
        error = reply.error()
        if error in (QNetworkReply.HostNotFoundError, QNetworkReply.UnknownNetworkError,
                     QNetworkReply.NetworkSessionFailedError):
            return ProviderError(ErrorKind.OFFLINE,
                                 "Нет подключения к интернету. Проверьте сеть и повторите.")
        if error in (QNetworkReply.TimeoutError, QNetworkReply.TemporaryNetworkFailureError,
                     QNetworkReply.OperationCanceledError):
            return ProviderError(ErrorKind.TRANSIENT,
                                 "Соединение прервалось. Попробуйте ещё раз.")
        if error in (QNetworkReply.SslHandshakeFailedError,
                     QNetworkReply.ContentAccessDenied):
            return ProviderError(ErrorKind.FORBIDDEN,
                                 "Защищённое соединение с источником отклонено.")
        return ProviderError(ErrorKind.TRANSIENT,
                             "Ошибка сети при обращении к источнику. Попробуйте ещё раз.")


# Резервный адрес только для известных gateway; сторонний base не подменяется.
def alternative_api_base(used: str) -> str | None:
    if used == API_BASE:
        return FALLBACK_BASE
    if used == FALLBACK_BASE:
        return API_BASE
    return None
