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
    res = _ingest_with(tmp_path, [StubCollector], "https://www.tiktok.com/@x/video/1111222233334444555")
    d = res.artifact_dir
    assert (d / "video.mp4").exists()
    manifest = json.loads((d / "manifest.json").read_text())
    assert manifest["video_id"] == "1111222233334444555"
    assert manifest["sha256"] == ing.sha256_of(FAKE_MP4_A)
    assert manifest["byte_size"] == len(FAKE_MP4_A)
    assert manifest["collector_name"] == "fake"
    assert manifest["attempted_collectors_in_order"] == ["fake"]
    assert (d / "metadata.raw.json").exists()
    assert (d / "metadata.normalized.json").exists()


def test_idempotent_same_video_reuses_mp4(tmp_path):
    first = _ingest_with(tmp_path, [StubCollector], "https://www.tiktok.com/@x/video/1111222233334444555")
    mtime = (first.artifact_dir / "video.mp4").stat().st_mtime_ns
    second = _ingest_with(tmp_path, [StubCollector], "https://www.tiktok.com/@x/video/1111222233334444555")
    assert second.reused_existing_mp4 is True
    assert (second.artifact_dir / "video.mp4").stat().st_mtime_ns == mtime


def test_mismatch_refused_no_overwrite(tmp_path):
    class OtherBytes(StubCollector):
        def collect(self, url):
            r = super().collect(url)
            r.mp4_bytes = FAKE_MP4_B
            return r

    _ingest_with(tmp_path, [StubCollector], "https://www.tiktok.com/@x/video/1111222233334444555")
    with pytest.raises(ArtifactMismatchError):
        _ingest_with(tmp_path, [OtherBytes], "https://www.tiktok.com/@x/video/1111222233334444555")
    stored = (tmp_path / "raw" / "1111222233334444555" / "video.mp4").read_bytes()
    assert stored == FAKE_MP4_A


def test_fallback_provenance_recorded(tmp_path):
    class Broken(StubCollector):
        name = "broken"

        def collect(self, url):
            raise DownloadError_("simulated download failure")

    res = _ingest_with(tmp_path, [Broken, StubCollector], "https://www.tiktok.com/@x/video/1111222233334444555")
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
        _ingest_with(tmp_path, [Unavail], "https://www.tiktok.com/@x/video/1111222233334444555")


def test_force_new_observation_versions_metadata(tmp_path):
    _ingest_with(tmp_path, [StubCollector], "https://www.tiktok.com/@x/video/1111222233334444555")
    res = _ingest_with(
        tmp_path,
        [StubCollector],
        "https://www.tiktok.com/@x/video/1111222233334444555",
        force_new_observation=True,
    )
    versioned = list(res.artifact_dir.glob("metadata.normalized.*.json"))
    assert versioned, "expected a timestamped metadata snapshot"


def test_invalid_url_fails_fast(tmp_path):
    from tiktok_analytics_factory.ingestion.errors import InvalidURLError

    with pytest.raises(InvalidURLError):
        _ingest_with(tmp_path, [StubCollector], "not-a-tiktok-url")


# ---- PM blocker regression tests ----

from tiktok_analytics_factory.ingestion.collectors import CollectionResult
from tiktok_analytics_factory.ingestion.errors import DownloadError_


def _canonical_files(d):
    return ["video.mp4", "metadata.raw.json", "metadata.normalized.json", "manifest.json"]


class NoMediaCollector(FakeCollector):
    """Simulates Pyktok returning metadata without any media bytes."""

    name = "nomedia"

    def collect(self, url):
        result = super().collect(url)
        result.mp4_bytes = None
        return result


def test_missing_media_is_failure_and_triggers_fallback(tmp_path):
    res = _ingest_with(
        tmp_path,
        [NoMediaCollector, StubCollector],
        "https://www.tiktok.com/@x/video/1111222233334444555",
    )
    manifest = json.loads((res.artifact_dir / "manifest.json").read_text())
    assert manifest["collector_name"] == "fake"
    assert manifest["attempted_collectors_in_order"] == ["nomedia", "fake"]
    notes = manifest["fallback_or_error_notes"]
    assert notes and notes[0]["collector"] == "nomedia"
    assert notes[0]["error_category"] == "download_failure"


def test_all_collectors_without_media_fail_no_manifest(tmp_path):
    class NoMedia2(NoMediaCollector):
        name = "nomedia2"

    with pytest.raises(DownloadError_):
        _ingest_with(tmp_path, [NoMediaCollector, NoMedia2], "https://www.tiktok.com/@x/video/1111222233334444555")
    assert not (tmp_path / "raw" / "1111222233334444555").exists()


