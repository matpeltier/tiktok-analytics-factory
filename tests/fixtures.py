"""Shared test fixtures: tiny synthetic MP4 payloads and fake collectors."""

from __future__ import annotations

import pytest

from tiktok_analytics_factory.ingestion.collectors import CollectionResult
from tiktok_analytics_factory.ingestion.errors import DownloadError_, VideoUnavailableError
from tiktok_analytics_factory import ingestion as ing

FAKE_MP4_A = b"\x00\x00\x00\x18ftypmp42fake-tiktok-video-payload-A" * 4
FAKE_MP4_B = b"\x00\x00\x00\x18ftypmp42fake-tiktok-video-payload-B" * 4

FIXTURE_PAYLOAD = {
    "desc": "Making sourdough #baking #bread",
    "author": {"unique_id": "bakerylab", "uid": "700123456"},
    "stats": {"play_count": 15234, "digg_count": 812, "comment_count": 43, "share_count": 7},
    "video": {"duration": 21.5, "id": "7300000000000000001"},
    "music": {"title": "Loaf Anthem", "author": "DJ Yeast"},
    "create_time": 1700000000,
}

URL = "https://www.tiktok.com/@bakerylab/video/7300000000000000001"


FAKE_MP4 = FAKE_MP4_A


class FakeCollector:
    name = "fake"

    def __init__(self, *, mp4=FAKE_MP4, payload=None, fail_with=None):
        self.mp4 = mp4
        self.payload = payload or FIXTURE_PAYLOAD
        self.fail_with = fail_with
        self.version = "0.0-test"

    def collect(self, url):
        from tiktok_analytics_factory.ingestion.urls import extract_video_id

        if self.fail_with is not None:
            raise self.fail_with
        vid = extract_video_id(url)
        return CollectionResult(
            collector_name=self.name,
            video_id=vid,
            source_url=f"https://www.tiktok.com/@x/video/{vid}",
            collected_at="2026-01-01T00:00:00+00:00",
            raw_payload=self.payload,
            mp4_bytes=self.mp4,
            creator_handle_hint="bakerylab",
        )


@pytest.fixture
def fake_ok_collector():
    return lambda **kw: FakeCollector(**kw)


@pytest.fixture(autouse=True)
def _no_live_network(monkeypatch):
    """Unit tests must never hit live TikTok."""
    real = ing.collect_with_fallback

    def guarded(url, order=None):
        for cls in order or []:
            if getattr(cls, "__name__", "").startswith(("Pyktok", "YtDlp")):
                raise AssertionError("Live collector attempted during unit tests")
        return real(url, order)

    monkeypatch.setattr(ing, "collect_with_fallback", guarded)


class UnavailableCollector(FakeCollector):
    pass
