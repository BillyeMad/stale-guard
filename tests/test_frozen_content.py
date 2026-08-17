"""The tests that would have caught two real, measured incidents.

Both incidents are from a production odds-scraping pipeline. In both, every
existing monitor stayed green for days. Neither produced a single error line.

Incident A -- "the file is written, the data is not"
    A scraper rewrote `latest.json` on every run. The freshness guard measured
    `st_mtime` and reported "3.8 h fresh". Measured afterwards over 2414
    snapshot files: only 309 had unique content (87.2% repeats), and the
    longest byte-identical run spanned **47 hours**. The guard was green
    throughout.

Incident B -- "started, but never enabled"
    A systemd timer archived those snapshots. It was `start`ed but never
    `enable`d, so no symlink existed. It ran flawlessly until the machine
    rebooted, then never came back. The journal's last entry is a clean,
    successful run. The archive directory stopped growing for 15 days while
    the freshness guard stayed green -- because the guard watched a file
    written by a *different*, still-enabled timer.

The rule these tests encode: an alarm that cannot fire when the fault is
present guards nothing. So each test *constructs the faulty state* and asserts
that the guard notices.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone

from stale_guard import Source, Status, check

T0 = datetime(2026, 7, 2, 13, 15, tzinfo=timezone.utc)
HOUR = timedelta(hours=1)


def _write(path, payload: dict, *, mtime: datetime) -> None:
    """Write `payload` and set the file's mtime -- simulating a rewrite."""
    path.write_text(json.dumps(payload), encoding="utf-8")
    stamp = mtime.timestamp()
    os.utime(path, (stamp, stamp))


def _source(tmp_path, **kw) -> Source:
    defaults = dict(
        name="odds-snapshot",
        path=tmp_path / "latest.json",
        max_write_age=6 * HOUR,
        max_content_age=6 * HOUR,
        state_dir=tmp_path / ".stale-guard",
    )
    defaults.update(kw)
    return Source(**defaults)


# --- Incident A -----------------------------------------------------------

def test_fresh_mtime_but_frozen_content_is_stale(tmp_path):
    """THE test. Rewritten constantly, unchanged for 47 hours."""
    src = _source(tmp_path)
    frozen = {"timestamp": "2026-07-02T13:15:00+00:00", "odds": [1.85, 2.10]}

    # First observation: the guard has no history yet and says so.
    _write(src.path, frozen, mtime=T0)
    check(src, now=T0)

    # 47 hours later. The scraper has rewritten the file every 15 minutes --
    # so the mtime is minutes old -- but the bytes never changed.
    later = T0 + 47 * HOUR
    _write(src.path, frozen, mtime=later - timedelta(minutes=6))
    report = check(src, now=later)

    assert report.status is Status.STALE, report
    assert report.exit_code == 1

    write, content = report.layer("write"), report.layer("content")
    assert write.status is Status.OK, "the mtime layer alone still says fresh"
    assert write.age < HOUR
    assert content.status is Status.STALE
    assert content.age >= 47 * HOUR

    # The divergence between the two layers is the actual signal.
    assert report.divergence is not None
    assert report.divergence >= 46 * HOUR


def test_removing_the_content_layer_makes_the_alarm_silent(tmp_path):
    """Gate test: prove the content layer is what does the work.

    With the layer switched off, the exact same faulty state must go
    unnoticed. If this ever fails, the alarm above is being raised by
    something else, and the guard would be green for the wrong reason.
    """
    src = _source(tmp_path, max_content_age=None)
    frozen = {"odds": [1.85]}

    _write(src.path, frozen, mtime=T0)
    check(src, now=T0)

    later = T0 + 47 * HOUR
    _write(src.path, frozen, mtime=later - timedelta(minutes=6))
    report = check(src, now=later)

    assert report.status is Status.OK, "without the content layer: silent"
    assert report.exit_code == 0


def test_changing_content_clears_the_alarm(tmp_path):
    src = _source(tmp_path)
    _write(src.path, {"odds": [1.85]}, mtime=T0)
    check(src, now=T0)

    later = T0 + 47 * HOUR
    _write(src.path, {"odds": [1.90]}, mtime=later)
    report = check(src, now=later)

    assert report.status is Status.OK
    assert report.layer("content").age == timedelta(0)


