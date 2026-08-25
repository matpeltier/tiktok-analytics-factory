"""CLI for the QA layer.

Usage:
    python -m tiktok_analytics_factory.qa audit \
        --dataset-root data/dataset \
        --output data/reports/qa_report.json \
        [--reviews-root data/reviews]

    python -m tiktok_analytics_factory.qa review-app --dataset-root data/dataset
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


def _cmd_audit(args: argparse.Namespace) -> int:
    from .audit import run_audit

    dataset_root = Path(args.dataset_root)
    if not dataset_root.is_dir():
        print(f"error: dataset root does not exist: {dataset_root}", file=sys.stderr)
        return 2
    reviews_root = Path(args.reviews_root) if args.reviews_root else None
    out = run_audit(dataset_root, Path(args.output), reviews_root)
    print(f"audit report written to {out}")
    return 0


def _cmd_review_app(args: argparse.Namespace) -> int:
    from .app import launch_review_app

    launch_review_app(Path(args.dataset_root), Path(args.reviews_root))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m tiktok_analytics_factory.qa")
    sub = parser.add_subparsers(dest="command", required=True)

    audit = sub.add_parser("audit", help="run the dataset-level audit and write a JSON report")
    audit.add_argument("--dataset-root", required=True)
    audit.add_argument("--output", required=True)
    audit.add_argument("--reviews-root", default=None)
    audit.set_defaults(func=_cmd_audit)

    app = sub.add_parser("review-app", help="launch the local Streamlit human review interface")
    app.add_argument("--dataset-root", required=True)
    app.add_argument("--reviews-root", default="data/reviews")
    app.set_defaults(func=_cmd_review_app)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
