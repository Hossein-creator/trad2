"""Replay the daily rules on past KuCoin 1h bars. Sends nothing, uses no keys.

Each weekday: rate every contract at 09:00, 10:00 and 11:00 Berlin (08, 09, 10 UTC). A trade enters at the open of
the bar after its check, with the stop-loss and 2R target on the hourly highs and lows, and closes at 21:00 UTC.
A bar that touches both counts as the stop. Costs: taker fee 0.06 % each way, slippage 0.02 % on the entry, funding
0.015 %. Results in net R: profit after costs divided by the loss at the stop after costs.

Variants  random   two random contracts at 11:00, same direction rule and same stops: the baseline to beat
          top2     the two with the most points at 11:00, every day
          n of 7   wait: the first contracts meeting at least n of the 7 checks at one of the three times, at most
                   two a day, none on a day without one

Then every contract at 11:00 split by each check and points: the trades with it against those without it.

Usage: python trader/backtest_daily.py BARS_FOLDER
"""
import bisect
import datetime
import glob
import json
import os
import random
import statistics
import sys

sys.path.insert(0, os.path.dirname(__file__))
import daily as D  # noqa: E402

FEE, SLIP, FUND = 0.0006, 0.0002, 0.00015
CHECKS = (8, 9, 10)       # UTC hours of the three checks; the last one decides
EXIT_HOUR = 21
WAITS = (4, 5, 6, 7)


def load(path):
    doc = json.load(open(path))
    h = [{"t": datetime.datetime.fromtimestamp(b[0] / 1000, datetime.UTC).replace(tzinfo=None), "o": b[1], "h": b[2],
          "l": b[3], "c": b[4], "v": b[5]} for b in doc["bars"]]

    def group(hours):
        out, cur = [], None
        for x in h:
            start = x["t"].replace(hour=x["t"].hour - x["t"].hour % hours)
            if cur is None or cur["t"] != start:
                cur = dict(x, t=start, n=1)
                out.append(cur)
            else:
                cur["h"], cur["l"], cur["c"] = max(cur["h"], x["h"]), min(cur["l"], x["l"]), x["c"]
                cur["v"] += x["v"]
                cur["n"] += 1
        return [x for x in out if x["n"] == hours]
    return {"symbol": doc["symbol"], "tick": doc["tick"], "h": h, "ht": [x["t"] for x in h], "h4": group(4),
            "d": group(24)}


def rate_at(c, t):
    """Rate from bars closed at time t."""
    i = bisect.bisect_left(c["ht"], t)
    b1 = c["h"][max(0, i - 200):i]
    b4 = [x for x in c["h4"] if x["t"] + datetime.timedelta(hours=4) <= t][-200:]
    bd = [x for x in c["d"] if x["t"] + datetime.timedelta(hours=24) <= t][-60:]
    if len(b4) < 80 or len(b1) < 60 or len(bd) < 26:
        return None
    r = D.rate(b4, b1, bd, t, c["tick"])
    return r if r["verdict"] == "ok" else None


def play(c, t, r):
    i = bisect.bisect_left(c["ht"], t)
    if i >= len(c["h"]) or c["ht"][i] != t:
        return None
    long_ = r["side"] == "long"
    sign = 1 if long_ else -1
    entry = c["h"][i]["o"] * (1 + sign * SLIP)
    risk = abs(entry - r["stop"])
    if risk <= 0 or (long_ and entry <= r["stop"]) or (not long_ and entry >= r["stop"]):
        return None
    target = entry + sign * D.TARGET_R * risk
    close_at = t.replace(hour=EXIT_HOUR)
    out, last = None, entry
    for x in c["h"][i:]:
        if x["t"] >= close_at:
            break
        if (x["l"] <= r["stop"]) if long_ else (x["h"] >= r["stop"]):
            out = r["stop"]
            break
        if (x["h"] >= target) if long_ else (x["l"] <= target):
            out = target
            break
        last = x["c"]
    if out is None:
        out = last
    cost = (entry + out) * FEE + entry * FUND
    worst = risk + (entry + r["stop"]) * FEE + entry * FUND
    return (sign * (out - entry) - cost) / worst


