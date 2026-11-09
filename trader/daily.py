"""Daily setups on KuCoin Futures: two trades a day, decided at 09:30 Berlin, closed by 12:30 Berlin, 1x.
Every contract is rated on 7 checks and on points from trend, support and resistance, fair value gaps, Fibonacci,
RSI, candles and volume; the two with the most checks met, then the most points, are the trades, strong day or weak
day. Sends nothing.

Checks      trend    4h structure with the trade, close on the right side of the EMA50, ADX at least 20, day bars not against
            zone     at a support or resistance zone, tested in the last 8 hours and held
            rsi      1h RSI 30-60 (long) or 40-70 (short)
            candle   the last 1h bar closed the trade's way beyond the 1h EMA20, or a pinbar or engulfing candle
            fvg      inside an open fair value gap of the trade's side, 4h or 1h
            fib      38.2-78.6 % retracement of the last 4h swing
            room     the next zone ahead lies beyond the 2R target

Tested with trader/backtest_daily.py on 20 contracts, Dec 2025 to Nov 2026, after costs: always two trades -0.09R a
trade, 41 % wins (469 trades); two random contracts -0.08R. Waiting for 5 of 7: -0.09R, 271 trades on 175 of 235 days;
6 of 7: -0.20R, 48 trades on 44 days; 7 of 7: one trade in the year. No variant was positive. Zones and fair value gaps
showed a small gain, Fibonacci and RSI none, candle signals a small loss. The rating follows the chosen rules; it is
no forecast. On 50 contracts, Nov 2024 to Oct 2026 (trader/backtest_scenarios.py, results in
trader/backtest-scenarios.txt and backtest-check.txt): always two trades -0.10R, 41 % wins, 1002 trades; 5 of 7 -0.10R.
Those tests closed at 22:00. The 09:30 to 12:30 window (trader/backtest_morning.py, 29 contracts, one year, results in
trader/backtest-morning.txt): -0.06R a trade, 42 % wins, 528 trades, two random contracts -0.02R. A minimum stop of
2 % lost least; 0.5 to 1.5 % lost more.

Price action (trader/price_action.py, added 06.11.2026) reads the last 120 1h and 15-minute bars for the trade's side:
candle shapes, patterns (pinbar, engulfing, outside reversal, stars, piercing / dark cloud, tweezers, inside-bar
breakout, three soldiers / crows, strong close), breaks of structure (BOS, CHoCH), liquidity sweeps, momentum, the
pullback's character, compression and wick pressure. The ticket shows it. A contract whose 15-minute bars show
something against the trade (a pattern against, a big bar against, or a CHoCH against still standing) goes behind the
others. trader/backtest_pa.py on 50 contracts, Nov 2025 to Nov 2026 (results in trader/backtest-pa.txt): that veto
moved the two trades from -0.070R / -0.055R (older / newer days) to -0.053R / -0.022R, still a loss and no better than
two random contracts (-0.046R / -0.031R). Using price action as extra points, extra checks, a must-have trigger,
waiting until 10:30 for a 15-minute trigger, or to choose the side instead of the 4h trend: none better on both
halves, most worse. A 1h pattern for the trade at 09:00 did worse than none: in a 3-hour trade the move is often over.

Direction   4h EMA20 over EMA50: long; under: short
Score       trend      4h structure (HH+HL / LH+LL), close vs EMA50, ADX(14), EMA50 slope, daily trend
            phase      distance to the 4h EMA20 in ATRs: pullback best, stretched and deep lose points
            zones      swings on 1d, 4h and 1h bars, each from the candle's wick to its body; consolidations;
                       round prices; yesterday's and last week's high and low; today's open. Zones within 0.15 ATR(4h)
                       merge. A lone 1h swing or round price does not count. Points for standing at a zone, for a
                       test in the last 8 hours that held, for 3+ touches, for a role change (breakout and retest)
                       and for room: the next zone beyond the 2R target
            fvg        inside an open three-candle fair value gap of the trade's side (4h more than 1h)
            fibonacci  retracement of the last 4h swing: 50-66 % best, 38.2-78.6 % good, past 100 % loses points
            RSI        Wilder RSI(14), used as a pullback gauge and not as a reversal signal. Long: 1h RSI 40-60
                       best, over 70 loses points (too late), under 30 loses points (falling knife), rising
                       over 3 bars and 4h RSI over 50 add points. Short: the mirror
            turn       last 1h bar closed the trade's way and beyond the 1h EMA20; pinbar or engulfing adds points
            volume    last 1h bar at least 1.2x the 20-bar average
            repeat     extra points when the same trade already ranked in the top 5 at an earlier hourly check

Hard rules (a contract that breaks one is out, whatever its score)
  stop       beyond the first zone on the far side that gives 2 % to 4 %, else 1.5 ATR(4h) if that fits;
             under 2 % the fees eat too much (backtest: -0.19R a trade with 0.8 %, -0.10R with 2 %)
  target     2R; at least 1.2R after taker fees in and out and the funding until 12:30 Berlin
  funding    against the trade by more than 0.03 % a period: out
  size       whole contracts, loss at the stop <= the smaller of max_loss_per_trade_usdt and max_loss_pct of
             equity; value <= MAX_VALUE_PCT of equity, so two trades fit the margin
  count      two trades a day in two different contracts, none in a contract already open

Usage: python trader/daily.py [SYM ...] [--avoid ETH,BNB] [--equity USDT] [--snapshot] [--log] [--hours N]
       --hours N: a trade outside the morning window, closed N hours from now (not tested like the morning)
       without symbols: the 30 crypto contracts with the most 24h turnover (at least 20M USDT)
       --snapshot records the ranking of this hour in trader/daily-watch.json and prints no ticket
"""
import argparse
import datetime
import json
import math
import os
import sys
import time
import urllib.request

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "trader-kucoin"))
sys.path.insert(0, os.path.dirname(__file__))
import kucoin as K  # noqa: E402
import price_action as P  # noqa: E402

