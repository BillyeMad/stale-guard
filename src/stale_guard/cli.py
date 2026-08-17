"""Command line front end.

    stale-guard --name odds --path data/latest.json \
        --max-write-age 6h --max-content-age 6h \
        --payload-json-path timestamp --max-payload-age 6h

    stale-guard --name archive --newest-in data/snapshots --glob '*.json' \
        --max-write-age 1h

Exit codes follow the contract in `core`: 0 clean, 1 the watched system is
unhealthy, 2 this guard cannot tell. Never collapse 1 and 2 -- a consumer that
only distinguishes "zero vs non-zero" will read a blind guard as a broken
pipeline, and send you to repair the wrong thing.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path

from stale_guard.core import Source, Status, check

_DURATION = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*([smhd])\s*$", re.IGNORECASE)
_UNITS = {"s": "seconds", "m": "minutes", "h": "hours", "d": "days"}


def duration(text: str) -> timedelta:
    match = _DURATION.match(text)
    if not match:
        raise argparse.ArgumentTypeError(
            f"expected a duration like 45m, 6h or 2d -- got {text!r}"
        )
    amount, unit = match.groups()
    return timedelta(**{_UNITS[unit.lower()]: float(amount)})


def json_path_extractor(dotted: str):
    """Pull a timestamp out of nested JSON by dotted path, e.g. meta.updated."""

    def extract(raw: bytes) -> datetime:
        node = json.loads(raw)
        for part in dotted.split("."):
            node = node[part]
        return datetime.fromisoformat(str(node))

    return extract


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="stale-guard",
        description="Tell whether data is fresh, not merely rewritten.",
    )
    p.add_argument("--name", required=True, help="label used in the report")

    where = p.add_mutually_exclusive_group(required=True)
    where.add_argument("--path", type=Path, help="a single file to watch")
    where.add_argument(
        "--newest-in", type=Path,
        help="a directory that is supposed to keep gaining files",
    )
    p.add_argument("--glob", default="*", help="with --newest-in (default: *)")

    p.add_argument("--max-write-age", type=duration,
                   help="how old the last write may be, e.g. 6h")
    p.add_argument("--max-content-age", type=duration,
                   help="how long the bytes may stay unchanged, e.g. 6h")
    p.add_argument("--payload-json-path",
                   help="dotted path to a timestamp inside the JSON payload")
    p.add_argument("--max-payload-age", type=duration,
                   help="how old the data may claim to be")
    p.add_argument("--state-dir", type=Path, default=Path.home() / ".stale-guard",
                   help="where the content history is kept")
    p.add_argument("--json", action="store_true", help="machine readable output")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if args.max_content_age and not (args.path or args.newest_in):
        print("nothing to watch", file=sys.stderr)
        return 2

    try:
        src = Source(
            name=args.name,
            path=args.path,
            newest_in=(args.newest_in, args.glob) if args.newest_in else None,
            max_write_age=args.max_write_age,
            max_content_age=args.max_content_age,
            payload_timestamp=(
                json_path_extractor(args.payload_json_path)
                if args.payload_json_path else None
            ),
            max_payload_age=args.max_payload_age,
            state_dir=args.state_dir,
        )
        report = check(src)
    except Exception as exc:  # the guard itself failed -> 2, loudly
        print(f"stale-guard crashed: {exc}", file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps({
            "name": report.name,
            "status": report.status.value,
            "exit_code": report.exit_code,
            "target": str(report.target) if report.target else None,
            "divergence_hours": (
                report.divergence.total_seconds() / 3600
                if report.divergence is not None else None
            ),
            "layers": [
                {
                    "name": lyr.name,
                    "status": lyr.status.value,
                    "age_hours": (
                        lyr.age.total_seconds() / 3600
                        if lyr.age is not None else None
                    ),
                    "detail": lyr.detail,
                }
                for lyr in report.layers
            ],
        }, indent=2))
    else:
        print(report)
        if report.divergence is not None and report.divergence > timedelta(0):
            hours = report.divergence.total_seconds() / 3600
            print(f"  divergence: content is {hours:.1f} h older than the "
                  f"last write")
        if report.status is Status.BLIND:
            print("  -> this guard cannot tell. Fix the guard, "
                  "not the pipeline.")

    return report.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
