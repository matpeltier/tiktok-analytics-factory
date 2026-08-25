"""Minimal local Streamlit review interface for human QA.

Launch with:
    python -m tiktok_analytics_factory.qa review-app --dataset-root data/dataset

Requires the optional ``streamlit`` dependency; fails loudly if it is missing.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any


def _require_streamlit() -> Any:
    try:
        import streamlit  # type: ignore[import-not-found]
    except ImportError as exc:  # fail loudly, no silent fallback
        raise SystemExit(
            "streamlit is not installed. Install it with:\n"
            "  pip install streamlit\n"
            "then run:\n"
            "  streamlit run -m tiktok_analytics_factory.qa ... or use the "
            "`review-app` CLI subcommand via `python -m streamlit run`."
        ) from exc
    return streamlit


SCORECARD_CATEGORIES = (
    "shot_timeline",
    "ocr_text",
    "dialogue",
    "visual_description",
    "camera_editing",
    "audio",
    "hook",
    "narrative",
    "commercial_reasoning",
    "reconstruction",
)


def build_review_from_form(
    record,
    reviewer: str,
    scores: dict[str, int],
    errors: list[dict[str, Any]],
    notes: str,
):
    from .reviews import Review
    from .taxonomy import ReviewError

    return Review(
        video_id=record.video_id,
        reviewer=reviewer,
        scores=scores,
        errors=[ReviewError.from_dict(e) for e in errors],
        notes=notes,
        source_record_hash=record.record_hash(),
    )


def launch_review_app(dataset_root: Path, reviews_root: Path) -> None:
    st = _require_streamlit()
    import random  # noqa: PLC0415

    from .records import list_video_ids, load_record  # noqa: PLC0415
    from .reviews import Review, list_reviews, load_review  # noqa: PLC0415
    from .validators import run_validators  # noqa: PLC0415

    st.set_page_config(page_title="Dataset QA Review", layout="wide")
    st.title("TikTok dataset QA review")

    video_ids = list_video_ids(dataset_root)
    if not video_ids:
        st.error(f"No records found under {dataset_root}")
        return

    if "index" not in st.session_state:
        st.session_state.index = 0

    nav1, nav2, nav3, nav4 = st.columns([1, 1, 1, 4])
    if nav1.button("◀ prev") and st.session_state.index > 0:
        st.session_state.index -= 1
    if nav2.button("next ▶") and st.session_state.index < len(video_ids) - 1:
        st.session_state.index += 1
    if nav3.button("random"):
        st.session_state.index = random.randrange(len(video_ids))
    nav4.selectbox(
        "record",
        video_ids,
        index=min(st.session_state.index, len(video_ids) - 1),
        key="record_select",
        on_change=lambda: setattr(st.session_state, "index", video_ids.index(st.session_state.record_select)),
    )

    video_id = video_ids[st.session_state.index]
    record = load_record(dataset_root, video_id)
    m = record.manifest

    st.header(video_id)

    left, right = st.columns([1, 2])

    with left:
        mp4_path = m.get("mp4_path")
        if mp4_path and Path(str(mp4_path)).exists():
            st.video(str(mp4_path))
        else:
            st.warning("local MP4 not available for playback")

    with right:
        st.subheader("Source metadata")
        st.json({k: v for k, v in m.items() if k != "observed_metadata"})

        perf = record.performance
        st.subheader("Performance snapshot")
        st.json(perf)

        cost = m.get("cost_usd")
        latency = m.get("latency_s")
        st.caption(f"cost_usd={cost} latency_s={latency}")

    st.subheader("Shot timeline")
    shots = (record.perception or {}).get("shots", [])
    for shot in shots:
        frame = shot.get("representative_frame")
        cols = st.columns([1, 3])
        if frame and Path(str(frame)).exists():
            cols[0].image(str(frame))
        elif frame and (record.root / str(frame)).exists():
            cols[0].image(str(record.root / str(frame)))
        cols[1].markdown(
            f"`{shot.get('shot_id')}` {shot.get('start_s')}s – {shot.get('end_s')}s"
        )

    st.subheader("CreativeIR")
    st.json(record.creative_ir)
    st.subheader("CanonicalIR")
    st.json(record.canonical_ir)

    st.subheader("Provenance / versions")
    st.json(
        {
            k: m.get(k)
            for k in ("pipeline_version", "schema_version", "prompt_version", "model_id")
            if k in m
        }
        | {
            k: (record.creative_ir or {}).get(k)
            for k in ("schema_version", "prompt_version", "model_id")
            if record.creative_ir and record.creative_ir.get(k) is not None
        }
    )

    st.subheader("Automatic validation results")
    issues = run_validators(record)
    if issues:
        for issue in issues:
            st.error(f"[{issue.severity}] {issue.category}: {issue.message}")
    else:
        st.success("all automatic validators passed")

    st.divider()
    st.subheader("Human review")

    existing = list_reviews(reviews_root, video_id)
    if existing:
        st.info(f"{len(existing)} existing review(s)")
        with st.expander("previous reviews"):
            for p in existing:
                st.json(load_review(p))

    reviewer = st.text_input("Reviewer name", value=st.session_state.get("reviewer", ""))
    scores: dict[str, int] = {}
    for cat in SCORECARD_CATEGORIES:
        scores[cat] = st.slider(cat, 1, 5, 3, key=f"score_{cat}")

    n_errors = st.number_input("Number of errors to log", 0, 10, 0)
    errors: list[dict[str, Any]] = []
    from .taxonomy import ERROR_TAXONOMY, SEVERITIES  # noqa: PLC0415

    for i in range(int(n_errors)):
        with st.expander(f"error #{i + 1}"):
            category = st.selectbox("category", sorted(ERROR_TAXONOMY), key=f"err_cat_{i}")
            severity = st.selectbox("severity", sorted(SEVERITIES), key=f"err_sev_{i}")
            note = st.text_input("note", key=f"err_note_{i}")
            shot_id = st.text_input("affected shot id (optional)", key=f"err_shot_{i}")
            field_ref = st.text_input("affected field (optional)", key=f"err_field_{i}")
            errors.append(
                {
                    "category": category,
                    "severity": severity,
                    "note": note,
                    "shot_id": shot_id or None,
                    "field": field_ref or None,
                }
            )

    notes = st.text_area("Notes (required when any score <= 2 or severity is blocking)")

    if st.button("Save review"):
        if not reviewer.strip():
            st.error("Reviewer name is required.")
        else:
            try:
                review = build_review_from_form(record, reviewer.strip(), scores, errors, notes)
                path = review.save(reviews_root)
                st.success(f"Saved review to {path}")
                st.cache_data.clear()
            except ValueError as exc:
                st.error(f"Review rejected: {exc}")


if __name__ == "__main__":
    launch_review_app(Path("data/dataset"), Path("data/reviews"))
