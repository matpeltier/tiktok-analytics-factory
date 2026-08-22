"""Optional live integration test. Run manually: pytest -m integration.

Skipped by default; requires network access to TikTok and the ingestion extra.
"""

import os

import pytest

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not os.environ.get("TIKTOK_TEST_URL"),
        reason="Set TIKTOK_TEST_URL to a public TikTok video URL to run the live check.",
    ),
]


def test_live_single_video_ingestion(tmp_path):
    from tiktok_analytics_factory.ingestion import ingest

    result = ingest(os.environ["TIKTOK_TEST_URL"], tmp_path / "raw")
    assert (result.artifact_dir / "video.mp4").stat().st_size > 0
    assert result.manifest["sha256"]
    assert result.metadata.video_id == result.video_id
