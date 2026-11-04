"""Replay the daily rules in as many scenarios as the past bars allow. Sends nothing, uses no keys.

  rate  every contract, every second hour of every weekday: the rating of trader/daily.py from bars closed by then,
        and the outcome in net R of every target and holding time, with the trend's direction and against it.
  scan  scenario = entry hours x side x condition x target x holding time x direction, at most two trades a day in
        different contracts, the most checks met first. The scenarios are picked on the older 60 % of the days only
        and then judged on the newer 40 %, which they have not seen. Without that split the best of thousands of
        scenarios looks good by luck alone.

Costs as in backtest_daily.py: taker fee 0.06 % each way, slippage 0.02 % on the entry, funding 0.01 % per 8 hours.
A bar that touches both the stop and the target counts as the stop.

Usage: python trader/backtest_scenarios.py rate BARS_FOLDER RATINGS.pickle
       python trader/backtest_scenarios.py scan RATINGS.pickle
"""
import array
import bisect
import datetime
import glob
import math
import multiprocessing
import os
import pickle
import statistics
import sys

sys.path.insert(0, os.path.dirname(__file__))
import backtest_daily as B  # noqa: E402
import daily as D  # noqa: E402

FEE, SLIP, FUND_HOUR = 0.0006, 0.0002, 0.0001 / 8
TARGETS = (1.0, 2.0, 3.0, "zone")
HOLDS = ("day", 12, 24, 48)
FEATS = ("zone", "fvg", "fvg4", "fib", "fibgold", "rsi", "trend", "candle", "room", "flip", "volume", "strong",
         "pullback", "adx25", "daywith", "engulf")
BIT = {f: 1 << i for i, f in enumerate(FEATS)}
N_OUT = len(TARGETS) * len(HOLDS)
HOUR_SETS = {"09-11 Berlin": (8, 10), "11 Berlin": (10,), "13-15 Berlin": (12, 14), "17-19 Berlin": (16, 18),
             "21-23 Berlin": (20, 22), "01-07 Berlin": (0, 2, 4, 6), "any hour": tuple(range(0, 24, 2))}
SIDES = ("both", "long", "short")
TRAIN = 0.6
MIN_TRADES = 100


def outcomes(c, i, sign, entry, stop, room, hour):
    """Net R of each target and holding time for one entry at bar i."""
    risk = abs(entry - stop)
    worst = risk + (entry + stop) * FEE + entry * 0.00015
    bars = c["h"][i:i + 48]
    left = 21 - hour if hour < 21 else 45 - hour
    out = []
    for tgt in TARGETS:
        mult = room if tgt == "zone" else tgt
        if tgt == "zone" and not 1 <= room < 5:
            out += [float("nan")] * len(HOLDS)
            continue
        price = entry + sign * mult * risk
        hit_at, hit = None, None
        for n, x in enumerate(bars):
            if (x["l"] <= stop) if sign > 0 else (x["h"] >= stop):
                hit_at, hit = n, stop
                break
            if (x["h"] >= price) if sign > 0 else (x["l"] <= price):
                hit_at, hit = n, price
                break
        for h in HOLDS:
            n_h = left if h == "day" else h
            if hit_at is not None and hit_at < n_h:
                px, hours = hit, hit_at + 1
            elif len(bars) >= n_h:
                px, hours = bars[n_h - 1]["c"], n_h
            else:
                out.append(float("nan"))
                continue
            out.append((sign * (px - entry) - (entry + px) * FEE - entry * hours * FUND_HOUR) / worst)
    return out


def rate_coin(path):
    c = B.load(path)
    h4t = [x["t"] for x in c["h4"]]
    dt = [x["t"] for x in c["d"]]
    rows, outs = [], array.array("f")
    four, one = datetime.timedelta(hours=4), datetime.timedelta(hours=24)
    for i, t in enumerate(c["ht"]):
        if t.hour % 2 or t.weekday() > 4 or i < 60 or i + 48 > len(c["h"]):
            continue
        b4 = c["h4"][max(0, bisect.bisect_right(h4t, t - four) - 200):bisect.bisect_right(h4t, t - four)]
        bd = c["d"][max(0, bisect.bisect_right(dt, t - one) - 60):bisect.bisect_right(dt, t - one)]
        if len(b4) < 80 or len(bd) < 26:
            continue
        try:
            r = D.rate(b4, c["h"][max(0, i - 200):i], bd, t, c["tick"])
        except (ValueError, ZeroDivisionError, TypeError):
            continue
        if r["verdict"] != "ok":
            continue
        sign = 1 if r["side"] == "long" else -1
        entry = c["h"][i]["o"] * (1 + sign * SLIP)
        if sign * (entry - r["stop"]) <= 0:
            continue
        k, p, tr = r["checks"], r["parts"], r["trend"]
        mask = 0
        for name, on in (("zone", k["zone"]), ("fvg", k["fvg"]), ("fvg4", "fvg4" in p), ("fib", k["fib"]),
                         ("fibgold", p.get("fib") == 15), ("rsi", k["rsi"]), ("trend", k["trend"]),
                         ("candle", k["candle"]), ("room", k["room"]), ("flip", "flip" in p), ("volume", "volume" in p),
                         ("strong", "strong_zone" in p), ("pullback", tr["phase"] == "pullback"),
                         ("adx25", (tr["adx"] or 0) >= 25), ("daywith", tr["day"] == tr["direction"]),
                         ("engulf", r["signal"] == "engulfing")):
            if on:
                mask |= BIT[name]
        room = r["room"] * r["risk"] / abs(entry - r["stop"])
        against_stop = entry + sign * abs(entry - r["stop"])
        outs.extend(outcomes(c, i, sign, entry, r["stop"], room, t.hour))
        outs.extend(outcomes(c, i, -sign, entry * (1 - 2 * sign * SLIP), against_stop, 99.0, t.hour))
        rows.append((t.toordinal(), t.hour, c["symbol"], 0 if sign > 0 else 1, r["met"], r["score"], mask))
    print(c["symbol"], len(rows), flush=True)
    return rows, outs


