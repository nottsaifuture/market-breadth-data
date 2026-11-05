#!/usr/bin/env python3
"""
Broad-market breadth for the S&P 500, written to breadth.json.

Run by GitHub Actions twice a day (20:20 and 21:20 UTC — one of those is
always about 20 minutes after the US close, whichever side of the clock
change we are on). The Apps Script dashboard reads the resulting JSON with a
single request instead of making 495 of its own.

Stateless by design: it downloads two years fresh each run and recomputes
everything. There is no cache to corrupt, so a bad run is fixed by the next
one rather than by a human.

    python3 build_breadth.py            # writes breadth.json
    python3 build_breadth.py --check f  # also compare against a fixture
"""

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf

HERE = Path(__file__).resolve().parent

# --- the rules, identical to Breadth500.gs --------------------------------
MA_FAST, MA_SLOW = 50, 200
HI_WINDOW = 252          # sessions in the 52-week high
NEAR_HIGH = 3.0          # "at a high" = within this % of the 52-week high
T50, T200 = 30.0, 65.0   # the two divergence conditions
WINDOW = 120             # sessions a watch stays open once it opens
KEEP = 300               # sessions published in the JSON
NDX, SPX = "^NDX", "^GSPC"

# A stock closing exactly on its average is not "above" it. Without this the
# 1e-13 drift in a rolling mean decides the answer, one name moves the figure
# by 0.2 points, and nothing reconciles with anything else. See NWS on
# 21 Sep 2026: close 32.86, 50-day average 32.86.
EPS = 1e-10


def read_list(name):
    out = []
    for line in (HERE / name).read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            out.append(line)
    return out


def load_universe():
    names, narrow = read_list("universe.txt"), read_list("universe_30.txt")
    missing = [t for t in narrow if t not in names]
    if missing:
        sys.exit("30-name list is not a subset of the 500: " + ", ".join(missing))
    return names, narrow


def download(symbols, period="2y"):
    """Closes only. Chunked so one bad batch cannot lose the whole download."""
    parts = []
    for i in range(0, len(symbols), 60):
        chunk = symbols[i:i + 60]
        for attempt in range(3):
            try:
                d = yf.download(chunk, period=period, auto_adjust=True,
                                progress=False, threads=True)
                if d is not None and len(d):
                    parts.append(d["Close"])
                    break
            except Exception as exc:                      # noqa: BLE001
                print(f"  retry {i} ({exc})", file=sys.stderr)
        else:
            print(f"  chunk at {i} failed three times, continuing", file=sys.stderr)
    if not parts:
        sys.exit("no price data at all — Yahoo is down, nothing written")
    close = pd.concat(parts, axis=1)
    return close.loc[:, ~close.columns.duplicated()]


def above(px, ma):
    """Strictly above, with an exact tie counted as not above."""
    return (px - ma) > ma.abs() * EPS


def compute(close, names, narrow):
    # Rows where the index itself did not trade are not US sessions: they creep
    # in from foreign listings in the same download and would put holidays in
    # the history.
    close = close[close[SPX].notna()]
    have = [t for t in names if t in close.columns]
    stocks = close[have]

    ma50, ma200 = stocks.rolling(MA_FAST).mean(), stocks.rolling(MA_SLOW).mean()
    up50, up200 = above(stocks, ma50), above(stocks, ma200)
    n50, n200 = ma50.notna().sum(axis=1), ma200.notna().sum(axis=1)

    nar = [t for t in narrow if t in stocks.columns]
    nUp, nTot = up50[nar].sum(axis=1), ma50[nar].notna().sum(axis=1)

    def pct(a, b):
        return (a / b.replace(0, np.nan) * 100).round(1)

    df = pd.DataFrame({
        "pct50": pct(up50.sum(axis=1), n50),
        "pct200": pct(up200.sum(axis=1), n200),
        "narrow50": pct(nUp, nTot),
        "above50": up50.sum(axis=1).astype(int),
        "counted50": n50.astype(int),
        "counted200": n200.astype(int),
        "narrowCounted": nTot.astype(int),
    })
    for sym, col in ((NDX, "ndxDist"), (SPX, "spxDist")):
        if sym in close.columns:
            px = close[sym]
            df[col] = (px / px.rolling(HI_WINDOW, min_periods=1).max() - 1).mul(100).round(1)
        else:
            df[col] = np.nan

    df = df[df["counted50"] > 0].copy()
    df["gap"] = (df["narrow50"] - df["pct50"]).round(1)

    near = df["ndxDist"] >= -NEAR_HIGH
    df["lit"] = ((near & (df["pct200"] < T200)).astype(int) +
                 (near & (df["pct50"] < T50)).astype(int))

    # The watch: opens on a two-condition day and runs WINDOW sessions. Further
    # red days inside it do not restart the clock, which is what makes the
    # "day N of 120" on the reference site mean anything.
    states, days, froms = [], [], []
    open_at = None
    for i, (idx, row) in enumerate(df.iterrows()):
        if open_at is not None and i - open_at[0] >= WINDOW:
            open_at = None
        if open_at is None and row["lit"] == 2:
            open_at = (i, idx)
        if open_at is not None:
            states.append("WATCH")
            days.append(i - open_at[0] + 1)
            froms.append(open_at[1])
        else:
            states.append("AMBER" if row["lit"] == 1 else "CLEAR")
            days.append(None)
            froms.append(None)
    df["state"], df["day"], df["watchFrom"] = states, days, froms
    return df


