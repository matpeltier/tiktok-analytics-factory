from __future__ import annotations

import json
import sys
from pathlib import Path

from tests.fixtures import FakeCollector


def _run_cli(args, cwd):
    return subprocess.run(
        [sys.executable, "-m", "tiktok_analytics_factory.ingestion", *args],
        capture_output=True, text=True, cwd=cwd,
    )


import subprocess


def _last_json(text: str) -> dict:
    return json.loads(text[text.index("{"):].strip())


def test_cli_failure_exit_nonzero(tmp_path):
    res = _run_cli(["ingest", "--url", "not-a-url", "--output-root", "data/raw"], tmp_path)
    assert res.returncode != 0
    payload = _last_json(res.stderr)
    assert payload["category"] == "invalid_url"


def test_cli_success_prints_id_and_dir(tmp_path, monkeypatch):
    from tiktok_analytics_factory.ingestion import collectors as collectors_mod
    from tiktok_analytics_factory.ingestion.__main__ import main

    monkeypatch.setattr(collectors_mod, "DEFAULT_COLLECTOR_ORDER", [FakeCollector])
    rc = main(["ingest", "--url", "https://www.tiktok.com/@x/video/1111222233334444555",
               "--output-root", str(tmp_path / "raw")])
    assert rc == 0