API = "https://api-futures.kucoin.com"
LOG = "trader/daily-log.json"
WATCH = "trader/daily-watch.json"
BRIEF = "trader/kucoin-brief.json"
TARGET_R, MIN_NET_R = 2.0, 1.2
MIN_STOP, MAX_STOP = 2.0, 4.0
MAX_VALUE_PCT = 45
MAX_TRADES = 2
REPEAT_POINTS = 5
MAX_FUNDING_AGAINST = 0.0003
CLOSE_BERLIN = (12, 30)
MIN_HOURS_LEFT = 2
MIN_TURNOVER = 20e6
TOP = 30
PA_BARS = 120             # 1h and 15-minute bars read by trader/price_action.py
PA_VETO_15M = True        # a contract whose last 15-minute bars show something against the trade goes to the back


# ------------------------------------------------------------------ data

def get(path):
    req = urllib.request.Request(API + path, headers={"User-Agent": "daily.py"})
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                doc = json.load(r)
            return K.payload(doc, path.split("?")[0])
        except Exception:
            if attempt == 2:
                raise
            time.sleep(1.5)


def bars(sym, minutes, n=200):
    """Closed bars as dicts t (UTC), o, h, l, c, v, oldest first."""
    end = int(time.time() * 1000)
    step = minutes * 60000
    raw = get("/api/v1/kline/query?symbol=%s&granularity=%d&from=%d&to=%d" % (sym, minutes, end - n * step, end))
    time.sleep(0.15)
    out = [{"t": K.utc_of_ms(b[0]), "o": float(b[1]), "h": float(b[2]), "l": float(b[3]), "c": float(b[4]),
            "v": float(b[5])} for b in raw if int(b[0]) + step <= end]
    return out


# ------------------------------------------------------------------ indicators

def ema_line(xs, n):
    if len(xs) < n:
        return [None] * len(xs)
    k = 2.0 / (n + 1)
    out = [None] * (n - 1)
    e = sum(xs[:n]) / float(n)
    out.append(e)
    for x in xs[n:]:
        e = x * k + e * (1 - k)
        out.append(e)
    return out


def rsi_line(xs, n=14):
    """Wilder's RSI on closes."""
    if len(xs) <= n:
        return [None] * len(xs)
    moves = [b - a for a, b in zip(xs[:-1], xs[1:])]
    up = sum(max(m, 0) for m in moves[:n]) / float(n)
    dn = sum(max(-m, 0) for m in moves[:n]) / float(n)
    out = [None] * n
    out.append(100.0 if dn == 0 else 100 - 100 / (1 + up / dn))
    for m in moves[n:]:
        up = (up * (n - 1) + max(m, 0)) / n
        dn = (dn * (n - 1) + max(-m, 0)) / n
        out.append(100.0 if dn == 0 else 100 - 100 / (1 + up / dn))
    return out


def true_ranges(b):
    return [max(x["h"] - x["l"], abs(x["h"] - p["c"]), abs(x["l"] - p["c"])) for p, x in zip(b[:-1], b[1:])]


def atr(b, n=14):
    tr = true_ranges(b)
    return sum(tr[-n:]) / float(n)


