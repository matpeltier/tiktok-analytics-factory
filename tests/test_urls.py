from __future__ import annotations

import pytest

from tiktok_analytics_factory.ingestion.urls import canonical_url, extract_video_id
from tiktok_analytics_factory.ingestion.errors import InvalidURLError


def test_extracts_id_from_canonical_url():
    assert extract_video_id("https://www.tiktok.com/@user/video/1111222233334444555") == "1111222233334444555"


def test_accepts_raw_numeric_id():
    assert extract_video_id("1111222233334444555") == "1111222233334444555"


def test_short_link_yields_token_not_crash():
    token = extract_video_id("https://vm.tiktok.com/ZMabcdef/")
    assert token == "ZMabcdef"


@pytest.mark.parametrize(
    "bad",
    ["", "   ", "https://youtube.com/watch?v=x", "not a url at all"],
)
def test_invalid_urls_raise(bad):
    with pytest.raises(InvalidURLError):
        extract_video_id(bad)


def test_canonical_url_roundtrip():
    assert canonical_url("1111222233334444555").endswith("/video/1111222233334444555")
