"""CLI: run the two-pass decompiler on a reference video.

Usage:
    python -m tiktok_analytics_factory.multistep --video-id 6718335390845095173 \
        [--video PATH] [--metadata PATH] [--config PATH]

Reads GEMINI_API_KEY / MULTISTEP_* from the environment; never notebooks.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .artifacts import MultiStepArtifacts
from .config import load_multistep_config
from .evaluation import build_comparison, evaluate_decision, load_evaluation
from .runner import MultiStepRunError, run_multistep


def _default_paths(video_id: str) -> tuple[Path, Path]:
    raw_dir = Path("data/raw") / video_id
    return raw_dir / "video.mp4", raw_dir / "metadata.raw.json"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="multistep")
    parser.add_argument("--video-id", required=True)
    parser.add_argument("--video", type=Path, default=None)
    parser.add_argument("--metadata", type=Path, default=None)
    parser.add_argument("--config", type=Path, default=None)
    parser.add_argument("--run-id", default=None)
    parser.add_argument(
        "--baseline-evaluation",
        type=Path,
        default=Path("examples/evaluation/single_pass_baseline_run_evaluation_v0_1.json"),
    )
    args = parser.parse_args(argv)

    video_path, metadata_path = _default_paths(args.video_id)
    video_path = args.video or video_path
    metadata_path = args.metadata or metadata_path

    config = load_multistep_config(args.config)
    raw_metadata = json.loads(metadata_path.read_text())
    source_metadata = {"video_id": args.video_id, "raw": raw_metadata}

    result = run_multistep(
        config,
        video_path,
        args.video_id,
        source_metadata,
        run_id=args.run_id,
    )

    artifacts = MultiStepArtifacts(Path(result["directory"]))
    baseline_eval = load_evaluation(args.baseline_evaluation)
    multistep_eval = json.loads((Path(result["directory"]) / "evaluation.json").read_text())
    comparison = build_comparison(baseline_eval, multistep_eval)
    comparison["canonical_projection_pass"] = True
    decision = evaluate_decision(comparison)
    comparison["decision"] = decision["decision"]
    comparison["gate_results"] = decision["gate_results"]
    if decision["follow_up"]:
        comparison["follow_up"] = decision["follow_up"]
    artifacts.write_comparison(comparison)

    print(json.dumps({
        "run_id": result["run_id"],
        "directory": result["directory"],
        "decision": decision["decision"],
    }, indent=2))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (MultiStepRunError, Exception) as exc:
        print(f"multistep run failed: {exc}", file=sys.stderr)
        sys.exit(1)
