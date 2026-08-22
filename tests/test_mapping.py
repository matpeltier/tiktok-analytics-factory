from __future__ import annotations

from tiktok_analytics_factory.ingestion.mapping import normalize_payload

FIXTURE = {
    "desc": "Making sourdough #baking #bread",
    "author": {"unique_id": "testcreator", "uid": "700123456"},
    "stats": {"play_count": 15234, "digg_count": 812, "comment_count": 43, "share_count": 7},
    "video": {"duration": 21.5},
    "music": {"title": "Loaf Anthem", "author": "DJ Yeast"},
    "create_time": 1700000000,
}


def test_full_mapping():
    meta = normalize_payload(FIXTURE, video_id="1111222233334444555", source_url="https://x", collector_name="fake")
    assert meta.platform == "tiktok"
    assert meta.creator_handle == "testcreator"
    assert meta.creator_id == "700123456"
    assert meta.hashtags == ["baking", "bread"]
    assert meta.published_at == "2023-11-14T22:13:20+00:00"
    assert meta.duration_seconds == 21.5
    assert (meta.views, meta.likes, meta.comments, meta.shares) == (15234, 812, 43, 7)
    assert (meta.music_title, meta.music_author) == ("Loaf Anthem", "DJ Yeast")


def test_unknown_values_stay_none_not_zero():
    payload = {"desc": "no stats here", "author": {"unique_id": "a"}}
    meta = normalize_payload(payload, video_id="1", source_url="u", collector_name="fake")
    for field in ("views", "likes", "comments", "shares", "saves", "creator_id",
                  "published_at", "duration_seconds", "music_title", "music_author"):
        assert getattr(meta, field) is None, field
    d = meta.to_json_dict()
    assert d["views"] is None and d["views"] != 0


def test_saves_only_when_genuinely_available():
    p = dict(FIXTURE)
    p["stats"] = {**FIXTURE["stats"], "collect_count": 99}
    meta = normalize_payload(p, video_id="1", source_url="u", collector_name="fake")
    assert meta.saves == 99


def test_hashtags_from_caption_fallback():
    meta = normalize_payload({"desc": "#fyp hello #test"}, video_id="1", source_url="u", collector_name="fake")
    assert meta.hashtags == ["fyp", "test"]
