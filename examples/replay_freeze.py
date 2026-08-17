"""Replay a snapshot archive through stale-guard to see when it would fire.

If you keep timestamped snapshots of a source (`20260702T131503Z.json`, ...),
this walks them in order, feeds each one to the guard as if it were happening
live, and prints when the alarm would have gone off.

    python examples/replay_freeze.py data/snapshots '2026*.json'

Useful for answering the only question that matters about a new guard:
would it actually have caught the incident that made you write it?
"""

from __future__ import annotations

import hashlib
import os
import shutil
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

from stale_guard import Source, check


def stamp_of(path: Path) -> datetime:
    """Parse a leading YYYYmmddTHHMMSS out of the file name."""
    return datetime.strptime(path.name[:15], "%Y%m%dT%H%M%S").replace(
        tzinfo=timezone.utc
    )


def longest_identical_run(files: list[Path]) -> tuple[int, int]:
    digests = [hashlib.sha256(p.read_bytes()).hexdigest() for p in files]
    best = (0, 0, 0)
    start = 0
    for i in range(1, len(digests) + 1):
        if i == len(digests) or digests[i] != digests[start]:
            if i - start > best[0]:
                best = (i - start, start, i - 1)
            start = i
    return best[1], best[2]


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(__doc__)
        return 2
    directory, pattern = Path(argv[0]), argv[1]
    limit = timedelta(hours=float(argv[2])) if len(argv) > 2 else timedelta(hours=6)

    files = sorted(p for p in directory.glob(pattern) if p.is_file())
    if not files:
        print(f"no file matches {pattern!r} in {directory}")
        return 2

    first, last = longest_identical_run(files)
    span = stamp_of(files[last]) - stamp_of(files[first])
    print(f"longest byte-identical run: {last - first + 1} files, "
          f"{span.total_seconds() / 3600:.1f} h")
    print(f"  {files[first].name} -> {files[last].name}\n")

    tmp = Path(tempfile.mkdtemp())
    try:
        watched = tmp / "latest.json"
        src = Source(
            name="replay",
            path=watched,
            max_write_age=limit,
            max_content_age=limit,
            state_dir=tmp / "state",
        )
        t0 = stamp_of(files[first])
        fired = False
        print(f"{'hour':>6}  {'status':<8} {'write':<12} content")
        print("-" * 48)
        for path in files[first:last + 1]:
            now = stamp_of(path)
            shutil.copy(path, watched)            # the writer rewrites it
            os.utime(watched, (now.timestamp(), now.timestamp()))
            report = check(src, now=now)
            elapsed = (now - t0).total_seconds() / 3600
            content = report.layer("content").age
            if not fired and report.exit_code == 1:
                fired = True
                print(f"{elapsed:6.1f}  {report.status.value:<8} "
                      f"{report.layer('write').age.total_seconds() / 60:>4.0f} min ago  "
                      f"{content.total_seconds() / 3600:>5.1f} h   <-- fires here")
        if not fired:
            print("never fired -- the source was never frozen past the limit")
    finally:
        shutil.rmtree(tmp)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
