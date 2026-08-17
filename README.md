# stale-guard

**Tell whether your data is fresh — not merely rewritten.**

Most freshness checks ask one question:

```python
age = time.time() - os.path.getmtime(path)   # "3.8 hours fresh" ✅
```

That measures *when the file was last written*. It is routinely used as if it
meant *when the data last changed*. Those are different questions, and the gap
between them is where sources go quietly dead.

---

## Two incidents this was built from

Both are from a production odds-scraping pipeline. In both, every existing
monitor stayed green for days, and **neither produced a single error line.**

### A — the file is written, the data is not

A scraper rewrote `latest.json` on every run. The freshness guard measured
`st_mtime` and reported `🟢 3.8 h fresh`. Measured afterwards across the whole
snapshot archive:

| | |
|---|---|
| snapshot files written | **2 414** |
| **unique contents** | **309** |
| redundant repeats | 2 105 (87.2%) |
| longest byte-identical run | **47 hours** |

For 47 hours the source was frozen and the guard was green. Downstream, a
closing-line-value calculation was comparing a two-day-old relic price against
a closing line and reporting the difference as market movement. It was a
measurement artefact.

The same file also carried its own timestamp *inside* the payload. Measured
live: file written 1.80 h ago, data claiming 2.12 h — a **19.5 minute lag**
between the writer and the data, invisible to every layer above.

### B — started, but never enabled

A systemd timer archived those snapshots every 30 minutes. It had been
`start`ed but never `enable`d, so no symlink existed in `timers.target.wants`.
It ran flawlessly for weeks — and then the machine rebooted.

```
boot -13:  2026-08-01 17:43  →  2026-08-02 05:01   ← machine died here
last archive run:              2026-08-02 02:15    ← inside that boot
boot -12:  2026-08-02 05:04   ← and it never came back
```

The journal's final entry is a clean, successful run. No failure, no error,
nothing to alert on. The archive stopped growing for **15 days** while the
freshness guard stayed green — because the guard watched a file written by a
*different*, still-enabled timer.

`started` ≠ `enabled`. The fault is created at install time and only becomes
visible at the next reboot, weeks later.

---

## What it does

Four independent layers. The product is not any one number — it is the
**divergence between them**.

| layer | what it measures | what it catches |
|---|---|---|
| `exists` | the thing is there at all | a typo'd path, an empty archive |
| `write` | when the bytes were last written (`st_mtime`) | the writer died |
| `content` | when the bytes last actually **changed** | **incident A** |
| `payload` | the timestamp the data claims for itself | writer/data drift |

`content` needs history, so it keeps a small sidecar file per source.

## Install

```bash
pip install stale-guard
```

## Use

```bash
# a file that is rewritten constantly and may still be frozen
stale-guard --name odds --path data/latest.json \
    --max-write-age 6h --max-content-age 6h \
    --payload-json-path timestamp --max-payload-age 6h

# a directory that is supposed to keep gaining members
stale-guard --name archive --newest-in data/snapshots --glob '*.json' \
    --max-write-age 1h
```

```python
from datetime import timedelta
from pathlib import Path
from stale_guard import Source, Status, check

report = check(Source(
    name="odds",
    path=Path("data/latest.json"),
    max_write_age=timedelta(hours=6),
    max_content_age=timedelta(hours=6),
))

if report.status is Status.STALE:
    ...
report.divergence   # content age minus write age — the signal
```

## Exit codes

A single exit code must never mean two things.

| code | meaning | who to fix |
|---|---|---|
| `0` | clean | — |
| `1` | the **watched** system is unhealthy (missing / stale) | the pipeline |
| `2` | the **guard** cannot tell (blind) | the guard |

Two consequences that are deliberate, and not everyone will want them:

**Blind is not green.** On the very first observation there is no history, so
the content age is unknown — the file may have been byte-identical for a week
before you started watching. `stale-guard` reports `BLIND` and exits 2 rather
than reporting OK. An OK there would be a guess wearing the costume of a
measurement.

**Blind is not broken either.** If a payload timestamp cannot be parsed, the
report says exactly that, quoting the exception. It never converts a swallowed
error into a confident claim about the source. Those are two different repair
jobs, and conflating them sends you to the wrong system.

## Replayed against the real incident

The 47-hour freeze above is not a story — the snapshot files still exist. Walk
them back through the guard in order (`examples/replay_freeze.py`) and it fires
at hour 6.3, while the `write` layer keeps saying "0 min ago" for two days:

```
longest byte-identical run: 134 files, 47.5 h
  20260702T131503Z.json -> 20260704T124546Z.json

  hour  status   write        content
------------------------------------------------
   0.0  blind      0 min ago       —      exit=2
   0.3  ok         0 min ago    0.3 h     exit=0
   3.3  ok         0 min ago    3.3 h     exit=0
   6.3  stale      0 min ago    6.3 h     exit=1   <-- fires here
  12.3  stale      0 min ago   12.3 h     exit=1
  47.5  stale      0 min ago   47.5 h     exit=1
```

Run it on your own archive before you trust the guard:

```bash
python examples/replay_freeze.py data/snapshots '2026*.json' 6
```

## The test that matters

Every check here constructs the faulty state and asserts the guard notices —
because an alarm that cannot fire when the fault is present guards nothing.

```python
def test_fresh_mtime_but_frozen_content_is_stale(tmp_path):
    ...
    assert report.layer("write").status is Status.OK      # mtime says fresh
    assert report.layer("content").status is Status.STALE # bytes say dead
    assert report.divergence >= timedelta(hours=46)
```

And a gate test proves that layer is what does the work: with
`max_content_age=None`, the exact same faulty state must go **unnoticed**. If
that ever starts failing, the alarm is coming from somewhere else and the
guard is green for the wrong reason.

Verified by mutation: neutering the content layer makes
`test_fresh_mtime_but_frozen_content_is_stale` fail, and nothing else.

## License

MIT
