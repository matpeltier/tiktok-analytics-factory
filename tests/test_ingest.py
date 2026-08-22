from __future__ import annotations

import json

import pytest

import tiktok_analytics_factory.ingestion as ing
from tiktok_analytics_factory.ingestion import ingest
from tiktok_analytics_factory.ingestion.errors import (
    ArtifactMismatchError,
    DownloadError_,
    VideoUnavailableError,
)
from tests.fixtures import FAKE_MP4_A, FAKE_MP4_B, FakeCollector


class StubCollector(FakeCollector):
    pass


def _ingest_with(tmp_path, order, url, **kw):
    # inject our fake order by patching DEFAULT_COLLECTOR_ORDER
    original = ing.collectors.DEFAULT_COLLECTOR_ORDER
    ing.collectors.DEFAULT_COLLECTOR_ORDER = order
    try:
        return ing.ingest(url, str(tmp_path / "raw"), **kw)
    finally:
        ing.collectors.DEFAULT_COLLECTOR_ORDER = original


def test_manifest_and_hash_created(tmp_path):
    res = _ingest_with(tmp_path, [StubCollector], "https://www.tiktok.com/@x/video/7300000000000000001")
    d = res.artifact_dir
    assert (d / "video.mp4").exists()
    manifest = json.loads((d / "manifest.json").read_text())
    assert manifest["video_id"] == "7300000000000000001"
    assert manifest["sha256"] == ing.sha256_of(FAKE_MP4_A)
    assert manifest["byte_size"] == len(FAKE_MP4_A)
    assert manifest["collector_name"] == "fake"
    assert manifest["attempted_collectors_in_order"] == ["fake"]
    assert (d / "metadata.raw.json").exists()
    assert (d / "metadata.normalized.json").exists()


def test_idempotent_same_video_reuses_mp4(tmp_path):
    first = _ingest_with(tmp_path, [StubCollector], "https://www.tiktok.com/@x/video/7300000000000000001")
    mtime = (first.artifact_dir / "video.mp4").stat().st_mtime_ns
    second = _ingest_with(tmp_path, [StubCollector], "https://www.tiktok.com/@x/video/7300000000000000001")
    assert second.reused_existing_mp4 is True
    assert (second.artifact_dir / "video.mp4").stat().st_mtime_ns == mtime


def test_mismatch_refused_no_overwrite(tmp_path):
    class OtherBytes(StubCollector):
        def collect(self, url):
            r = super().collect(url)
            r.mp4_bytes = FAKE_MP4_B
            return r

    _ingest_with(tmp_path, [StubCollector], "https://www.tiktok.com/@x/video/7300000000000000001")
    with pytest.raises(ArtifactMismatchError):
        _ingest_with(tmp_path, [OtherBytes], "https://www.tiktok.com/@x/video/7300000000000000001")
    stored = (tmp_path / "raw" / "7300000000000000001" / "video.mp4").read_bytes()
    assert stored == FAKE_MP4_A


def test_fallback_provenance_recorded(tmp_path):
    class Broken(StubCollector):
        name = "broken"

        def collect(self, url):
            raise DownloadError_("simulated download failure")

    res = _ingest_with(tmp_path, [Broken, StubCollector], "https://www.tiktok.com/@x/video/7300000000000000001")
    manifest = json.loads((res.artifact_dir / "manifest.json").read_text())
    assert manifest["attempted_collectors_in_order"] == ["broken", "fake"]
    assert manifest["collector_name"] == "fake"
    notes = manifest["fallback_or_error_notes"]
    assert notes and notes[0]["collector"] == "broken"
    assert notes[0]["error_category"] == "download_failure"


def test_all_collectors_fail_raises_structured_error(tmp_path):
    class Unavail(StubCollector):
        name = "unavail"

        def collect(self, url):
            raise VideoUnavailableError("video is private")

    with pytest.raises(VideoUnavailableError):
        _ingest_with(tmp_path, [Unavail], "https://www.tiktok.com/@x/video/7300000000000000001")


def test_force_new_observation_versions_metadata(tmp_path):
    _ingest_with(tmp_path, [StubCollector], "https://www.tiktok.com/@x/video/7300000000000000001")
    res = _ingest_with(
        tmp_path,
        [StubCollector],
        "https://www.tiktok.com/@x/video/7300000000000000001",
        force_new_observation=True,
    )
    versioned = list(res.artifact_dir.glob("metadata.normalized.*.json"))
    assert versioned, "expected a timestamped metadata snapshot"


def test_invalid_url_fails_fast(tmp_path):
    from tiktok_analytics_factory.ingestion.errors import InvalidURLError

    with pytest.raises(InvalidURLError):
        _ingest_with(tmp_path, [StubCollector], "not-a-tiktok-url")
