"""Tests for the audit CLI entry point."""

from __future__ import annotations

import json

import pytest

from tiktok_analytics_factory.qa.__main__ import main
from tests.qa_fixtures import build_record, write_cohort_config


@pytest.fixture
def dataset(tmp_path):
    root = tmp_path / "dataset"
    write_cohort_config(root)
    build_record(root, "7300000000000000001")
    return root


def test_audit_cli_writes_report(tmp_path, dataset):
    out = tmp_path / "reports" / "qa_report.json"
    rc = main(
        [
            "audit",
            "--dataset-root",
            str(dataset),
            "--output",
            str(out),
        ]
    )
    assert rc == 0
    report = json.loads(out.read_text())
    assert report["total_records"] == 1
    assert report["validation"]["pass_rate_pct"] == 100.0


def test_audit_cli_fails_loudly_on_missing_root(tmp_path):
    rc = main(
        ["audit", "--dataset-root", str(tmp_path / "nope"), "--output", str(tmp_path / "r.json")]
    )
    assert rc == 2


def test_audit_cli_with_reviews_root(tmp_path, dataset):
    reviews = tmp_path / "reviews"
    rc = main(
        [
            "audit",
            "--dataset-root",
            str(dataset),
            "--output",
            str(tmp_path / "qa_report.json"),
            "--reviews-root",
            str(reviews),
        ]
    )
    assert rc == 0
