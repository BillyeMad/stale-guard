"""Four independent answers to "is this data actually fresh?".

Most freshness checks ask one question -- when was the file last written? --
and treat the answer as if it meant "when did the data last change". Those are
different questions, and the gap between them is where sources go quietly dead.

    exists   the thing is there at all
    write    when the bytes were last written        (st_mtime)
    content  when the bytes last actually CHANGED    (digest + history)
    payload  what timestamp the data claims for itself

The product of this module is not any one of those numbers. It is the
DIVERGENCE between them. A source that is written every 15 minutes and has not
changed in 47 hours is dead, and only the second layer can say so.

Exit-code contract (0/1/2), because a single code must never mean two things:

    0  clean
    1  the WATCHED system is unhealthy  (missing / stale)  -> fix the pipeline
    2  the GUARD cannot tell            (blind)            -> fix the guard

"Blind" is deliberately not green and deliberately not the same as "broken".
They are different repair jobs, and a guard that conflates them sends the
operator to the wrong system.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from pathlib import Path


class Status(str, Enum):
    OK = "ok"
    STALE = "stale"
    MISSING = "missing"
    BLIND = "blind"


# Worst-first. MISSING and STALE outrank BLIND: if we can already prove the
# watched system is unhealthy, that is the more actionable fact.
_SEVERITY = {Status.MISSING: 3, Status.STALE: 2, Status.BLIND: 1, Status.OK: 0}
_EXIT = {Status.OK: 0, Status.STALE: 1, Status.MISSING: 1, Status.BLIND: 2}


@dataclass(frozen=True)
class LayerResult:
    name: str
    status: Status
    age: timedelta | None
    detail: str
    provisional: bool = False
    """True when `age` is a LOWER BOUND, not a measurement.

    Until we have watched the content actually change once, all we know is
    how long it has been identical *since we started looking*. If the guard
    was deployed in the middle of a freeze, the real age is larger. Saying
    "3 h" there would overstate what we measured, so the report says
    "at least 3 h" and keeps saying it until a change is observed.
    """


@dataclass(frozen=True)
class Report:
    name: str
    status: Status
    layers: tuple[LayerResult, ...]
    target: Path | None

    def layer(self, name: str) -> LayerResult:
        for layer in self.layers:
            if layer.name == name:
                return layer
        raise KeyError(f"no such layer: {name!r}")

    def has(self, name: str) -> bool:
        return any(layer.name == name for layer in self.layers)

    @property
    def exit_code(self) -> int:
        return _EXIT[self.status]

    @property
    def divergence(self) -> timedelta | None:
        """How far the content age exceeds the write age.

        This is the number that would have caught incident A. Large positive
        divergence means: something keeps writing, nothing keeps changing.
        """
        if not (self.has("content") and self.has("write")):
            return None
        content, write = self.layer("content").age, self.layer("write").age
        if content is None or write is None:
            return None
        return content - write

    def __str__(self) -> str:
        head = f"{self.name}: {self.status.value.upper()}"
        body = "\n".join(
            f"  {lyr.name:<8} {lyr.status.value:<8} {lyr.detail}"
            for lyr in self.layers
        )
        return f"{head}\n{body}"


@dataclass(frozen=True)
class Source:
    """What to watch, and what counts as too old.

    Set `path` for a single file, or `newest_in=(directory, glob)` for a
    directory that is supposed to keep gaining members -- an archive, a
    snapshot store, an inbox. A directory that stops growing looks identical
    to a healthy one unless something measures its newest member.

    Any `max_*` left as None switches that layer off entirely.
    """

    name: str
    path: Path | None = None
    newest_in: tuple[Path, str] | None = None
    members: str = "files"
    """What counts as a member of `newest_in`: "files", "dirs" or "any".

    A backup directory gains *directories*, not files -- one per snapshot. With
    the default "files" such a directory looks empty and the guard reports
    MISSING, which is a true statement about files and a false one about the
    backup. Say what you are watching.
    """
    max_write_age: timedelta | None = None
    max_content_age: timedelta | None = None
    payload_timestamp: Callable[[bytes], datetime] | None = None
    max_payload_age: timedelta | None = None
    state_dir: Path = field(default_factory=lambda: Path(".stale-guard"))

    def __post_init__(self) -> None:
        if (self.path is None) == (self.newest_in is None):
            raise ValueError("give exactly one of `path` or `newest_in`")
        if self.members not in ("files", "dirs", "any"):
            raise ValueError('members must be "files", "dirs" or "any"')
        if self.payload_timestamp is not None and self.max_payload_age is None:
            raise ValueError("payload_timestamp needs max_payload_age")

    @property
    def slug(self) -> str:
        raw = f"{self.name}|{self.path}|{self.newest_in}".encode()
        return f"{_safe(self.name)}-{hashlib.sha256(raw).hexdigest()[:8]}"


def _safe(text: str) -> str:
    return "".join(c if c.isalnum() or c in "-_" else "-" for c in text)[:40]


def _resolve(src: Source) -> tuple[Path | None, str]:
    """Find the file to inspect, and say why if there is none."""
    if src.path is not None:
        if not src.path.exists():
            return None, f"the file does not exist: {src.path}"
        return src.path, ""

    directory, pattern = src.newest_in  # type: ignore[misc]
    if not directory.exists():
        return None, f"the directory does not exist: {directory}"
    keep = {"files": lambda p: p.is_file(),
            "dirs": lambda p: p.is_dir(),
            "any": lambda p: True}[src.members]
    members = [p for p in directory.glob(pattern) if keep(p)]
    if not members:
        return None, (
            f"no file matches {pattern!r} in {directory} -- "
            "the source has produced nothing at all"
        )
    return max(members, key=lambda p: p.stat().st_mtime), ""


def _human(delta: timedelta) -> str:
    hours = delta.total_seconds() / 3600
    if hours < 1:
        return f"{delta.total_seconds() / 60:.0f} min"
    if hours < 48:
        return f"{hours:.1f} h"
    return f"{hours / 24:.1f} days"


def _age_layer(
    name: str, age: timedelta, limit: timedelta | None, note: str,
    provisional: bool = False,
) -> LayerResult:
    at_least = "at least " if provisional else ""
    if limit is not None and age > limit:
        return LayerResult(
            name, Status.STALE, age,
            f"{note} {at_least}{_human(age)} ago (limit {_human(limit)})",
            provisional,
        )
    return LayerResult(
        name, Status.OK, age, f"{note} {at_least}{_human(age)} ago", provisional
    )


def _content_layer(src: Source, target: Path, now: datetime) -> LayerResult:
    """When did the bytes last actually change?

    Needs history, so it keeps a tiny sidecar file. On the very first look
    there is no history -- and we refuse to guess. The file may have been
    byte-identical for a week before we started watching, so reporting OK here
    would be a guess wearing the costume of a measurement.
    """
    digest = hashlib.sha256(target.read_bytes()).hexdigest()
    store = src.state_dir / f"{src.slug}.json"

    previous: dict | None = None
    if store.exists():
        try:
            previous = json.loads(store.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            previous = None
            note = f"unreadable state file ({exc}); baseline re-recorded"
        else:
            note = ""
    else:
        note = ""

    if previous is not None and previous.get("digest") == digest:
        first_seen = datetime.fromisoformat(previous["first_seen"])
        age = now - first_seen
        # `confirmed` means: we have seen this content REPLACE something else,
        # so `first_seen` is the real moment it appeared. Without that, the
        # age is only a lower bound -- we may have started watching mid-freeze.
        return _age_layer(
            "content", age, src.max_content_age, "last changed",
            provisional=not previous.get("confirmed", False),
        )

    store.parent.mkdir(parents=True, exist_ok=True)
    store.write_text(
        json.dumps({
            "digest": digest,
            "first_seen": now.isoformat(),
            "confirmed": previous is not None,
        }),
        encoding="utf-8",
    )

    if previous is None:
        return LayerResult(
            "content", Status.BLIND, None,
            note or "no prior observation -- baseline recorded, "
                    "the content age is unknown until the next check",
        )
    return LayerResult("content", Status.OK, timedelta(0), "changed just now")


def _payload_layer(src: Source, target: Path, now: datetime) -> LayerResult:
    """What timestamp does the data claim for itself?

    If the extractor fails we say we are blind, and we say why, verbatim. We
    never turn a swallowed exception into a confident diagnosis about the
    source -- that sends the operator to repair the wrong system.
    """
    assert src.payload_timestamp is not None
    try:
        stamp = src.payload_timestamp(target.read_bytes())
    except Exception as exc:  # noqa: BLE001 -- the reason is the payload
        return LayerResult(
            "payload", Status.BLIND, None,
            f"could not read the timestamp inside the data: {exc}",
        )
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=timezone.utc)
    return _age_layer(
        "payload", now - stamp, src.max_payload_age, "data claims"
    )


def check(src: Source, now: datetime | None = None) -> Report:
    """Run every configured layer and combine them worst-first."""
    now = now or datetime.now(timezone.utc)
    target, why = _resolve(src)

    if target is None:
        return Report(
            src.name, Status.MISSING,
            (LayerResult("exists", Status.MISSING, None, why),), None,
        )

    layers = [LayerResult("exists", Status.OK, None, str(target))]

    mtime = datetime.fromtimestamp(target.stat().st_mtime, timezone.utc)
    layers.append(
        _age_layer("write", now - mtime, src.max_write_age, "written")
    )
    if src.max_content_age is not None:
        layers.append(_content_layer(src, target, now))
    if src.payload_timestamp is not None:
        layers.append(_payload_layer(src, target, now))

    worst = max(layers, key=lambda lyr: _SEVERITY[lyr.status]).status
    return Report(src.name, worst, tuple(layers), target)
