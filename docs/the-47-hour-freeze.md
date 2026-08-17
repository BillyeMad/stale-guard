# The 47-hour freeze

*My monitor stayed green the whole time. Here is what it was actually measuring.*

I keep a small sports-odds pipeline running at home. It scrapes prices on a
schedule, writes them to `latest.json`, and archives timestamped snapshots so I
can measure closing line value later.

In July I hashed the whole snapshot archive, expecting to find some duplicate
files worth cleaning up. This is what I got:

| | |
|---|---|
| timestamped snapshots written | **2 413** |
| **unique contents** | **308** |
| redundant repeats | 2 105 (87.2%) |

My scraper had run 2413 times and received new data 308 times. Sorted by
timestamp, the repeats cluster into runs:

| repeats | from | to | frozen for |
|---|---|---|---|
| 134× | 2026-07-02 13:15 | 2026-07-04 12:45 | **47.5 hours** |
| 92× | 2026-07-05 13:09 | 2026-07-06 12:56 | 23.8 hours |
| 87× | 2026-07-09 13:15 | 2026-07-10 12:15 | 23.0 hours |
| 91× | 2026-06-30 14:15 | 2026-07-01 12:45 | 22.5 hours |

For 47 hours, the prices I was recording had not moved by a single byte. My
freshness monitor was green throughout. It had been green all along.

## Why this is not a cosmetic problem

I keep the snapshots to compute closing line value — the difference between the
price I took and the price the market closed at. CLV is how I find out whether
I have an edge long before profit and loss can tell me anything: with P&L I
would have needed roughly fifteen thousand bets per arm to reach significance,
and with CLV about a hundred and fifty.

So price freshness is not decoration around my measurement. It **is** my
measuring instrument. A CLV I compute against a two-day-old relic price does
not measure market movement. It measures my own plumbing.

## How it stayed green

One line:

```python
age = time.time() - path.stat().st_mtime
if age <= max_age:
    ok(f"{age:.1f} h fresh")
```

My scraper rewrote `latest.json` on every run, whether or not the upstream
source had changed. So the file was always minutes old. The *data* in it was
two days old. `st_mtime` answers "when was this file last written", and I read
it as "when did the data last change". Those are different questions, and I
never noticed I was asking the wrong one.

## The part I find harder to shrug off

That function was not naive. I had already taught it three lessons the hard
way, and its docstring says so:

- it separates *"the producer is intentionally stopped"* from *"the producer is
  broken"*, because I had once watched two of my own monitors report green and
  red for the same paused timer;
- it carries my explicit warning that a systemd unit's description naming a
  file **is not proof** that this unit writes it — I measured that one the
  expensive way;
- it refuses to let a missing file be swallowed by the "intentionally stopped"
  branch, so a path I typo could never go quiet.

Three edges I had hardened myself. And the measurement in the middle was still
the wrong one. Every time I reviewed that function I asked *am I handling the
edge cases?* I never once asked *am I measuring the thing I think I am?*

There was a smaller version of the same blindness sitting in plain sight. The
payload carries its own timestamp. I measured it live while writing this: the
file had been written 1.80 hours ago, and the data inside it claimed to be 2.12
hours old. A 19.5 minute lag between my writer and my data, on every single
cycle, and I had nothing looking at it.

## Then I did it again, in a worse shape

While fixing this I checked the snapshot archive itself and found it had
stopped **15 days earlier**. No error, no failed unit, nothing in the journal
but a clean successful run and then silence.

I had `start`ed the archiving timer and never `enable`d it. No symlink in
`timers.target.wants`, so it ran perfectly until the machine rebooted:

```
boot -13:  2026-08-01 17:43  →  2026-08-02 05:01   ← machine died here
last archive run:              2026-08-02 02:15    ← inside that boot
boot -12:  2026-08-02 05:04   ← and it never came back
```

`started` ≠ `enabled`. I created that fault at install time and it only became
visible weeks later, at the next reboot — by which point I blamed the reboot,
not the install.

And my monitor was green for those 15 days too, because it was watching
`latest.json`, which a *different*, still-enabled timer writes. Right file,
wrong question. I had nothing measuring whether the directory that was supposed
to keep growing was actually growing.

Those 15 days of price history are simply gone. I cannot recover them.

## What I changed

I pulled the check out into its own thing, [`stale-guard`][repo], with four
independent layers:

| layer | what it measures |
|---|---|
| `exists` | the thing is there at all |
| `write` | when the bytes were last written (`st_mtime`) |
| `content` | when the bytes last actually **changed** (digest + history) |
| `payload` | the timestamp the data claims for itself |

The useful output is not any one of those numbers. It is the **divergence
between them**. Something rewritten every fifteen minutes that has not changed
in 47 hours is dead, and only the second layer can say so.

Two decisions in there I would defend, and that you may well disagree with:

**Blind is not green.** The content layer needs history, so on its very first
observation it does not know how long the file has been identical — it may have
been frozen for a week before I started watching. It reports `BLIND` and exits
non-zero rather than reporting OK. An OK there would be a guess wearing the
costume of a measurement. For the same reason, until it has actually watched
the content change once, it reports the age as a lower bound: *"last changed
**at least** 3.0 h ago"*.

**Blind is not broken either.** If it cannot parse the payload timestamp, the
report says exactly that and quotes the exception. It never turns an error I
swallowed into a confident claim about the source. Those are two different
repair jobs for me, and running them together would send me to fix the wrong
system.

## The only proof I actually trusted

Not that the tests pass. Two things:

**Mutation.** I neutered the content layer, and exactly one test failed — the
one that constructs a fresh-mtime/frozen-content file. Had that test stayed
green, the alarm would have been coming from somewhere else.

**Replay against the real bytes.** The 134 files from that 47-hour run still
exist. I walked them back through the guard in order, as if it were happening
live:

```
longest byte-identical run: 134 files, 47.5 h

  hour  status   write        content
------------------------------------------------
   0.0  blind      0 min ago       —      exit=2
   3.3  ok         0 min ago    3.3 h     exit=0
   6.3  stale      0 min ago    6.3 h     exit=1   <-- fires here
  47.5  stale      0 min ago   47.5 h     exit=1
```

Six hours instead of 47, and the `write` column keeps saying "0 min ago" for
two full days — exactly the green I had been looking at.

## Four things I would tell myself in June

1. **Ask what the metric measures, not what it is named.** My "freshness" was
   measuring write activity. The name was doing the work the code wasn't.
2. **A check that cannot fail while the fault is present guards nothing.** The
   only test I trust now is one that *constructs* the broken state and asserts
   that my guard notices it.
3. **I can harden a check around the wrong number.** Edge cases and a correct
   premise are unrelated properties, and I had been improving only one of them.
4. **`started` ≠ `enabled`.** I verify with `is-enabled` now, not "is it
   running right now" — the difference only surfaces at the next reboot.

I retired the model this pipeline fed anyway, on 227 out-of-sample bets at
p < 0.01. That is a different post, and an easier one to write than this.

---

The code is MIT and lives here: **[stale-guard][repo]**. If you keep timestamped
snapshots of anything, `examples/replay_freeze.py` will walk your own archive
and tell you when a guard would have fired — you do not need the library for
that, and I would genuinely like to know what it finds.

Which brings me to the question I actually have. Every freshness check I have
written or read measures a file timestamp or an HTTP `Last-Modified`. **Do you
check that the content changed, rather than that a write happened?** And if you
do — what do you do about the first observation, when you have no history and
cannot honestly say anything at all?

[repo]: https://github.com/BillyeMad/stale-guard
