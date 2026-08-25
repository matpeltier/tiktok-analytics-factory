"""Generate a SYNTHETIC demo dataset and QA audit report under examples/.

This exists only to exercise the QA tooling end-to-end while the real pilot
collection (#8) is not yet available. Nothing here is real TikTok data.

Usage:
    python examples/qa_demo/generate_demo.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tests"))

from qa_fixtures import build_record, write_cohort_config  # noqa: E402
from tiktok_analytics_factory.qa.audit import run_audit  # noqa: E402


def main() -> None:
    base = Path(__file__).resolve().parent
    dataset = base / "dataset"
    write_cohort_config(dataset)
    # two healthy records, one systematic failure (cohort mismatch)
    build_record(dataset, "7300000000000000001", manifest={"creator": "bakerylab"})
    build_record(
        dataset,
        "7300000000000000002",
        manifest={"creator": "pizzaiolo"},
        performance={
            "snapshots": [
                {"observed_at": "2026-02-01T00:00:00+00:00", "metrics": {"views": 999999}}
            ]
        },
    )
    build_record(
        dataset,
        "7300000000000000003",
        manifest={"cohort_id": "not-approved", "status": "failed"},
    )
    out = run_audit(dataset, base / "qa_report.json")
    print(f"synthetic demo report written to {out}")


if __name__ == "__main__":
    main()