def to_rows(df):
    out = []
    for idx, r in df.iterrows():
        def num(key, cast=float):
            v = r[key]
            return None if pd.isna(v) else cast(v)
        out.append({
            "date": idx.strftime("%Y-%m-%d"),
            "pct50": num("pct50"), "pct200": num("pct200"),
            "narrow50": num("narrow50"), "gap": num("gap"),
            "above50": num("above50", int), "counted50": num("counted50", int),
            "counted200": num("counted200", int),
            "narrowCounted": num("narrowCounted", int),
            "ndxDist": num("ndxDist"), "spxDist": num("spxDist"),
            "lit": num("lit", int), "state": r["state"],
            "day": None if r["day"] is None or pd.isna(r["day"]) else int(r["day"]),
            "watchFrom": None if (r["watchFrom"] is None or pd.isna(r["watchFrom"]))
                         else pd.Timestamp(r["watchFrom"]).strftime("%Y-%m-%d"),
        })
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", metavar="FILE",
                    help="compare the result against a fixture and exit non-zero on a mismatch")
    ap.add_argument("--out", default=str(HERE / "breadth.json"))
    ap.add_argument("--period", default="2y")
    ap.add_argument("--cache", metavar="FILE",
                    help="read closes from a {d, c} JSON instead of downloading, "
                         "so the maths can be tested offline against a fixture")
    args = ap.parse_args()

    names, narrow = load_universe()
    print(f"universe: {len(names)} names + 2 indices")
    if args.cache:
        raw = json.loads(Path(args.cache).read_text())
        close = pd.DataFrame(raw["c"], index=pd.to_datetime(raw["d"]))
        print(f"loaded {close.shape[1]} symbols from {args.cache} (no download)")
    else:
        close = download(names + [NDX, SPX], args.period)
    got = [t for t in names if t in close.columns and close[t].notna().any()]
    print(f"downloaded: {len(got)} of {len(names)}")
    if len(got) < len(names) * 0.9:
        sys.exit(f"only {len(got)} of {len(names)} names came back — refusing to "
                 "publish a percentage measured on a partial universe")
    for sym in (NDX, SPX):
        if sym not in close.columns or close[sym].notna().sum() < HI_WINDOW:
            sys.exit(f"{sym} is missing — the 52-week-high test cannot be made")

    df = compute(close, names, narrow)
    rows = to_rows(df)[-KEEP:]
    if not rows:
        sys.exit("computed no rows")

    payload = {
        "generated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "universe": len(got),
        "rules": {"nearHigh": NEAR_HIGH, "t50": T50, "t200": T200, "window": WINDOW},
        "latest": rows[-1],
        "history": rows,
    }
    Path(args.out).write_text(json.dumps(payload, indent=1) + "\n")

    last = rows[-1]
    print(f"{last['date']}  broad {last['pct50']}%  ({last['above50']} of "
          f"{last['counted50']})   30 names {last['narrow50']}%   "
          f"gap {last['gap']} pp   NDX {last['ndxDist']}%   {last['state']}"
          + (f" day {last['day']}/{WINDOW}" if last["day"] else ""))
    print(f"wrote {args.out} ({len(rows)} rows)")

    if args.check:
        ref = {r["date"]: r for r in json.loads(Path(args.check).read_text())}
        bad, n = [], 0
        for r in rows:
            e = ref.get(r["date"])
            if not e or e.get("pct200") is None:
                continue
            n += 1
            for k in ("pct50", "pct200", "ndxDist", "counted50"):
                if abs((r[k] or 0) - (e[k] or 0)) > 1e-9:
                    bad.append(f"{r['date']} {k}: {r[k]} vs {e[k]}")
        print(f"checked {n} rows against the fixture")
        if bad:
            print("MISMATCH:\n  " + "\n  ".join(bad[:10]))
            sys.exit(1)
        print("fixture check: exact match")


if __name__ == "__main__":
    main()
