#!/usr/bin/env python3
"""
Refuses to publish a breadth.json that is obviously wrong.

The dashboard trusts this file, and a silently wrong percentage is worse than
no percentage at all — so anything that fails here stops the run instead of
being committed.
"""
import json
import sys
from datetime import datetime, timedelta, timezone

path = sys.argv[1] if len(sys.argv) > 1 else "breadth.json"
d = json.loads(open(path).read())
problems = []

rows = d.get("history") or []
last = d.get("latest") or {}

if len(rows) < 120:
    problems.append(f"only {len(rows)} rows of history; the 120-day watch needs more")
if not last:
    problems.append("no latest row")
if d.get("universe", 0) < 440:
    problems.append(f"universe down to {d.get('universe')} names")

for key, lo, hi in (("pct50", 0, 100), ("pct200", 0, 100), ("narrow50", 0, 100),
                    ("ndxDist", -90, 0.001)):
    v = last.get(key)
    if v is None:
        problems.append(f"latest {key} is missing")
    elif not (lo <= v <= hi):
        problems.append(f"latest {key} = {v}, outside {lo}..{hi}")

if last.get("state") not in ("CLEAR", "AMBER", "WATCH"):
    problems.append(f"bad state {last.get('state')!r}")
if last.get("state") == "WATCH" and not (1 <= (last.get("day") or 0) <= 120):
    problems.append(f"watch day {last.get('day')} outside 1..120")

try:
    age = (datetime.now(timezone.utc).date()
           - datetime.strptime(last["date"], "%Y-%m-%d").date()).days
    if age > 5:
        problems.append(f"newest session is {age} days old ({last['date']})")
    if age < 0:
        problems.append(f"newest session is in the future ({last['date']})")
except Exception as exc:                                        # noqa: BLE001
    problems.append(f"unreadable date: {exc}")

dates = [r["date"] for r in rows]
if len(set(dates)) != len(dates):
    problems.append("duplicate dates in the history")
if dates != sorted(dates):
    problems.append("history is not in date order")

# A day-to-day jump of more than 35 points has never happened and almost
# certainly means half the universe failed to download.
for a, b in zip(rows, rows[1:]):
    if a.get("pct50") is not None and b.get("pct50") is not None:
        if abs(b["pct50"] - a["pct50"]) > 35:
            problems.append(f"{a['date']} -> {b['date']}: pct50 jumped "
                            f"{a['pct50']} -> {b['pct50']}")

if problems:
    print("REFUSING TO PUBLISH:")
    for p in problems:
        print("  - " + p)
    sys.exit(1)

print(f"{path} looks sane: {last['date']}, {last['pct50']}% broad, "
      f"{last['narrow50']}% narrow, {len(rows)} rows, {d['universe']} names")