def adx(b, n=14):
    """Wilder's ADX on the bars."""
    pdm, ndm = [], []
    for p, x in zip(b[:-1], b[1:]):
        up, dn = x["h"] - p["h"], p["l"] - x["l"]
        pdm.append(up if up > dn and up > 0 else 0.0)
        ndm.append(dn if dn > up and dn > 0 else 0.0)
    tr = true_ranges(b)
    if len(tr) < 2 * n:
        return None

    def wilder(xs):
        s = sum(xs[:n])
        out = [s]
        for x in xs[n:]:
            s = s - s / n + x
            out.append(s)
        return out
    trs, ps, ns = wilder(tr), wilder(pdm), wilder(ndm)
    dx = []
    for t, p_, n_ in zip(trs, ps, ns):
        pdi, ndi = 100 * p_ / t if t else 0, 100 * n_ / t if t else 0
        dx.append(100 * abs(pdi - ndi) / (pdi + ndi) if pdi + ndi else 0)
    a = sum(dx[:n]) / n
    for x in dx[n:]:
        a = (a * (n - 1) + x) / n
    return a


def pivots(b, k):
    """Swing highs and lows with k bars on each side: (index, price, 'H' or 'L')."""
    out = []
    for i in range(k, len(b) - k):
        near = b[i - k:i] + b[i + 1:i + 1 + k]
        if b[i]["h"] >= max(x["h"] for x in near):
            out.append((i, b[i]["h"], "H"))
        if b[i]["l"] <= min(x["l"] for x in near):
            out.append((i, b[i]["l"], "L"))
    return out


def fair_value_gaps(b, a, look):
    """Open three-candle gaps of the last look bars. Middle candle's body at least 0.8 ATR (the displacement).
    Bullish: third low over first high. Bearish: third high under first low. Closed through: no longer open."""
    out = []
    for i in range(max(0, len(b) - look), len(b) - 2):
        x, m, y = b[i], b[i + 1], b[i + 2]
        if abs(m["c"] - m["o"]) < 0.8 * a:
            continue
        if y["l"] > x["h"] and m["c"] > m["o"]:
            lo, hi, kind = x["h"], y["l"], "bull"
        elif y["h"] < x["l"] and m["c"] < m["o"]:
            lo, hi, kind = y["h"], x["l"], "bear"
        else:
            continue
        later = b[i + 3:]
        if not any((z["c"] < lo) if kind == "bull" else (z["c"] > hi) for z in later):
            out.append({"low": lo, "high": hi, "kind": kind})
    return out


def in_gap(gaps, recent, px, long_, a):
    """A gap of the trade's side that the last bars reached and the price still holds."""
    for g in gaps:
        if long_ and g["kind"] == "bull" and min(x["l"] for x in recent) <= g["high"] and g["low"] <= px <= g["high"] + 0.5 * a:
            return g
        if not long_ and g["kind"] == "bear" and max(x["h"] for x in recent) >= g["low"] and g["low"] - 0.5 * a <= px <= g["high"]:
            return g
    return None


def fib_ratio(b4, px, long_, a4):
    """How far the price has retraced the last 4h swing of the trend (0.5 = half way), None without a clean swing."""
    piv = pivots(b4, 3)
    tops = [(i, p) for i, p, kind in piv if kind == "H"]
    lows = [(i, p) for i, p, kind in piv if kind == "L"]
    if not tops or not lows:
        return None
    if long_:
        i_hi, hi = tops[-1]
        before = [p for i, p in lows if i < i_hi]
        if not before or hi - before[-1] < 2 * a4:
            return None
        return (hi - px) / (hi - before[-1])
    i_lo, lo = lows[-1]
    before = [p for i, p in tops if i < i_lo]
    if not before or before[-1] - lo < 2 * a4:
        return None
    return (px - lo) / (before[-1] - lo)


def candle_signal(prev, x, long_):
    """Pinbar or engulfing candle the trade's way on the last bar, else None."""
    rng, body = x["h"] - x["l"], abs(x["c"] - x["o"])
    if not rng:
        return None
    if long_:
        wick = min(x["o"], x["c"]) - x["l"]
        if wick >= 2 * body and wick >= 0.5 * rng and x["c"] >= x["l"] + 0.6 * rng:
            return "pinbar"
        if x["c"] > x["o"] and prev["c"] < prev["o"] and x["c"] >= prev["o"] and x["o"] <= prev["c"]:
            return "engulfing"
        return None
    wick = x["h"] - max(x["o"], x["c"])
    if wick >= 2 * body and wick >= 0.5 * rng and x["c"] <= x["h"] - 0.6 * rng:
        return "pinbar"
    if x["c"] < x["o"] and prev["c"] > prev["o"] and x["c"] <= prev["o"] and x["o"] >= prev["c"]:
        return "engulfing"
    return None


# ------------------------------------------------------------------ trend