def rate_all(folder, out):
    files = sorted(glob.glob(os.path.join(folder, "*.json")))
    with multiprocessing.Pool(6) as pool:
        res = pool.map(rate_coin, files, chunksize=1)
    rows, outs = [], array.array("f")
    for r, o in res:
        rows += r
        outs.extend(o)
    pickle.dump({"rows": rows, "outs": outs}, open(out, "wb"))
    print("RATED %d contracts, %d ratings" % (len(files), len(rows)), flush=True)


def stats(xs):
    if not xs:
        return {"n": 0, "mean": 0.0, "win": 0.0, "t": 0.0, "total": 0.0}
    mean = statistics.mean(xs)
    sd = statistics.pstdev(xs) if len(xs) > 1 else 0.0
    return {"n": len(xs), "mean": mean, "win": 100.0 * sum(1 for x in xs if x > 0) / len(xs),
            "t": mean / (sd / math.sqrt(len(xs))) if sd else 0.0, "total": sum(xs)}


def show(s):
    return "%5d trades %3.0f %% wins %+.3fR each t %+5.1f total %+7.1fR" % (s["n"], s["win"], s["mean"], s["t"], s["total"])


def rank_corr(xs, ys):
    def ranks(v):
        order = sorted(range(len(v)), key=lambda i: v[i])
        out = [0] * len(v)
        for r, i in enumerate(order):
            out[i] = r
        return out
    a, b = ranks(xs), ranks(ys)
    ma, mb = statistics.mean(a), statistics.mean(b)
    top = sum((x - ma) * (y - mb) for x, y in zip(a, b))
    bot = math.sqrt(sum((x - ma) ** 2 for x in a) * sum((y - mb) ** 2 for y in b))
    return top / bot if bot else 0.0


def conditions():
    single = ["zone", "fvg", "fvg4", "fib", "fibgold", "rsi", "trend", "candle", "room", "flip", "volume", "strong",
              "pullback", "adx25", "daywith", "engulf"]
    out = [("none", 0, 0)]
    for n in (4, 5, 6):
        out.append(("%d of 7" % n, 0, n))
    for f in single:
        out.append((f, BIT[f], 0))
    for i, a in enumerate(single):
        for b in single[i + 1:]:
            out.append((a + "+" + b, BIT[a] | BIT[b], 0))
    return out


