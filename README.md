# market-breadth-data

Daily breadth figures for the whole S&P 500, published as one small JSON file.

**[`breadth.json`](breadth.json)** — raw URL:
`https://raw.githubusercontent.com/nottsaifuture/market-breadth-data/main/breadth.json`

## Why this exists

A market-breadth dashboard measured breadth on 30 mega-caps. Those 30 are also
most of what moves the index, so when they hold up the table reports healthy
breadth *by construction* — it is checking the index against itself.

On **30 September 2026** the gap was 44 points:

| measured on | above their 50-day line | |
|---|---|---|
| 30 mega-caps | 19 of 30 | **65%** — looks green |
| whole S&P 500 | 108 of 498 | **22%** — four out of five stocks below |

The Nasdaq-100 was within 1% of a 52-week high that week. It then fell about
9% from its 6 October peak. The 30-name table never saw it coming, because the
30 names *were* the thing holding the index up.

This repository computes the broad figure so a dashboard can read it with a
single request.

## What is in `breadth.json`

```jsonc
{
  "generated": "2026-11-05T21:20:11Z",
  "universe": 493,
  "rules": { "nearHigh": 3.0, "t50": 30.0, "t200": 65.0, "window": 120 },
  "latest":  { ... },          // the newest row, repeated for convenience
  "history": [ { ... } ]       // the last 300 sessions, oldest first
}
```

Each row:

| field | meaning |
|---|---|
| `date` | the session, `YYYY-MM-DD` |
| `pct50` / `pct200` | % of the universe above their 50- / 200-day average |
| `narrow50` | % of the 30 mega-caps above their 50-day average |
| `gap` | `narrow50 − pct50`: how much healthier the narrow table looks |
| `above50`, `counted50` | the raw counts behind `pct50` |
| `ndxDist`, `spxDist` | % below the index's own 252-session closing high |
| `lit` | 0, 1 or 2 divergence conditions met |
| `state` | `CLEAR`, `AMBER` (one condition) or `WATCH` (both) |
| `day`, `watchFrom` | position in the 120-session watch window |

### The divergence watch

Both conditions are measured **only while the index is within 3% of its
52-week high**, because that is the whole point — the index at a high while
the average stock is not:

1. fewer than **65%** of the universe above their 200-day average
2. fewer than **30%** of the universe above their 50-day average

One condition is `AMBER`, both open a `WATCH` that runs 120 sessions. Further
red days inside the window do not restart the clock.

**This is not a trading signal, and the numbers say so.** Measured on the whole
S&P 500 back to 1993, this configuration was followed by a 5% fall within six
months on **29%** of occasions, against a **48%** base rate for a random day.
Weak breadth has predicted falls when the index was *already* falling — not at
highs. It is published to show how narrow the market is, nothing more.

## How it runs

GitHub Actions, twice each weekday. GitHub's cron is UTC-only while the US
close moves with the clock change, so no single time works all year:

| | US close | useful slot |
|---|---|---|
| winter (GMT) | 21:00 UTC | `21:20 UTC` |
| summer (BST) | 20:00 UTC | `20:20 UTC` |

Both run every day. The off-season one is harmless: the builder drops any
session still in progress and simply republishes the last completed one.

Scheduled runs are commonly 5–20 minutes late and are occasionally skipped at
busy times, so consumers should read `latest.date` rather than assuming the
file is current.

### Before anything is published

1. `build_breadth.py --cache tests/fixture_cache.json --check tests/fixture_rows.json`
   recomputes a fixture of 300 real sessions offline and requires an **exact**
   match against the reference implementation. The reference is the Apps Script
   version that consumes this feed, so the two can never drift apart silently.
2. `check_output.py` refuses to publish a file with an out-of-range percentage,
   a date in the future, a shrunken universe, duplicate or unordered dates, or
   a day-to-day jump of more than 35 points.

A failing check stops the run; the previous `breadth.json` stays in place.

### Stateless on purpose

Two years of prices are downloaded fresh every run and everything is
recomputed. There is no cache to corrupt, so a bad run is fixed by the next one
rather than by a human.

## Running it yourself

```bash
pip install -r requirements.txt
python3 build_breadth.py                 # writes breadth.json
python3 check_output.py breadth.json
```

Offline, against the fixture:

```bash
python3 build_breadth.py --cache tests/fixture_cache.json \
                         --check tests/fixture_rows.json --out /tmp/out.json
```

## Universe

`universe.txt` — the S&P 500 as listed on 5 November 2026 (493 usable tickers).
`universe_30.txt` — the 30 mega-caps, a strict subset, used for the `gap`.

Membership drifts. A name that stops returning data is left out of the count
rather than treated as a faller, so the percentage stays correct; the run fails
outright if more than 10% of the list goes missing, because a percentage
measured on a partial universe is worse than none.

## Licence

Public domain (CC0). Prices come from Yahoo Finance and carry their own terms.