def structure(b, k=3):
    piv = pivots(b, k)
    hs = [p for _, p, kind in piv if kind == "H"]
    ls = [p for _, p, kind in piv if kind == "L"]
    if len(hs) < 2 or len(ls) < 2:
        return "unclear"
    if hs[-1] > hs[-2] and ls[-1] > ls[-2]:
        return "HH+HL"
    if hs[-1] < hs[-2] and ls[-1] < ls[-2]:
        return "LH+LL"
    return "mixed"


def trend(b4, bd):
    closes = [x["c"] for x in b4]
    e20, e50 = ema_line(closes, 20), ema_line(closes, 50)
    long_ = e20[-1] > e50[-1]
    sign = 1 if long_ else -1
    dist = sign * (closes[-1] - e20[-1]) / atr(b4)
    phase = ("stretched" if dist > 1.5 else "running" if dist > 0.3 else "pullback" if dist >= -1.0 else "deep")
    dcl = [x["c"] for x in bd]
    d20 = ema_line(dcl, 20)
    dslope = d20[-1] - d20[-6]
    day = ("up" if dcl[-1] > d20[-1] and dslope > 0 else "down" if dcl[-1] < d20[-1] and dslope < 0 else "neutral")
    return {"direction": "up" if long_ else "down", "structure": structure(b4), "adx": adx(b4), "ema20": e20[-1],
            "ema50": e50[-1], "close": closes[-1], "slope50": (e50[-1] / e50[-11] - 1) * 100, "atr": atr(b4),
            "dist": dist, "phase": phase, "day": day}


# ------------------------------------------------------------------ support and resistance

def swing_zones(b, k, kind, a4):
    """Each swing as a zone from the candle's wick to its body, at most 0.5 ATR(4h) wide."""
    out = []
    for i, _, side in pivots(b, k):
        x = b[i]
        if side == "H":
            out.append((max(max(x["o"], x["c"]), x["h"] - 0.5 * a4), x["h"], kind))
        else:
            out.append((x["l"], min(min(x["o"], x["c"]), x["l"] + 0.5 * a4), kind))
    return out


def consolidations(b1, a1):
    """Stretches of 8 hours or more inside a range of at most 1.5 ATR(1h)."""
    out, i = [], 0
    while i + 8 <= len(b1):
        win = b1[i:i + 8]
        hi, lo = max(x["h"] for x in win), min(x["l"] for x in win)
        if hi - lo <= 1.5 * a1:
            out.append((lo, hi, "range"))
            i += 8
        else:
            i += 1
    return out


def round_levels(px, a4):
    """Round prices within 4 ATR(4h): multiples of half the leading digit's size, like 95, 100 or 1.0, 1.5."""
    step = 10 ** math.floor(math.log10(px)) / 2.0
    n = math.floor((px - 4 * a4) / step)
    out = []
    while n * step <= px + 4 * a4:
        if n > 0:
            out.append((n * step, n * step, "round"))
        n += 1
    return out


def zones(b4, b1, bd, a4, now):
    px = b1[-1]["c"]
    cands = swing_zones(bd, 2, "1d swing", a4) + swing_zones(b4, 3, "4h swing", a4) + swing_zones(b1, 4, "1h swing", a4)
    cands += consolidations(b1, atr(b1)) + round_levels(px, a4)
    today = now.date()
    done = [x for x in bd if x["t"].date() < today]
    if done:
        cands += [(done[-1]["h"], done[-1]["h"], "yesterday high"), (done[-1]["l"], done[-1]["l"], "yesterday low")]
        week = done[-7:]
        hi, lo = max(x["h"] for x in week), min(x["l"] for x in week)
        cands += [(hi, hi, "week high"), (lo, lo, "week low")]
    opens = [x for x in b1 if x["t"].date() == today]
    if opens:
        cands.append((opens[0]["o"], opens[0]["o"], "day open"))
    gap = 0.15 * a4
    groups, cur, top = [], [], None
    for lo, hi, kind in sorted(cands):
        if cur and (lo - top > gap or max(top, hi) - cur[0][0] > a4):
            groups.append(cur)
            cur, top = [], None
        cur.append((lo, hi, kind))
        top = hi if top is None else max(top, hi)
    if cur:
        groups.append(cur)
    out = []
    for g in groups:
        kinds = [k for _, _, k in g]
        if len(g) < 2 and kinds[0] in ("1h swing", "round"):
            continue                                  # one 1h turn or a round number alone is noise
        out.append({"low": min(x[0] for x in g), "high": max(x[1] for x in g), "touches": len(g),
                    "kinds": sorted(set(kinds))})
    return out


