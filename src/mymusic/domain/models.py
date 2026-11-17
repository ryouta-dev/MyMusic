"""Доменные модели. Не зависят от Qt и сети."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


PROVIDER_AUDIUS = "audius"


@dataclass(frozen=True)
class TrackRef:
    provider_id: str
    track_id: str


class Availability(str, Enum):
    FULL = "full"
    PREVIEW = "preview"
    UNAVAILABLE = "unavailable"


@dataclass
class Track:
    ref: TrackRef
    title: str
    artist: str
    duration_ms: int | None = None
    artwork_url: str | None = None
    source_page_url: str = ""
    availability: Availability = Availability.FULL
    attribution: str | None = "Audius"

    @property
    def key(self) -> tuple[str, str]:
        return (self.ref.provider_id, self.ref.track_id)


@dataclass
class SearchPage:
    tracks: list[Track]
    next_offset: int | None


@dataclass(frozen=True)
class Capabilities:
    can_search: bool = True
    can_background: bool = True
    can_seek: bool = True
    can_previous: bool = True
    can_next: bool = True
    supports_full_track: bool = True
    requires_auth: bool = False


class ErrorKind(str, Enum):
    OFFLINE = "offline"
    UNAUTHORIZED = "unauthorized"
    SUBSCRIPTION_REQUIRED = "subscription_required"
    RATE_LIMITED = "rate_limited"
    UNAVAILABLE = "unavailable"
    FORBIDDEN = "forbidden"
    UNSUPPORTED = "unsupported"
    TRANSIENT = "transient"
    CANCELLED = "cancelled"


class ProviderError(Exception):
    """Пользовательский текст не содержит токенов и внутренних URL."""

    def __init__(self, kind: ErrorKind, user_message: str,
                 retry_after_s: int | None = None, detail: str = ""):
        super().__init__(user_message)
        self.kind = kind
        self.user_message = user_message
        self.retry_after_s = retry_after_s
        self.detail = detail

    def __str__(self) -> str:
        return self.user_message


class PlaybackState(str, Enum):
    IDLE = "idle"
    RESOLVING = "resolving"
    BUFFERING = "buffering"
    PLAYING = "playing"
    PAUSED = "paused"
    ENDED = "ended"
    ERROR = "error"
    SHUTTING_DOWN = "shutting_down"


@dataclass
class PlaybackHandle:
    url: str
    handle_type: str = "direct_audio"
    expires_at: float | None = None


@dataclass
class PlaybackSnapshot:
    state: PlaybackState
    track: Track | None = None
    position_ms: int = 0
    duration_ms: int | None = None
    volume: float = 0.8
    can_seek: bool = True
    error: str | None = None
    queue_count: int = 0
    queue_index: int = -1
