"""CLI: python -m tiktok_analytics_factory.pipeline run-pilot --cohort ... --sources ... --output-root ..."""

from __future__ import annotations

import argparse
import json
import logging
import sys


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m tiktok_analytics_factory.pipeline",
        description="Run the 20-50 video micro-niche pilot batch.",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("run-pilot", help="Run the batch pilot.")
    p.add_argument("--cohort", required=True, help="Path to config/pilot_cohort.json.")
    p.add_argument("--sources", required=True, help="Explicit source list (.csv or .jsonl).")
    p.add_argument("--output-root", default="data/dataset", help="Dataset output root.")
    p.add_argument("--no-resume", action="store_true", help="Reprocess already-successful records.")
    p.add_argument(
        "--retry-attempts", type=int, default=3,
        help="Bounded retry attempts for transient errors (default 3).",
    )
    p.add_argument(
        "--reviews",
        default=None,
        help="Optional JSONL of manual review scores to apply before the gate.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    args = build_parser().parse_args(argv)

    from .runner import PilotOptions, run_pilot
    from .retry import RetryPolicy

    summary = run_pilot(
        args.cohort,
        args.sources,
        args.output_root,
        options=PilotOptions(
            resume=not args.no_resume,
            reprocess=args.no_resume,
            retry_policy=RetryPolicy(max_attempts=args.retry_attempts),
        ),
        reviews_path=args.reviews,
    )
    print(json.dumps(summary.to_dict(), indent=2, sort_keys=True))
    print(f"DECISION: {summary.decision}")
    for b in summary.blockers:
        print(f"  blocker: {b}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