def line(xs):
    if not xs:
        return "no trades"
    wins = sum(1 for x in xs if x > 0)
    return "%4d trades, %3.0f %% wins, %+.3fR each, %+7.1fR total" % (
        len(xs), 100.0 * wins / len(xs), statistics.mean(xs), sum(xs))


def summary(name, rs):
    half = len(rs) // 2
    print("  %-10s all    %s" % (name, line(rs)))
    print("  %-10s first  %s" % ("", line(rs[:half])))
    print("  %-10s second %s" % ("", line(rs[half:])))


def main():
    coins = [load(p) for p in glob.glob(os.path.join(sys.argv[1], "*.json"))]
    coins = [c for c in coins if len(c["h"]) > 1000]
    first = min(c["ht"][0] for c in coins) + datetime.timedelta(days=40)
    last = max(c["ht"][-1] for c in coins) - datetime.timedelta(days=1)
    print("%d contracts, %s to %s" % (len(coins), first.date(), last.date()))
    res = {"random": [], "top2": []}
    for n in WAITS:
        res["%d of 7" % n] = []
    days = {n: 0 for n in WAITS}
    workdays = 0
    feat = {}
    rng = random.Random(7)
    day = first.replace(hour=0, minute=0, second=0, microsecond=0)
    while day <= last:
        if day.weekday() < 5:
            workdays += 1
            seen, final, hits = {}, [], {n: [] for n in WAITS}
            for hour in CHECKS:
                t = day.replace(hour=hour)
                rated = [(c, rate_at(c, t)) for c in coins]
                rated = sorted([(c, r) for c, r in rated if r], key=lambda p: -p[1]["score"])
                for n in WAITS:
                    used = {c["symbol"] for c, _, _ in hits[n]}
                    for c, r in sorted(rated, key=lambda p: -p[1]["met"]):
                        if r["met"] >= n and c["symbol"] not in used and len(hits[n]) < D.MAX_TRADES:
                            hits[n].append((c, r, t))
                            used.add(c["symbol"])
                if hour == CHECKS[-1]:
                    for c, r in rated:
                        r["total"] = r["score"] + D.REPEAT_POINTS * seen.get((c["symbol"], r["side"]), 0)
                    final = sorted(rated, key=lambda p: -p[1]["total"])
                else:
                    for c, r in rated[:5]:
                        seen[(c["symbol"], r["side"])] = seen.get((c["symbol"], r["side"]), 0) + 1
            t = day.replace(hour=CHECKS[-1])
            for c, r in final[:2]:
                x = play(c, t, r)
                if x is not None:
                    res["top2"].append(x)
            if len(final) >= 2:
                for c, r in rng.sample(final, 2):
                    x = play(c, t, r)
                    if x is not None:
                        res["random"].append(x)
            for n in WAITS:
                if hits[n]:
                    days[n] += 1
                for c, r, when in hits[n]:
                    x = play(c, when, r)
                    if x is not None:
                        res["%d of 7" % n].append(x)
            for c, r in final:
                x = play(c, t, r)
                if x is None:
                    continue
                for k, v in r["checks"].items():
                    feat.setdefault("check " + k, ([], []))[0 if v else 1].append(x)
                for k in ("fvg4", "fvg1", "flip", "candle", "strong_zone"):
                    feat.setdefault("part " + k, ([], []))[0 if k in r["parts"] else 1].append(x)
                feat.setdefault("fib golden", ([], []))[0 if r["parts"].get("fib") == 15 else 1].append(x)
        day += datetime.timedelta(days=1)
    for name in res:
        summary(name, res[name])
    print("  workdays %d; days with a trade: %s" % (workdays, ", ".join("%d of 7: %d" % (n, days[n]) for n in WAITS)))
    print("  every contract at 11:00, with / without:")
    for k in sorted(feat):
        print("  %-18s with    %s" % (k, line(feat[k][0])))
        print("  %-18s without %s" % ("", line(feat[k][1])))
    return 0


if __name__ == "__main__":
    sys.exit(main())