# --- blind is not green ---------------------------------------------------

def test_first_observation_is_blind_not_ok(tmp_path):
    """No history means we cannot know how long the content has been frozen.

    Reporting OK here would be a guess dressed as a measurement. The file may
    have been identical for a week before we first looked at it.
    """
    src = _source(tmp_path)
    _write(src.path, {"odds": [1.85]}, mtime=T0)

    report = check(src, now=T0)

    assert report.status is Status.BLIND
    assert report.exit_code == 2, "2 = the guard cannot tell, fix the guard"
    assert "baseline" in report.layer("content").detail.lower()


def test_unreadable_payload_timestamp_is_blind_not_stale(tmp_path):
    """A swallowed exception must never become a confident diagnosis.

    Saying "the source is frozen" when the truth is "I could not parse the
    timestamp" sends the operator to repair the wrong system.
    """

    def extractor(raw: bytes) -> datetime:
        raise ValueError("no 'timestamp' key")

    src = _source(tmp_path, payload_timestamp=extractor, max_payload_age=6 * HOUR)
    _write(src.path, {"odds": [1.85]}, mtime=T0)
    check(src, now=T0)

    later = T0 + HOUR
    _write(src.path, {"odds": [1.90]}, mtime=later)
    report = check(src, now=later)

    payload = report.layer("payload")
    assert payload.status is Status.BLIND
    assert "no 'timestamp' key" in payload.detail
    assert "frozen" not in payload.detail.lower()
    assert report.exit_code == 2


def test_missing_file_is_never_swallowed(tmp_path):
    src = _source(tmp_path)
    report = check(src, now=T0)

    assert report.status is Status.MISSING
    assert report.exit_code == 1
    assert str(src.path) in report.layer("exists").detail


# --- Incident B -----------------------------------------------------------

def test_directory_that_should_grow_but_stopped(tmp_path):
    """The archive kept its files; it just stopped gaining new ones."""
    archive = tmp_path / "archive"
    archive.mkdir()
    src = Source(
        name="odds-archive",
        newest_in=(archive, "*.json"),
        max_write_age=6 * HOUR,
        state_dir=tmp_path / ".stale-guard",
    )

    _write(archive / "20260802T001554Z.json", {"odds": [1.85]}, mtime=T0)
    assert check(src, now=T0 + HOUR).status is Status.OK

    # 15 days later: the newest member of the directory is still that file.
    report = check(src, now=T0 + timedelta(days=15))

    assert report.status is Status.STALE
    assert report.exit_code == 1
    assert report.layer("write").age >= timedelta(days=14)


def test_empty_directory_is_missing_not_ok(tmp_path):
    archive = tmp_path / "archive"
    archive.mkdir()
    src = Source(
        name="odds-archive",
        newest_in=(archive, "*.json"),
        max_write_age=6 * HOUR,
        state_dir=tmp_path / ".stale-guard",
    )

    report = check(src, now=T0)

    assert report.status is Status.MISSING
    assert report.exit_code == 1


def test_payload_lag_is_reported_even_when_everything_is_fresh(tmp_path):
    """Measured live: mtime 1.80 h old, payload timestamp 2.12 h old.

    Both inside the threshold, so nothing is wrong -- but the 19.5 minute lag
    is the early warning that the writer and the data have drifted apart.
    """

    def extractor(raw: bytes) -> datetime:
        return datetime.fromisoformat(json.loads(raw)["timestamp"])

    src = _source(tmp_path, payload_timestamp=extractor, max_payload_age=6 * HOUR)

    inner = T0 - timedelta(minutes=19, seconds=30)
    _write(src.path, {"timestamp": inner.isoformat(), "odds": [1.85]}, mtime=T0)
    check(src, now=T0)

    later = T0 + HOUR
    inner2 = later - timedelta(minutes=19, seconds=30)
    _write(src.path, {"timestamp": inner2.isoformat(), "odds": [1.90]}, mtime=later)
    report = check(src, now=later)

    assert report.status is Status.OK
    lag = report.layer("payload").age - report.layer("write").age
    assert timedelta(minutes=19) <= lag <= timedelta(minutes=20)
