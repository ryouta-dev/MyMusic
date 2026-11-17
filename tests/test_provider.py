"""Разбор ответов Audius, классификация ошибок и allowlist медиа-доменов."""
from __future__ import annotations

import unittest

from mymusic.domain.models import Availability, ErrorKind
from mymusic.providers.audius import (API_BASE, APP_NAME, FALLBACK_BASE, alternative_api_base,
                                      classify_http, host_allowed, parse_search, parse_track,
                                      _retry_after_seconds)

from .support import make_track


def sample_item(**overrides) -> dict:
    item = {
        "id": "D7KyD",
        "title": "  Work It  ",
        "duration": 187.5,
        "user": {"name": "chromonicci"},
        "artwork": {"150x150": "https://cdn.audius.co/small.jpg",
                    "480x480": "https://cdn.audius.co/big.jpg"},
        "permalink": "/chromonicci/workit",
    }
    item.update(overrides)
    return item


class HostAllowlistTests(unittest.TestCase):
    def test_trusted_hosts(self):
        for url in (
            "https://audius.co/track",
            "https://api.audius.co/v1/tracks/1/stream",
            "https://creatornode.audius.co/x",
            "https://r2.cloudflarestorage.com/bucket",
            "https://open-audio-validator.com/a",
            "https://media.theblueprint.xyz/a",
            "https://monophonic.digital/a",
            "https://audius.foundation/a",
        ):
            with self.subTest(url=url):
                self.assertTrue(host_allowed(url))

    def test_untrusted_hosts_rejected(self):
        for url in (
            "http://audius.co/track",
            "https://audius.co.evil.example/track",
            "https://evil-audius.co/track",
            "https://notaudius.co/track",
            "https://cloudflarestorage.com.evil.example/a",
            "ftp://audius.co/a",
            "https://",
            "not a url",
            "",
        ):
            with self.subTest(url=url):
                self.assertFalse(host_allowed(url))

    def test_trailing_dot_and_case(self):
        self.assertTrue(host_allowed("https://API.AUDIUS.CO./v1"))


class ParseTrackTests(unittest.TestCase):
    def test_parses_metadata(self):
        track = parse_track(sample_item())
        self.assertIsNotNone(track)
        self.assertEqual(track.ref.track_id, "D7KyD")
        self.assertEqual(track.ref.provider_id, "audius")
        self.assertEqual(track.title, "Work It")
        self.assertEqual(track.artist, "chromonicci")
        self.assertEqual(track.duration_ms, 187_500)
        self.assertEqual(track.artwork_url, "https://cdn.audius.co/big.jpg")
        self.assertEqual(track.source_page_url, "https://audius.co/chromonicci/workit")
        self.assertEqual(track.availability, Availability.FULL)
        self.assertEqual(track.attribution, "Audius")

    def test_rejects_missing_or_invalid_id(self):
        self.assertIsNone(parse_track({}))
        self.assertIsNone(parse_track({"id": ""}))
        self.assertIsNone(parse_track({"id": 5}))
        self.assertIsNone(parse_track("not a dict"))

    def test_fallbacks_for_empty_fields(self):
        track = parse_track({"id": "x", "title": "   ", "user": {}})
        self.assertEqual(track.title, "Без названия")
        self.assertEqual(track.artist, "Неизвестный исполнитель")
        self.assertIsNone(track.duration_ms)
        self.assertIsNone(track.artwork_url)
        self.assertEqual(track.source_page_url, "")

    def test_availability_flags(self):
        self.assertEqual(parse_track(sample_item(is_stream_gated=True)).availability,
                         Availability.UNAVAILABLE)
        self.assertEqual(parse_track(sample_item(preview=True)).availability,
                         Availability.PREVIEW)
        self.assertEqual(parse_track(sample_item(preview_cid="cid", is_streamable=False)).availability,
                         Availability.PREVIEW)
        self.assertEqual(parse_track(sample_item(is_streamable=False)).availability,
                         Availability.UNAVAILABLE)

    def test_artwork_must_be_https(self):
        track = parse_track(sample_item(artwork={"480x480": "http://insecure/art.jpg"}))
        self.assertIsNone(track.artwork_url)

    def test_artist_from_legacy_field(self):
        track = parse_track({"id": "x", "artist": "Legacy Artist"})
        self.assertEqual(track.artist, "Legacy Artist")


class ParseSearchTests(unittest.TestCase):
    def test_full_page_has_next_offset(self):
        payload = {"data": [sample_item(id=str(i)) for i in range(30)]}
        page = parse_search(payload, 0, 30)
        self.assertEqual(len(page.tracks), 30)
        self.assertEqual(page.next_offset, 30)

    def test_partial_page_is_last(self):
        payload = {"data": [sample_item(id=str(i)) for i in range(12)]}
        page = parse_search(payload, 30, 30)
        self.assertIsNone(page.next_offset)

    def test_empty_page(self):
        page = parse_search({"data": []}, 0, 30)
        self.assertEqual(page.tracks, [])
        self.assertIsNone(page.next_offset)

    def test_invalid_payload_raises(self):
        from mymusic.domain.models import ProviderError
        for payload in ({}, {"data": {}}, [], {"data": "x"}):
            with self.subTest(payload=payload):
                with self.assertRaises(ProviderError):
                    parse_search(payload, 0, 30)

    def test_invalid_items_are_skipped(self):
        payload = {"data": [sample_item(), {"no_id": True}, "junk"]}
        page = parse_search(payload, 0, 30)
        self.assertEqual(len(page.tracks), 1)


class ErrorClassificationTests(unittest.TestCase):
    def test_status_mapping(self):
        expected = {
            401: ErrorKind.UNAUTHORIZED,
            403: ErrorKind.FORBIDDEN,
            404: ErrorKind.UNAVAILABLE,
            429: ErrorKind.RATE_LIMITED,
            451: ErrorKind.UNAVAILABLE,
            500: ErrorKind.TRANSIENT,
            503: ErrorKind.TRANSIENT,
            418: ErrorKind.UNAVAILABLE,
        }
        for status, kind in expected.items():
            with self.subTest(status=status):
                self.assertEqual(classify_http(status).kind, kind)

    def test_retry_after_is_parsed_and_bounded(self):
        self.assertEqual(classify_http(429, "30").retry_after_s, 30)
        self.assertIsNone(classify_http(429, "-5").retry_after_s)
        self.assertIsNone(classify_http(429, "999999").retry_after_s)
        self.assertIsNone(classify_http(429, "soon").retry_after_s)
        self.assertIsNone(classify_http(429, None).retry_after_s)
        self.assertEqual(classify_http(503, "0").retry_after_s, 0)

    def test_rate_limited_message_mentions_delay(self):
        message = classify_http(429, "45").user_message
        self.assertIn("45", message)

    def test_alternative_base(self):
        self.assertEqual(alternative_api_base(API_BASE), FALLBACK_BASE)
        self.assertEqual(alternative_api_base(FALLBACK_BASE), API_BASE)
        self.assertIsNone(alternative_api_base("https://offline-check.mymusic.invalid/v1"))

    def test_app_name_is_declared(self):
        self.assertEqual(APP_NAME, "MyMusic")


if __name__ == "__main__":
    unittest.main()