def test_ordinary_rerun_touches_no_canonical_file(tmp_path):
    first = _ingest_with(tmp_path, [StubCollector], "https://www.tiktok.com/@x/video/1111222233334444555")
    before = {
        name: (
            (first.artifact_dir / name).stat().st_mtime_ns,
            (first.artifact_dir / name).read_bytes(),
        )
        for name in _canonical_files(first.artifact_dir)
    }
    second = _ingest_with(tmp_path, [StubCollector], "https://www.tiktok.com/@x/video/1111222233334444555")
    for name, (mtime, content) in before.items():
        st = (second.artifact_dir / name).stat()
        assert st.st_mtime_ns == mtime, f"{name} was modified"
        assert (second.artifact_dir / name).read_bytes() == content
    # no versioned snapshots without explicit request
    assert not list(second.artifact_dir.glob("metadata.*.*.json"))


def test_force_new_observation_preserves_canonical_provenance(tmp_path):
    first = _ingest_with(tmp_path, [StubCollector], "https://www.tiktok.com/@x/video/1111222233334444555")
    before = {name: (first.artifact_dir / name).stat().st_mtime_ns for name in _canonical_files(first.artifact_dir)}
    second = _ingest_with(
        tmp_path,
        [StubCollector],
        "https://www.tiktok.com/@x/video/1111222233334444555",
        force_new_observation=True,
    )
    assert second.observation_snapshot is not None
    for name, mtime in before.items():
        assert (second.artifact_dir / name).stat().st_mtime_ns == mtime, f"{name} was modified"
    assert list(second.artifact_dir.glob("metadata.raw.*.json"))
    assert list(second.artifact_dir.glob("metadata.normalized.*.json"))


def test_manifest_paths_relative_with_absolute_output_root(tmp_path, monkeypatch):
    from tiktok_analytics_factory.ingestion import collectors as collectors_mod

    monkeypatch.setattr(collectors_mod, "DEFAULT_COLLECTOR_ORDER", [StubCollector])
    abs_root = tmp_path / "absolute" / "raw"
    res = ing.ingest(
        "https://www.tiktok.com/@x/video/1111222233334444555",
        str(abs_root),
    )
    artifacts = json.loads((res.artifact_dir / "manifest.json").read_text())["artifacts"]
    for value in artifacts.values():
        assert not value.startswith("/")
        assert "\\" not in value
        assert value.startswith("1111222233334444555/")


def test_non_mp4_bytes_refused_cleanly(tmp_path):
    class NotMp4(StubCollector):
        def collect(self, url):
            r = super().collect(url)
            r.mp4_bytes = b"not-an-mp4-container-at-all"
            return r

    with pytest.raises(DownloadError_):
        _ingest_with(tmp_path, [NotMp4], "https://www.tiktok.com/@x/video/1111222233334444555")
    assert not (tmp_path / "raw" / "1111222233334444555").exists()


def test_looks_like_mp4_signature():
    from tiktok_analytics_factory.ingestion.ingest import _looks_like_mp4

    assert _looks_like_mp4(FAKE_MP4_A)
    assert not _looks_like_mp4(b"\x00\x00\x00\x18XTypmp42" + b"x" * 20)
    assert not _looks_like_mp4(b"RIFFxxxxWEBPVP8 " + b"x" * 20)
    assert not _looks_like_mp4(b"short")




def test_force_new_observation_writes_versioned_manifest_snapshot(tmp_path):
    first = _ingest_with(tmp_path, [StubCollector], "https://www.tiktok.com/@x/video/1111222233334444555")
    canonical_before = (first.artifact_dir / "manifest.json").read_bytes()
    second = _ingest_with(
        tmp_path,
        [StubCollector],
        "https://www.tiktok.com/@x/video/1111222233334444555",
        force_new_observation=True,
    )
    snapshots = list(second.artifact_dir.glob("manifest.*.json"))
    assert len(snapshots) == 1
    obs = json.loads(snapshots[0].read_text())
    assert obs["video_id"] == first.video_id
    assert obs["observation_of_manifest"] == f"{first.video_id}/manifest.json"
    assert obs["observed_metadata"]["video_id"] == first.video_id
    # canonical manifest untouched
    assert (second.artifact_dir / "manifest.json").read_bytes() == canonical_before


def test_fresh_run_reports_reused_false(tmp_path):
    res = _ingest_with(tmp_path, [StubCollector], "https://www.tiktok.com/@x/video/1111222233334444555")
    assert res.manifest["mp4_reused_from_previous_run"] is False

def test_partial_artifacts_repair_reports_reused_true(tmp_path):
    first = _ingest_with(tmp_path, [StubCollector], "https://www.tiktok.com/@x/video/1111222233334444555")
    (first.artifact_dir / "metadata.raw.json").unlink()
    (first.artifact_dir / "metadata.normalized.json").unlink()
    (first.artifact_dir / "manifest.json").unlink()
    second = _ingest_with(tmp_path, [StubCollector], "https://www.tiktok.com/@x/video/1111222233334444555")
    assert second.reused_existing_mp4 is False
    assert second.manifest["mp4_reused_from_previous_run"] is True