def scan(path):
    doc = pickle.load(open(path, "rb"))
    rows, outs = doc["rows"], doc["outs"]
    width = 2 * N_OUT
    days = sorted({r[0] for r in rows})
    cut = days[int(len(days) * TRAIN)]
    print("%d ratings, %d contracts, %d weekdays, %s to %s, older part up to %s" % (
        len(rows), len({r[2] for r in rows}), len(days), datetime.date.fromordinal(days[0]),
        datetime.date.fromordinal(days[-1]), datetime.date.fromordinal(cut)), flush=True)
    index = sorted(range(len(rows)), key=lambda i: (rows[i][0], -rows[i][4], -rows[i][5]))
    groups = {}
    for name, hours in HOUR_SETS.items():
        for side in SIDES:
            keep = [i for i in index if rows[i][1] in hours and (side == "both" or rows[i][3] == SIDES.index(side) - 1)]
            by_day = {}
            for i in keep:
                by_day.setdefault(rows[i][0], []).append(i)
            groups[(name, side)] = by_day
    results = []
    total_trades = 0
    for (hname, side), by_day in groups.items():
        for cname, need, met in conditions():
            picks = []
            for day, ids in by_day.items():
                used = set()
                for i in ids:
                    r = rows[i]
                    if r[4] >= met and r[6] & need == need and r[2] not in used:
                        picks.append((day, i))
                        used.add(r[2])
                        if len(used) == D.MAX_TRADES:
                            break
            if len(picks) < MIN_TRADES:
                continue
            for d_i, direction in enumerate(("with", "against")):
                for t_i, tgt in enumerate(TARGETS):
                    if direction == "against" and tgt == "zone":
                        continue
                    for h_i, hold in enumerate(HOLDS):
                        at = d_i * N_OUT + t_i * len(HOLDS) + h_i
                        old, new = [], []
                        for day, i in picks:
                            x = outs[i * width + at]
                            if x == x:
                                (old if day <= cut else new).append(x)
                        total_trades += len(old) + len(new)
                        if len(old) >= MIN_TRADES and len(new) >= 30:
                            results.append({"hours": hname, "side": side, "cond": cname, "dir": direction, "target": tgt,
                                            "hold": hold, "old": stats(old), "new": stats(new)})
    print("%d scenarios, %d simulated trades" % (len(results), total_trades), flush=True)

    def name(r):
        return "%-12s %-5s %-22s %-7s target %-4s hold %-3s" % (r["hours"], r["side"], r["cond"], r["dir"], r["target"], r["hold"])

    print("\nThe live rule: 11:00 Berlin, both sides, 2R, closed by 22:00")
    for r in results:
        if r["hours"] == "11 Berlin" and r["side"] == "both" and r["dir"] == "with" and r["target"] == 2.0 and r["hold"] == "day" \
                and r["cond"] in ("none", "4 of 7", "5 of 7", "6 of 7"):
            print("  %-8s older %s\n  %-8s newer %s" % (r["cond"], show(r["old"]), "", show(r["new"])))
    pos_old = sum(1 for r in results if r["old"]["mean"] > 0)
    pos_new = sum(1 for r in results if r["new"]["mean"] > 0)
    pos_both = sum(1 for r in results if r["old"]["mean"] > 0 and r["new"]["mean"] > 0)
    print("\nPositive after costs: older %d (%.1f %%), newer %d (%.1f %%), both %d (%.1f %%) of %d" % (
        pos_old, 100.0 * pos_old / len(results), pos_new, 100.0 * pos_new / len(results), pos_both,
        100.0 * pos_both / len(results), len(results)))
    print("Rank correlation older vs newer, all scenarios: %+.2f" % rank_corr(
        [r["old"]["mean"] for r in results], [r["new"]["mean"] for r in results]))
    print("By direction, average of the scenarios' mean R:")
    for d in ("with", "against"):
        sub = [r for r in results if r["dir"] == d]
        print("  %-8s older %+.3f newer %+.3f (%d scenarios)" % (d, statistics.mean(r["old"]["mean"] for r in sub),
                                                                statistics.mean(r["new"]["mean"] for r in sub), len(sub)))
    best = sorted(results, key=lambda r: -r["old"]["mean"])[:25]
    print("\nThe 25 best on the older days (mean R), judged on the newer days:")
    for r in best:
        print("  %s\n      older %s\n      newer %s" % (name(r), show(r["old"]), show(r["new"])))
    print("  these 25 on the newer days: average %+.3fR each, %d of 25 positive" % (
        statistics.mean(r["new"]["mean"] for r in best), sum(1 for r in best if r["new"]["mean"] > 0)))
    solid = [r for r in results if r["old"]["t"] >= 3 and r["old"]["n"] >= 200]
    print("\nStrong on the older days (t at least 3, at least 200 trades): %d scenarios" % len(solid))
    if solid:
        print("  on the newer days: average %+.3fR each, %d positive, %d with t at least 2" % (
            statistics.mean(r["new"]["mean"] for r in solid), sum(1 for r in solid if r["new"]["mean"] > 0),
            sum(1 for r in solid if r["new"]["t"] >= 2)))
        for r in sorted(solid, key=lambda r: -min(r["old"]["t"], r["new"]["t"]))[:15]:
            print("  %s\n      older %s\n      newer %s" % (name(r), show(r["old"]), show(r["new"])))
    print("\nEach parameter alone, with-trend scenarios, average of mean R on all days:")
    for key in ("hours", "side", "target", "hold"):
        vals = {}
        for r in results:
            if r["dir"] == "with":
                vals.setdefault(str(r[key]), []).append((r["old"]["mean"], r["new"]["mean"]))
        for v, xs in sorted(vals.items()):
            print("  %-7s %-14s older %+.3f newer %+.3f" % (key, v, statistics.mean(x[0] for x in xs), statistics.mean(x[1] for x in xs)))
    print("END")


if __name__ == "__main__":
    if sys.argv[1] == "rate":
        rate_all(sys.argv[2], sys.argv[3])
    else:
        scan(sys.argv[2])