def ztext(z, tick):
    lo, hi = K.fmt(z["low"], tick), K.fmt(z["high"], tick)
    return "%s (%s, %dx)" % (lo if lo == hi else lo + "-" + hi, "/".join(z["kinds"]), z["touches"])


# ------------------------------------------------------------------ the score

def rate(b4, b1, bd, now, tick, use_rsi=True, side=None):
    """Side, stop, target and score from closed bars alone; verdict 'stop' when no stop fits 2 to 4 %.
    side 'long' or 'short' rates that side even against the 4h trend (for the backtests)."""
    tr = trend(b4, bd)
    long_ = tr["direction"] == "up" if side is None else side == "long"
    a4, a1 = tr["atr"], atr(b1)
    closes1 = [x["c"] for x in b1]
    last, px = b1[-1], closes1[-1]
    zs = zones(b4, b1, bd, a4, now)
    sign = 1 if long_ else -1
    parts = {}

    # zone behind the entry: the stop goes beyond it; zone ahead: the room
    behind = sorted([z for z in zs if (z["low"] <= px if long_ else z["high"] >= px)],
                    key=lambda z: -z["high"] if long_ else z["low"])
    ahead = sorted([z for z in zs if (z["low"] > px if long_ else z["high"] < px)],
                   key=lambda z: z["low"] if long_ else -z["high"])
    zone, stop = None, None
    for z in behind:
        cand = K.round_away(z["low"] - 0.25 * a4, tick, down=True) if long_ else K.round_away(z["high"] + 0.25 * a4, tick, down=False)
        pct = abs(px - cand) / px * 100
        if MIN_STOP <= pct <= MAX_STOP:
            zone, stop = z, cand
            break
        if pct > MAX_STOP:
            break
    if stop is None:
        cand = K.round_away(px - sign * 1.5 * a4, tick, down=long_)
        if not MIN_STOP <= abs(px - cand) / px * 100 <= MAX_STOP:
            return {"verdict": "stop", "why": "no stop fits %.1f-%.0f %%" % (MIN_STOP, MAX_STOP), "trend": tr}
        stop = cand
    risk = abs(px - stop)
    target = K.round_away(px + sign * TARGET_R * risk, tick, down=long_)
    pct = risk / px * 100

    # trend
    want = "HH+HL" if long_ else "LH+LL"
    against = "LH+LL" if long_ else "HH+HL"
    parts["structure"] = 20 if tr["structure"] == want else -10 if tr["structure"] == against else 5
    parts["ema50"] = 10 if sign * (tr["close"] - tr["ema50"]) > 0 else 0
    strength = tr["adx"] or 0
    parts["adx"] = 15 if strength >= 25 else 10 if strength >= 20 else 0
    parts["slope"] = 5 if sign * tr["slope50"] > 0 else 0
    parts["day"] = 10 if tr["day"] == ("up" if long_ else "down") else 3 if tr["day"] == "neutral" else -15
    parts["phase"] = {"pullback": 15, "running": 5, "stretched": -15, "deep": -10}[tr["phase"]]

    # support and resistance
    near = behind[0] if behind else None
    recent = b1[-8:]
    if near is not None:
        edge = near["high"] if long_ else near["low"]
        if abs(px - edge) <= 0.6 * a4:
            parts["at_zone"] = 10
        if long_:
            tested = min(x["l"] for x in recent) <= near["high"] + 0.1 * a1
            held = min(x["c"] for x in recent) >= near["low"]
        else:
            tested = max(x["h"] for x in recent) >= near["low"] - 0.1 * a1
            held = max(x["c"] for x in recent) <= near["high"]
        if tested and held:
            parts["tested"] = 10
        if near["touches"] >= 3:
            parts["strong_zone"] = 5
        # role change: this zone stood on the other side of the price within the last 24 hours (breakout and retest)
        if long_ and any(x["c"] < near["low"] for x in b1[-24:]) or not long_ and any(x["c"] > near["high"] for x in b1[-24:]):
            if tested and held:
                parts["flip"] = 10
    other = ahead[0] if ahead else None
    room = (abs((other["low"] if long_ else other["high"]) - px) / risk) if other else 5.0
    parts["room"] = 10 if room >= TARGET_R else 3 if room >= 1 else -10

    # RSI, as a pullback gauge in the trend's direction
    r1 = rsi_line(closes1)
    r4 = rsi_line([x["c"] for x in b4])
    rsi1 = r1[-1] if long_ else 100 - r1[-1]           # mirrored for shorts: high means stretched the trade's way
    rsi4 = r4[-1] if long_ else 100 - r4[-1]
    if use_rsi:
        parts["rsi1"] = (10 if 40 <= rsi1 <= 60 else 5 if 30 <= rsi1 < 40 else 0 if 60 < rsi1 <= 70
                         else -15 if rsi1 > 70 else -5)
        if sign * (r1[-1] - r1[-4]) > 0:
            parts["rsi_turn"] = 5
        parts["rsi4"] = 5 if rsi4 >= 50 else -5 if rsi4 < 40 else 0

    # turn and volume
    e20_1 = ema_line(closes1, 20)[-1]
    if sign * (last["c"] - last["o"]) > 0 and sign * (last["c"] - e20_1) > 0:
        parts["turn"] = 10
    avg_v = sum(x["v"] for x in b1[-21:-1]) / 20.0
    if avg_v and last["v"] >= 1.2 * avg_v:
        parts["volume"] = 5
    signal = candle_signal(b1[-2], last, long_)
    if signal:
        parts["candle"] = 10

    # fair value gaps and Fibonacci
    recent3 = b1[-3:]
    gap4 = in_gap(fair_value_gaps(b4, a4, 30), recent3, px, long_, a1)
    gap1 = in_gap(fair_value_gaps(b1, a1, 48), recent3, px, long_, a1)
    if gap4:
        parts["fvg4"] = 15
    if gap1:
        parts["fvg1"] = 10
    fib = fib_ratio(b4, px, long_, a4)
    if fib is not None:
        parts["fib"] = 15 if 0.5 <= fib <= 0.66 else 8 if 0.382 <= fib <= 0.786 else -5 if fib > 1 else 0

    checks = {"trend": tr["structure"] == want and parts["ema50"] > 0 and parts["adx"] >= 10 and parts["day"] >= 3,
              "zone": "at_zone" in parts and "tested" in parts,
              "rsi": 30 <= rsi1 <= 60,
              "candle": "candle" in parts or "turn" in parts,
              "fvg": bool(gap4 or gap1),
              "fib": parts.get("fib", 0) >= 8,
              "room": room >= TARGET_R}
    return {"verdict": "ok", "why": "", "side": "long" if long_ else "short", "trend": tr, "price": px, "stop": stop,
            "target": target, "stop_pct": pct, "risk": risk, "zone": zone, "next_zone": other, "room": room,
            "rsi1": r1[-1], "rsi4": r4[-1], "fib": fib, "fvg": gap4 or gap1, "signal": signal, "parts": parts,
            "checks": checks, "met": sum(checks.values()), "score": sum(parts.values())}


