"""CLI: python -m tiktok_analytics_factory.ingestion ingest --url ... --output-root data/raw"""

from __future__ import annotations

import argparse
import json
import sys

from .errors import IngestionError


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m tiktok_analytics_factory.ingestion",
        description="Ingest one public TikTok video into immutable raw artifacts.",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    ingest_p = sub.add_parser("ingest", help="Ingest a single TikTok URL.")
    ingest_p.add_argument("--url", required=True, help="Public TikTok video URL.")
    ingest_p.add_argument("--output-root", default="data/raw", help="Artifact output root.")
    ingest_p.add_argument(
        "--force-new-observation",
        action="store_true",
        help="Record a timestamped new metadata snapshot even if artifacts exist.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    from .ingest import ingest

    try:
        result = ingest(
            args.url,
            args.output_root,
            force_new_observation=args.force_new_observation,
        )
    except IngestionError as exc:
        payload = exc.to_dict()
        print(f"error: [{payload['category']}] {payload['message']}", file=sys.stderr)
        print(json.dumps(payload, indent=2), file=sys.stderr)
        return 1
    except Exception as exc:  # unexpected
        print(json.dumps({"category": "unexpected_error", "message": str(exc)}, indent=2), file=sys.stderr)
        return 1

    print(result.video_id)
    print(result.artifact_dir)
    return 0


if __name__ == "__main__":
    sys.exit(main())
