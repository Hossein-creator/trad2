"""Does price action make the morning trades better? Replay on past bars. Sends nothing, uses no keys.

Same as backtest_morning.py: rated at 09:30 Berlin on the 1h bars closed by 09:00, entry at the open of the 15-minute
bar at 09:30, stop and 2R target on the 15-minute highs and lows (a bar touching both counts as the stop), closed at
market at 12:30 Berlin. Costs: taker 0.06 % each way, slippage 0.02 % on the entry, funding 0.01 %. Minimum stop 2 %.

Price action (trader/price_action.py) is read for the trade's side on the last 120 1h bars and the last 120
15-minute bars before 09:30. Then:
  1. each price-action feature on every rated contract: trades with it against those without it
  2. ways to pick two trades a day: today's rule, with price action as a filter, a veto, extra points or an 8th check
Every line is split into the older 60 % and the newer 40 % of the days; only what holds on both counts.

Usage: python trader/backtest_pa.py BARS_1H_FOLDER BARS_15M_FOLDER
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
import price_action as P  # noqa: E402

FEE, SLIP, FUND = 0.0006, 0.0002, 0.0001
TARGETS = (1.5, 2.0)
EXIT = (12, 30)
LOOK = 120


def features(pa, tf):
    """The price-action reading as a set of names."""
    out = {tf + ":check"} if pa["check"] else {tf + ":no check"}
    if pa["against"]:
        out.add(tf + ":anything against")
    if pa["trigger"]:
        out.add(tf + ":any trigger")
    for k, v in pa["parts"].items():
        out.add("%s:%s %s" % (tf, k, "+" if v > 0 else "-"))
    for n in pa["trigger"]:
        out.add(tf + ":trigger " + n.replace(" (bar before)", ""))
    for n in pa["against"]:
        out.add(tf + ":against " + n.replace(" (bar before)", ""))
    if pa.get("pullback"):
        out.add(tf + ":pullback " + pa["pullback"])
    return out


def replay(job):
    path1, path15 = job
    c = B.load(path1)
    q = json.load(open(path15))["bars"]
    qt = [datetime.datetime.fromtimestamp(b[0] / 1000, datetime.UTC).replace(tzinfo=None) for b in q]
    h4t = [x["t"] for x in c["h4"]]
    dt = [x["t"] for x in c["d"]]
    four, one = datetime.timedelta(hours=4), datetime.timedelta(hours=24)
    out, seen = [], set()
    for when in qt:
        d = when.date()
        if d in seen or when.weekday() > 4:
            continue
        seen.add(d)
        noon = datetime.datetime(d.year, d.month, d.day, 12)
        off = D.K.berlin(noon) - noon
        start = datetime.datetime(d.year, d.month, d.day, 9, 30) - off
        rated_at = datetime.datetime(d.year, d.month, d.day, 9) - off
        end = datetime.datetime(d.year, d.month, d.day, EXIT[0], EXIT[1]) - off
        i_h = bisect.bisect_left(c["ht"], rated_at)
        i_q = bisect.bisect_left(qt, start)
        if i_h < LOOK or i_q < LOOK or i_q >= len(q) or qt[i_q] != start:
            continue
        b4 = c["h4"][max(0, bisect.bisect_right(h4t, rated_at - four) - 200):bisect.bisect_right(h4t, rated_at - four)]
        bd = c["d"][max(0, bisect.bisect_right(dt, rated_at - one) - 60):bisect.bisect_right(dt, rated_at - one)]
        if len(b4) < 80 or len(bd) < 26:
            continue
        b1 = c["h"][max(0, i_h - 200):i_h]
        q15 = [{"o": b[1], "h": b[2], "l": b[3], "c": b[4], "v": b[5]} for b in q[i_q - LOOK:i_q]]
        for side in ("long", "short"):
            row = rate_side(c, q, qt, i_q, end, b4, b1, bd, q15, rated_at, side)
            if row:
                row["day"] = d.toordinal()
                out.append(row)
    return out


def simulate(q, qt, i, end, long_, stop):
    """Entry at the open of 15-minute bar i, stop and each target on the highs and lows, close at end: net R."""
    if i >= len(q):
        return None
    sign = 1 if long_ else -1
    entry = q[i][1] * (1 + sign * SLIP)
    if sign * (entry - stop) <= 0:
        return None
    risk = abs(entry - stop)
    worst = risk + (entry + stop) * FEE + entry * FUND
    res = {}
    for tgt in TARGETS:
        price = entry + sign * tgt * risk
        px = entry
        for b, t in zip(q[i:i + 16], qt[i:i + 16]):
            if t >= end:
                break
            if (b[3] <= stop) if long_ else (b[2] >= stop):
                px = stop
                break
            if (b[2] >= price) if long_ else (b[3] <= price):
                px = price
                break
            px = b[4]
        res[tgt] = (sign * (px - entry) - (entry + px) * FEE - entry * FUND) / worst
    return res


def rate_side(c, q, qt, i_q, end, b4, b1, bd, q15, rated_at, side):
    """One side of one contract on one day: the rating, the price action and the result, or None."""
    try:
        r = D.rate(b4, b1, bd, rated_at, c["tick"], side=side)
    except (ValueError, ZeroDivisionError, TypeError):
        return None
    if r["verdict"] != "ok":
        return None
    long_ = r["side"] == "long"
    res = simulate(q, qt, i_q, end, long_, r["stop"])
    if res is None:
        return None
    pa1 = P.read(b1[-LOOK:], long_)
    pa15 = P.read(q15, long_)
    # wait for a 15-minute trigger: the first bar closing by 10:30 Berlin with the price-action check, entry at the
    # next bar's open, same stop (it must still lie 1 to 5 % away)
    wait = None
    for k in range(4):
        win = [{"o": b[1], "h": b[2], "l": b[3], "c": b[4], "v": b[5]} for b in q[i_q - LOOK + 1 + k:i_q + 1 + k]]
        b = q[i_q + k]
        if (b[3] <= r["stop"]) if long_ else (b[2] >= r["stop"]):
            break                                             # the stop was hit before any trigger: no trade
        if P.read(win, long_)["check"]:
            got = simulate(q, qt, i_q + k + 1, end, long_, r["stop"])
            if got is not None and 1.0 <= abs(q[i_q + k + 1][1] - r["stop"]) / q[i_q + k + 1][1] * 100 <= 5.0:
                wait = {"k": k, "res": got}
            break
    return {"sym": c["symbol"], "met": r["met"], "score": r["score"], "side": r["side"], "wait": wait,
                "trend": r["side"] == ("long" if r["trend"]["direction"] == "up" else "short"),
                "pa1": {"check": pa1["check"], "points": pa1["points"], "against": bool(pa1["against"])},
                "pa15": {"check": pa15["check"], "points": pa15["points"], "against": bool(pa15["against"])},
                "f": sorted(features(pa1, "1h") | features(pa15, "15m")), "res": res}


def split(rows, cut, tgt):
    old = [x["res"][tgt] for x in rows if x["day"] <= cut]
    new = [x["res"][tgt] for x in rows if x["day"] > cut]
    return S.stats(old), S.stats(new)


def pick(by_day, keep, key, n=2):
    """Each day the first n rows by key among those kept, one side per contract."""
    out = []
    for d, v in by_day.items():
        got = []
        for x in sorted([x for x in v if keep(x)], key=key):
            if x["sym"] not in [y["sym"] for y in got]:
                got.append(x)
            if len(got) == n:
                break
        out += got
    return out


def features_block(rows, cut, tgt, title):
    print("\n%s (2R, closed 12:30): trades with the feature" % title)
    base_o, base_n = split(rows, cut, tgt)
    print("  all of them                       older %s\n  %-34s newer %s" % (S.show(base_o), "", S.show(base_n)))
    lines = []
    for f in sorted({f for x in rows for f in x["f"]}):
        w = [x for x in rows if f in x["f"]]
        if len(w) < 150:
            continue
        o, n = split(w, cut, tgt)
        lines.append((min(o["mean"] - base_o["mean"], n["mean"] - base_n["mean"]), f, o, n))
    for gain, f, o, n in sorted(lines, reverse=True):
        both = "  better on both" if o["mean"] > base_o["mean"] and n["mean"] > base_n["mean"] else ""
        print("  %-34s older %s\n  %-34s newer %s%s" % (f, S.show(o), "", S.show(n), both))


def main():
    f1, f15 = sys.argv[1], sys.argv[2]
    names = sorted(n for n in os.listdir(f15) if os.path.exists(os.path.join(f1, n)))
    with multiprocessing.Pool(6) as pool:
        done = pool.map(replay, [(os.path.join(f1, n), os.path.join(f15, n)) for n in names], chunksize=1)
    rows = [x for rs in done for x in rs]
    days = sorted({x["day"] for x in rows})
    cut = days[int(len(days) * S.TRAIN)]
    first, last = datetime.date.fromordinal(days[0]), datetime.date.fromordinal(days[-1])
    print("%d contracts, %d weekdays %s to %s, %d rated contract-days; older 60 %% to %s" % (
        len(names), len(days), first, last, len(rows), datetime.date.fromordinal(cut)))
    tgt = 2.0
    with_trend = [x for x in rows if x["trend"]]
    features_block(with_trend, cut, tgt, "1a. Price action on the trend side (today's direction rule)")
    features_block([x for x in rows if not x["trend"]], cut, tgt, "1b. Price action against the 4h trend")

    by_day, all_day = {}, {}
    for x in with_trend:
        by_day.setdefault(x["day"], []).append(x)
    for x in rows:
        all_day.setdefault(x["day"], []).append(x)
    rng = random.Random(7)
    rand = []
    for d, v in by_day.items():
        rand += rng.sample(v, min(2, len(v)))
    pa = lambda x: x["pa1"]["points"] + x["pa15"]["points"]  # noqa: E731
    sides = [
        ("against the trend, top 2", lambda x: not x["trend"], lambda x: (-x["met"], -x["score"])),
        ("either side, top 2 by checks", lambda x: True, lambda x: (-x["met"], -x["score"])),
        ("either side, best PA points", lambda x: True, lambda x: -pa(x)),
        ("either side, both PA checks", lambda x: x["pa1"]["check"] and x["pa15"]["check"],
         lambda x: (-x["met"], -x["score"])),
        ("either side, both checks, best PA", lambda x: x["pa1"]["check"] and x["pa15"]["check"], lambda x: -pa(x)),
        ("against trend, both PA checks", lambda x: not x["trend"] and x["pa1"]["check"] and x["pa15"]["check"],
         lambda x: (-x["met"], -x["score"])),
    ]
    rules = [
        ("today's rule (top 2)", lambda x: True, lambda x: (-x["met"], -x["score"])),
        ("random 2", None, None),
        ("+ PA points", lambda x: True, lambda x: (-x["met"], -(x["score"] + pa(x)))),
        ("PA as 8th and 9th check", lambda x: True,
         lambda x: (-(x["met"] + x["pa1"]["check"] + x["pa15"]["check"]), -x["score"])),
        ("veto: nothing against 1h", lambda x: not x["pa1"]["against"], lambda x: (-x["met"], -x["score"])),
        ("veto: nothing against 15m", lambda x: not x["pa15"]["against"], lambda x: (-x["met"], -x["score"])),
        ("veto: nothing against both", lambda x: not x["pa1"]["against"] and not x["pa15"]["against"],
         lambda x: (-x["met"], -x["score"])),
        ("only with 1h PA check", lambda x: x["pa1"]["check"], lambda x: (-x["met"], -x["score"])),
        ("only with 15m PA check", lambda x: x["pa15"]["check"], lambda x: (-x["met"], -x["score"])),
        ("only with 1h or 15m check", lambda x: x["pa1"]["check"] or x["pa15"]["check"],
         lambda x: (-x["met"], -x["score"])),
        ("only with both checks", lambda x: x["pa1"]["check"] and x["pa15"]["check"],
         lambda x: (-x["met"], -x["score"])),
        ("PA points > 0 both", lambda x: x["pa1"]["points"] > 0 and x["pa15"]["points"] > 0,
         lambda x: (-x["met"], -x["score"])),
        ("best PA points only", lambda x: True, lambda x: -pa(x)),
        ("5+ of 7 and 15m check", lambda x: x["met"] >= 5 and x["pa15"]["check"], lambda x: -x["score"]),
        ("5+ of 7, nothing against", lambda x: x["met"] >= 5 and not x["pa1"]["against"] and not x["pa15"]["against"],
         lambda x: -x["score"]),
    ]
    for t in TARGETS:
        print("\n2. Two trades a day, %.1fR target, closed 12:30 (fewer trades where the rule found none)" % t)
        for name, keep, key in rules:
            chosen = rand if keep is None else pick(by_day, keep, key)
            o, n = split(chosen, cut, t)
            print("  %-34s older %s\n  %-34s newer %s" % (name, S.show(o), "", S.show(n)))
        print("  -- wait from 09:30 to 10:30 for a 15-minute price-action trigger, enter on the next bar")
        waits = [
            ("top 2 that trigger, by checks", lambda x: x["wait"] is not None, lambda x: (-x["met"], -x["score"])),
            ("first 2 to trigger", lambda x: x["wait"] is not None, lambda x: (x["wait"]["k"], -x["met"], -x["score"])),
            ("5+ of 7 that trigger", lambda x: x["wait"] is not None and x["met"] >= 5,
             lambda x: (-x["met"], -x["score"])),
            ("today's top 5, those that trigger", None, None),
        ]
        for name, keep, key in waits:
            if keep is None:
                top5 = []
                for d, v in by_day.items():
                    top5 += [x for x in sorted(v, key=lambda x: (-x["met"], -x["score"]))[:5] if x["wait"]][:2]
                chosen = top5
            else:
                chosen = pick(by_day, keep, key)
            o, n = split([dict(x, res=x["wait"]["res"]) for x in chosen], cut, t)
            print("  %-34s older %s\n  %-34s newer %s" % (name, S.show(o), "", S.show(n)))
        print("  -- the side chosen by price action instead of the 4h trend")
        for name, keep, key in sides:
            o, n = split(pick(all_day, keep, key), cut, t)
            print("  %-34s older %s\n  %-34s newer %s" % (name, S.show(o), "", S.show(n)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