# ------------------------------------------------------------------ money

def berlin_close(now):
    """Today's closing time, Berlin, in UTC."""
    off = K.berlin(now) - now
    local = K.berlin(now).replace(hour=CLOSE_BERLIN[0], minute=CLOSE_BERLIN[1], second=0, microsecond=0)
    return local - off


def evaluate(c, equity, cfg, now, close_by):
    sym = c["symbol"]
    tick, mult = float(c["tickSize"]), float(c["multiplier"])
    fee = float(c.get("takerFeeRate") or 0.0006)
    b4, b1, bd = bars(sym, 240), bars(sym, 60), bars(sym, 1440, 60)
    if len(b4) < 80 or len(b1) < 60 or len(bd) < 26:
        return {"symbol": sym, "verdict": "no-data", "why": "too few bars (new contract?)"}
    res = dict(rate(b4, b1, bd, now, tick), symbol=sym, tick=tick)
    if res["verdict"] != "ok":
        return res
    side_long = res["side"] == "long"
    res["pa1"] = P.read(b1[-PA_BARS:], side_long)
    res["pa15"] = P.read(bars(sym, 15, PA_BARS), side_long)

    def no(verdict, why):
        return dict(res, verdict=verdict, why=why)
    long_ = res["side"] == "long"
    px, stop, target, risk = res["price"], res["stop"], res["target"], res["risk"]
    fr = get("/api/v1/funding-rate/%s/current" % sym)
    rate_now = float(fr.get("value") or 0)
    against = rate_now if long_ else -rate_now                      # > 0: this side pays
    if against > MAX_FUNDING_AGAINST:
        return no("funding", "funding %+.3f %% a period against the trade" % (rate_now * 100))
    interval = int(fr.get("granularity") or 28800000) / 1000.0
    nxt = K.utc_of_ms(fr["fundingTime"])
    n_fund = 0 if nxt > close_by else int((close_by - nxt).total_seconds() // interval) + 1
    fund_unit = n_fund * max(against, 0.0001) * px * mult
    per_lot_loss = risk * mult + (px + stop) * mult * fee + fund_unit
    per_lot_win = abs(target - px) * mult - (px + target) * mult * fee - fund_unit
    budget = min(float(cfg["max_loss_per_trade_usdt"]), equity * float(cfg["max_loss_pct"]) / 100)
    cap_pct = min(float(cfg["max_position_pct"]), MAX_VALUE_PCT)
    lots = min(int(math.floor(budget / per_lot_loss + 1e-9)),
               int(math.floor(equity * cap_pct / 100 / (px * mult) + 1e-9)))
    net_r = per_lot_win / per_lot_loss
    res.update(lots=lots, multiplier=mult, max_loss=lots * per_lot_loss, win=lots * per_lot_win, net_r=net_r,
               value=lots * mult * px, fundings=n_fund, funding=rate_now)
    if lots < 1:
        return no("size", "one contract loses %.2f USDT at the stop, over %.2f" % (per_lot_loss, budget))
    if net_r < MIN_NET_R:
        return no("net-r", "%.2fR after fees and funding, under %.1fR" % (net_r, MIN_NET_R))
    return res


# ------------------------------------------------------------------ main

def universe(avoid):
    rows = get("/api/v1/contracts/active")
    rows = [c for c in rows if c["symbol"].endswith("USDTM") and (c.get("assetClass") or "CRYPTO") == "CRYPTO"
            and c.get("status") == "Open" and float(c.get("turnoverOf24h") or 0) >= MIN_TURNOVER
            and K.base_of(c["symbol"]) not in avoid]
    return sorted(rows, key=lambda c: -float(c.get("turnoverOf24h") or 0))[:TOP]


def ticket(n, b):
    tr, t = b["trend"], b["tick"]
    print("\nDAILY TICKET %d  %s %s, %d contracts (= %g %s), market, isolated 1x, %d of %d checks, %d points" % (
        n, b["side"].upper(), b["symbol"], b["lots"], b["lots"] * b["multiplier"], K.base_of(b["symbol"]), b["met"],
        len(b["checks"]), b["total"]))
    print("  met: %s; missing: %s" % (", ".join(k for k, v in b["checks"].items() if v) or "none",
                                     ", ".join(k for k, v in b["checks"].items() if not v) or "none"))
    if b["fib"] is not None or b["fvg"] or b["signal"]:
        print("  Fibonacci %s, fair value gap %s, candle %s" % (
            "%.1f %%" % (b["fib"] * 100) if b["fib"] is not None else "no swing",
            "%s-%s" % (K.fmt(b["fvg"]["low"], t), K.fmt(b["fvg"]["high"], t)) if b["fvg"] else "none",
            b["signal"] or "none"))
    print("  trend: 4h %s (%s), ADX %.0f, EMA50 %+.2f %% over 40h, day bars %s, phase %s (%.1f ATR from EMA20)" % (
        tr["direction"], tr["structure"], tr["adx"] or 0, tr["slope50"], tr["day"], tr["phase"], tr["dist"]))
    print("  RSI 14: 1h %.0f, 4h %.0f" % (b["rsi1"], b["rsi4"]))
    for tf, pa in (("1h", b["pa1"]), ("15m", b["pa15"])):
        print("  price action %-3s %s; for: %s; against: %s" % (
            tf, ", ".join(pa["seen"]) or "nothing", ", ".join(pa["trigger"]) or "none", ", ".join(pa["against"]) or "none"))
    if b["zone"]:
        print("  %s behind the stop: %s" % ("support" if b["side"] == "long" else "resistance", ztext(b["zone"], t)))
    if b["next_zone"]:
        print("  next %s: %s, %.1fR away" % ("resistance" if b["side"] == "long" else "support",
                                            ztext(b["next_zone"], t), b["room"]))
    print("  entry about %s, value %.2f USDT" % (K.fmt(b["price"], t), b["value"]))
    print("  stop-loss %s (%.2f %%), take-profit %s (2R), both on the last price" % (
        K.fmt(b["stop"], t), b["stop_pct"], K.fmt(b["target"], t)))
    print("  max loss %.2f USDT, at the target +%.2f USDT (%.2fR net, fees and %d fundings in)" % (
        b["max_loss"], b["win"], b["net_r"], b["fundings"]))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("symbols", nargs="*")
    ap.add_argument("--avoid", default="")
    ap.add_argument("--equity", type=float)
    ap.add_argument("--config", default="trader/kucoin.json")
    ap.add_argument("--snapshot", action="store_true", help="record this hour's ranking, print no ticket")
    ap.add_argument("--log", action="store_true", help="record the tickets as today's trades")
    ap.add_argument("--hours", type=float, help="close this many hours from now instead of at 12:30 Berlin")
    a = ap.parse_args()
    cfg = K.read_config(a.config)
    now = K.utc_now()
    close_by = now + datetime.timedelta(hours=a.hours) if a.hours else berlin_close(now)
    day = K.berlin(now).strftime("%Y-%m-%d")
    log = K.read_json(LOG, []) or []
    taken = [x for x in log if x.get("day") == day]
    if len(taken) >= MAX_TRADES and not a.snapshot:
        print("Today's %d trades are already logged (%s)." % (MAX_TRADES, day))
        return 1
    hours = (close_by - now).total_seconds() / 3600
    if hours < MIN_HOURS_LEFT:
        print("Only %.1f hours to %02d:%02d Berlin: too late for today's trades." % ((hours,) + CLOSE_BERLIN))
        return 1
    avoid = {s.strip().upper() for s in a.avoid.split(",") if s.strip()}
    brief = K.read_json(BRIEF, {}) or {}
    if brief.get("date") == now.strftime("%Y-%m-%d"):
        avoid |= {s.upper() for s in brief.get("avoid") or []}
    equity = a.equity
    if equity is None:
        acct = K.private("GET", "/api/v1/account-overview?currency=USDT") or {}
        equity = float(acct.get("accountEquity") or 0)
    held = {p.get("symbol") for p in K.private("GET", "/api/v1/positions") or []}
    if a.symbols:
        every = {c["symbol"]: c for c in get("/api/v1/contracts/active")}
        cs = [every[K.symbol_of(s)] for s in a.symbols if K.symbol_of(s) in every]
    else:
        cs = universe(avoid)
    print("Daily check %s Berlin, equity %.2f USDT, close by %s Berlin, avoid: %s" % (
        K.berlin(now).strftime("%a %d.%m. %H:%M"), equity, K.berlin(close_by).strftime("%H:%M"),
        ", ".join(sorted(avoid)) or "none"))
    rows = []
    for c in cs:
        try:
            rows.append(evaluate(c, equity, cfg, now, close_by))
        except Exception as e:
            rows.append({"symbol": c["symbol"], "verdict": "error", "why": str(e)[:100]})
    watch = K.read_json(WATCH, {}) or {}
    earlier = (watch.get(day) or {}).values() if isinstance(watch.get(day), dict) else []
    ok = [r for r in rows if r["verdict"] == "ok" and r["symbol"] not in held
          and r["symbol"] not in {x["symbol"] for x in taken}]
    for r in ok:
        key = "%s %s" % (r["symbol"], r["side"])
        r["total"] = r["score"] + REPEAT_POINTS * sum(1 for hour in earlier if key in hour)
    ok.sort(key=lambda r: (PA_VETO_15M and bool(r["pa15"]["against"]), -r["met"], -r["total"]))
    for r in sorted(rows, key=lambda r: (-r.get("met", -1), -(r.get("total") or r.get("score") or -99))):
        tr = r.get("trend") or {}
        desc = "%-5s %-6s ADX %2.0f day %-7s %-9s" % (tr.get("direction", ""), tr.get("structure", ""),
                                                     tr.get("adx") or 0, tr.get("day", ""), tr.get("phase", "")) if tr else ""
        info = r["why"] or "%s %d/7, %3d points, RSI 1h %.0f, net %.2fR, stop %.2f %%, 15m PA %s" % (
            r["side"], r["met"], r.get("total", r["score"]), r["rsi1"], r["net_r"], r["stop_pct"],
            "against" if r["pa15"]["against"] else "trigger" if r["pa15"]["check"] else "-")
        print("  %-12s %s %-8s %s" % (r["symbol"], desc, r["verdict"], info))
    if a.snapshot:
        hour = K.berlin(now).strftime("%H:00")
        watch = {day: dict(watch.get(day) or {}, **{hour: ["%s %s" % (r["symbol"], r["side"]) for r in ok[:5]]})}
        K.write_json(WATCH, watch)
        print("\nSnapshot %s: %s" % (hour, ", ".join(watch[day][hour]) or "none"))
        return 0
    picks = ok[:MAX_TRADES - len(taken)]
    if not picks:
        print("\nNo contract passes the hard rules today. No trade.")
        return 1
    for n, b in enumerate(picks, len(taken) + 1):
        ticket(n, b)
    print("\n  close by %s Berlin" % K.berlin(close_by).strftime("%H:%M"))
    if a.log:
        for b in picks:
            log.append({"day": day, "logged_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"), "close_by":
                        close_by.strftime("%Y-%m-%dT%H:%M:%SZ"), "points": b["total"], **{k: b[k] for k in (
                            "symbol", "side", "price", "stop", "target", "lots", "max_loss")}})
        K.write_json(LOG, log)
        print("Logged %d trade(s) for today." % len(picks))
    return 0


if __name__ == "__main__":
    sys.exit(main())
