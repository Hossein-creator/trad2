"""A closer look at the scenarios that survived backtest_scenarios.py: the same trades by quarter, against a plain
baseline without any condition, with the t value counted per day (trades of one day move together), and the worst
drawdown. Usage: python trader/backtest_check.py RATINGS.pickle
"""
import datetime
import math
import os
import pickle
import statistics
import sys

sys.path.insert(0, os.path.dirname(__file__))
import backtest_scenarios as S  # noqa: E402

ANY = S.HOUR_SETS["any hour"]
ELEVEN = S.HOUR_SETS["11 Berlin"]
CASES = [
    ("short, Fib 50-66 %, day bars with, 3R, 24h", ANY, 1, S.BIT["fibgold"] | S.BIT["daywith"], 0, 0, 3.0, 24),
    ("same with 2R", ANY, 1, S.BIT["fibgold"] | S.BIT["daywith"], 0, 0, 2.0, 24),
    ("same, closed by 22:00, 2R", ANY, 1, S.BIT["fibgold"] | S.BIT["daywith"], 0, 0, 2.0, "day"),
    ("baseline: any short, 24h, 2R", ANY, 1, 0, 0, 0, 2.0, 24),
    ("baseline: any long, 24h, 2R", ANY, 0, 0, 0, 0, 2.0, 24),
    ("11:00, long signal 5 of 7, traded SHORT, 2R, 48h", ELEVEN, 0, 0, 5, 1, 2.0, 48),
    ("same with 3R", ELEVEN, 0, 0, 5, 1, 3.0, 48),
    ("same, closed by 22:00, 2R", ELEVEN, 0, 0, 5, 1, 2.0, "day"),
    ("baseline: 11:00, any long signal traded SHORT, 2R, 48h", ELEVEN, 0, 0, 0, 1, 2.0, 48),
    ("baseline: 11:00, any short signal traded SHORT, 2R, 48h", ELEVEN, 1, 0, 0, 0, 2.0, 48),
    ("live rule: 11:00, always 2, 2R, closed by 22:00", ELEVEN, None, 0, 0, 0, 2.0, "day"),
    ("live rule, only 5 of 7", ELEVEN, None, 0, 5, 0, 2.0, "day"),
]


def main():
    doc = pickle.load(open(sys.argv[1], "rb"))
    rows, outs = doc["rows"], doc["outs"]
    width = 2 * S.N_OUT
    index = sorted(range(len(rows)), key=lambda i: (rows[i][0], -rows[i][4], -rows[i][5]))
    for name, hours, side, need, met, against, tgt, hold in CASES:
        at = against * S.N_OUT + S.TARGETS.index(tgt) * len(S.HOLDS) + S.HOLDS.index(hold)
        days = {}
        used = {}
        for i in index:
            r = rows[i]
            if r[1] not in hours or (side is not None and r[3] != side) or r[4] < met or r[6] & need != need:
                continue
            u = used.setdefault(r[0], set())
            if r[2] in u or len(u) == 2:
                continue
            u.add(r[2])
            x = outs[i * width + at]
            if x == x:
                days.setdefault(r[0], []).append(x)
        per_day = [sum(v) for _, v in sorted(days.items())]
        xs = [x for _, v in sorted(days.items()) for x in v]
        s = S.stats(xs)
        t_day = statistics.mean(per_day) / (statistics.pstdev(per_day) / math.sqrt(len(per_day)))
        peak, eq, dd = 0.0, 0.0, 0.0
        for x in per_day:
            eq += x
            peak = max(peak, eq)
            dd = min(dd, eq - peak)
        print("\n%s" % name)
        print("  %s; t per day %+.1f; worst drawdown %.0fR" % (S.show(s), t_day, dd))
        quarters = {}
        for d, v in sorted(days.items()):
            day = datetime.date.fromordinal(d)
            quarters.setdefault("%d Q%d" % (day.year, (day.month - 1) // 3 + 1), []).extend(v)
        print("  " + "  ".join("%s %+.0fR" % (q, sum(v)) for q, v in sorted(quarters.items())))


if __name__ == "__main__":
    sys.exit(main())
