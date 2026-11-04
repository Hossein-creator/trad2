"""Replay the morning window on past bars: rate at 09:30 Berlin, two trades, closed by 12:00 or 12:30 Berlin.
Sends nothing, uses no keys.

The rating uses the 1h bars closed by 09:00 Berlin, as the live script does at 09:30. Entry at the open of the 15-minute
bar at 09:30 Berlin, with stop and target on the 15-minute highs and lows, close at market at the end. A bar that
touches both counts as the stop. Costs: taker fee 0.06 % each way, slippage 0.02 % on the entry, funding 0.01 %.

Each minimum stop distance and target is one scenario, split into the older 60 % and newer 40 % of the days. The
random line is two random contracts on the same day with the same stop and target rules.

Usage: python trader/backtest_morning.py BARS_1H_FOLDER BARS_15M_FOLDER
"""
import bisect
import datetime
import json
import multiprocessing
import os
import random
import sys

sys.path.insert(0, os.path.dirname(__file__))
import backtest_daily as B  # noqa: E402
import backtest_scenarios as S  # noqa: E402
import daily as D  # noqa: E402

FEE, SLIP, FUND = 0.0006, 0.0002, 0.0001
MIN_STOPS = (0.5, 0.8, 1.0, 1.5, 2.0)
TARGETS = (1.0, 1.5, 2.0)
EXITS = ((12, 0), (12, 30))


def replay(job):
    """One contract, one minimum stop: for each weekday the rating and the net R of every target and exit."""
    path1, path15, min_stop = job
    D.MIN_STOP = min_stop
    c = B.load(path1)
    q = json.load(open(path15))["bars"]
    qt = [datetime.datetime.fromtimestamp(b[0] / 1000, datetime.UTC).replace(tzinfo=None) for b in q]
    h4t = [x["t"] for x in c["h4"]]
    dt = [x["t"] for x in c["d"]]
    four, one = datetime.timedelta(hours=4), datetime.timedelta(hours=24)
    out = []
    seen = set()
    for when in qt:
        d = when.date()
        if d in seen or when.weekday() > 4:
            continue
        seen.add(d)
        noon = datetime.datetime(d.year, d.month, d.day, 12)
        off = D.K.berlin(noon) - noon
        start = datetime.datetime(d.year, d.month, d.day, 9, 30) - off
        rated_at = datetime.datetime(d.year, d.month, d.day, 9) - off
        i_h = bisect.bisect_left(c["ht"], rated_at)
        i_q = bisect.bisect_left(qt, start)
        if i_h < 60 or i_q >= len(q) or qt[i_q] != start:
            continue
        b4 = c["h4"][max(0, bisect.bisect_right(h4t, rated_at - four) - 200):bisect.bisect_right(h4t, rated_at - four)]
        bd = c["d"][max(0, bisect.bisect_right(dt, rated_at - one) - 60):bisect.bisect_right(dt, rated_at - one)]
        if len(b4) < 80 or len(bd) < 26:
            continue
        try:
            r = D.rate(b4, c["h"][max(0, i_h - 200):i_h], bd, rated_at, c["tick"])
        except (ValueError, ZeroDivisionError, TypeError):
            continue
        if r["verdict"] != "ok":
            continue
        sign = 1 if r["side"] == "long" else -1
        entry = q[i_q][1] * (1 + sign * SLIP)
        stop = r["stop"]
        if sign * (entry - stop) <= 0:
            continue
        risk = abs(entry - stop)
        worst = risk + (entry + stop) * FEE + entry * FUND
        res = {}
        for tgt in TARGETS:
            price = entry + sign * tgt * risk
            for ex in EXITS:
                end = datetime.datetime(d.year, d.month, d.day, ex[0], ex[1]) - off
                px = entry
                for b, t in zip(q[i_q:i_q + 20], qt[i_q:i_q + 20]):
                    if t >= end:
                        break
                    if (b[3] <= stop) if sign > 0 else (b[2] >= stop):
                        px = stop
                        break
                    if (b[2] >= price) if sign > 0 else (b[3] <= price):
                        px = price
                        break
                    px = b[4]
                res[(tgt, ex)] = (sign * (px - entry) - (entry + px) * FEE - entry * FUND) / worst
        out.append((d.toordinal(), c["symbol"], r["met"], r["score"], r["stop_pct"], res))
    return min_stop, out


def main():
    f1, f15 = sys.argv[1], sys.argv[2]
    names = [n for n in os.listdir(f15) if os.path.exists(os.path.join(f1, n))]
    jobs = [(os.path.join(f1, n), os.path.join(f15, n), m) for n in names for m in MIN_STOPS]
    with multiprocessing.Pool(6) as pool:
        done = pool.map(replay, jobs, chunksize=1)
    print("%d contracts" % len(names))
    for m in MIN_STOPS:
        rows = [x for ms, rs in done if ms == m for x in rs]
        days = sorted({x[0] for x in rows})
        if not days:
            continue
        cut = days[int(len(days) * S.TRAIN)]
        by_day = {}
        for x in rows:
            by_day.setdefault(x[0], []).append(x)
        rng = random.Random(7)
        picks = {d: sorted(v, key=lambda x: (-x[2], -x[3]))[:2] for d, v in by_day.items()}
        rand = {d: rng.sample(v, min(2, len(v))) for d, v in by_day.items()}
        stops = sorted(x[4] for v in picks.values() for x in v)
        print("\nminimum stop %.1f %%: %d days, median stop %.2f %%" % (m, len(days), stops[len(stops) // 2]))
        for tgt in TARGETS:
            for ex in EXITS:
                for label, chosen in (("top2", picks), ("random", rand)):
                    old = [x[5][(tgt, ex)] for d, v in chosen.items() if d <= cut for x in v]
                    new = [x[5][(tgt, ex)] for d, v in chosen.items() if d > cut for x in v]
                    print("  %.1fR to %02d:%02d %-6s older %s\n  %-22s newer %s" % (tgt, ex[0], ex[1], label, S.show(S.stats(old)), "", S.show(S.stats(new))))
    return 0


if __name__ == "__main__":
    sys.exit(main())
