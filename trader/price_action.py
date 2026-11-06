"""Price action: what each candle, the last few candles and the swings say, read from one side (long or short).
Bars are dicts with o, h, l, c (v optional), oldest first, closed bars only. Uses nothing but the bars. Sends nothing.

Single candle   body, upper and lower wick as shares of the range, size in ATRs, where it closed (0 low, 1 high);
                shapes: doji, spinning top, marubozu, hammer / pinbar, shooting star, big bar
Patterns        ending on the last bar or the bar before, for and against the trade:
                pinbar (rejection wick), engulfing, outside-bar reversal, morning / evening star, piercing / dark
                cloud, tweezer bottom / top, inside-bar breakout, three soldiers / crows, strong close (marubozu)
Structure       swings with k bars each side; a close beyond the last swing high or low is a break of structure:
                BOS when it goes with the bias so far, CHoCH (change of character) when it turns it
Liquidity       sweep: a recent bar ran beyond a swing of the last day (where stops sit) and closed back inside
Momentum        how many of the last bars closed the trade's way; a big bar against the trade that closed near its
                extreme (someone sold or bought hard)
Pullback        since the last extreme: small, overlapping bars (corrective, the trend rests) or big bars (impulsive,
                maybe a turn)
Compression     NR7 (narrowest range of 7) and inside bars: energy before a move
Wick pressure   lower wicks against upper wicks over the last 10 bars: who keeps pushing price back

read() puts it together for one side: what was seen, points, and the check: a trigger for the trade (pattern, sweep
or a break of structure its way in the last 3 bars) and nothing strong against it.
"""


def _atr(b, n=14):
    tr = [max(x["h"] - x["l"], abs(x["h"] - p["c"]), abs(x["l"] - p["c"])) for p, x in zip(b[:-1], b[1:])]
    tr = tr[-n:]
    return sum(tr) / len(tr) if tr else 0.0


def anatomy(x, a):
    """Shares of the range: body, upper wick, lower wick; size in ATRs; close location (0 = low, 1 = high)."""
    rng = x["h"] - x["l"]
    if rng <= 0:
        return {"range": 0.0, "size": 0.0, "body": 0.0, "up": 0.0, "dn": 0.0, "clv": 0.5, "dir": 0}
    return {"range": rng, "size": rng / a if a else 0.0, "body": abs(x["c"] - x["o"]) / rng,
            "up": (x["h"] - max(x["o"], x["c"])) / rng, "dn": (min(x["o"], x["c"]) - x["l"]) / rng,
            "clv": (x["c"] - x["l"]) / rng, "dir": (x["c"] > x["o"]) - (x["c"] < x["o"])}


def shape(x, a):
    """The candle's shape alone, without context."""
    s = anatomy(x, a)
    if not s["range"]:
        return "flat"
    if s["body"] <= 0.1:
        return "doji"
    if s["dn"] >= 0.5 and s["dn"] >= 2 * s["body"] and s["clv"] >= 0.6:
        return "hammer"
    if s["up"] >= 0.5 and s["up"] >= 2 * s["body"] and s["clv"] <= 0.4:
        return "shooting star"
    if s["body"] >= 0.8 and s["size"] >= 1.0:
        return "marubozu up" if s["dir"] > 0 else "marubozu down"
    if s["body"] <= 0.3:
        return "spinning top"
    if s["size"] >= 1.5:
        return "big bar up" if s["dir"] > 0 else "big bar down"
    return "bar up" if s["dir"] > 0 else "bar down"


def _flip(x):
    """Mirror a bar so short patterns can be found with the long rules."""
    return {"o": -x["o"], "h": -x["l"], "l": -x["h"], "c": -x["c"], "v": x.get("v", 0)}


def _bull_patterns(b, a):
    """Bullish patterns ending on the last bar: (name, strength 2 strong / 1 medium)."""
    out = []
    if len(b) < 4 or not a:
        return out
    x, p, q = b[-1], b[-2], b[-3]
    s, sp, sq = anatomy(x, a), anatomy(p, a), anatomy(q, a)
    lowest = min(y["l"] for y in b[-6:-1])
    if s["dn"] >= 0.5 and s["dn"] >= 2 * s["body"] and s["clv"] >= 0.6 and x["l"] <= lowest:
        out.append(("pinbar", 2))
    if s["dir"] > 0 and sp["dir"] < 0 and x["c"] >= p["o"] and x["o"] <= p["c"] and s["body"] >= 0.5:
        out.append(("engulfing", 2))
    if x["h"] > p["h"] and x["l"] < p["l"] and s["clv"] >= 0.75 and s["dir"] > 0:
        out.append(("outside reversal", 2))
    if (sq["dir"] < 0 and sq["body"] >= 0.5 and sp["body"] <= 0.35 and s["dir"] > 0
            and x["c"] >= (q["o"] + q["c"]) / 2 and max(p["o"], p["c"]) <= q["o"]):
        out.append(("morning star", 2))
    if (sp["dir"] < 0 and sp["body"] >= 0.5 and s["dir"] > 0 and x["o"] <= p["c"]
            and (p["o"] + p["c"]) / 2 <= x["c"] < p["o"]):
        out.append(("piercing", 1))
    if abs(x["l"] - p["l"]) <= 0.1 * a and sp["dir"] < 0 and s["dir"] > 0 and x["l"] <= lowest + 0.1 * a:
        out.append(("tweezer bottom", 1))
    if p["h"] <= q["h"] and p["l"] >= q["l"] and x["c"] > q["h"]:
        out.append(("inside-bar breakout", 1))
    if (all(anatomy(y, a)["dir"] > 0 and anatomy(y, a)["body"] >= 0.5 and anatomy(y, a)["clv"] >= 0.7 for y in (q, p, x))
            and q["c"] < p["c"] < x["c"]):
        out.append(("three soldiers", 1))
    if s["dir"] > 0 and s["body"] >= 0.8 and s["size"] >= 1.0:
        out.append(("strong close", 1))
    return out


def patterns(b, a, long_):
    """Patterns on the last bar for the trade and against it, as lists of (name, strength)."""
    up = _bull_patterns(b, a)
    down = _bull_patterns([_flip(x) for x in b], a)
    names = {"pinbar": "pinbar", "engulfing": "engulfing", "outside reversal": "outside reversal",
             "morning star": "evening star", "piercing": "dark cloud", "tweezer bottom": "tweezer top",
             "inside-bar breakout": "inside-bar breakdown", "three soldiers": "three crows", "strong close": "strong close"}
    down = [(names[n], s) for n, s in down]
    return (up, down) if long_ else (down, up)


def pivots(b, k):
    out = []
    for i in range(k, len(b) - k):
        near = b[i - k:i] + b[i + 1:i + 1 + k]
        if b[i]["h"] >= max(x["h"] for x in near):
            out.append((i, b[i]["h"], "H"))
        if b[i]["l"] <= min(x["l"] for x in near):
            out.append((i, b[i]["l"], "L"))
    return out


def structure(b, k=2):
    """Breaks of structure on closes. A swing counts once it is confirmed (k bars later). Returns the bias, the
    events (index, 'BOS up' / 'CHoCH up' / 'BOS down' / 'CHoCH down', level) and the last swing high and low."""
    piv = sorted(pivots(b, k))
    hi = lo = None
    bias, events, j = None, [], 0
    for i, x in enumerate(b):
        while j < len(piv) and piv[j][0] + k < i:
            idx, price, kind = piv[j]
            if kind == "H":
                hi = [price, False]
            else:
                lo = [price, False]
            j += 1
        if hi and not hi[1] and x["c"] > hi[0]:
            events.append((i, "CHoCH up" if bias == "down" else "BOS up", hi[0]))
            bias, hi[1] = "up", True
        if lo and not lo[1] and x["c"] < lo[0]:
            events.append((i, "CHoCH down" if bias == "up" else "BOS down", lo[0]))
            bias, lo[1] = "down", True
    return {"bias": bias, "events": events, "high": hi[0] if hi else None, "low": lo[0] if lo else None}


def sweep(b, a, long_, look=24, recent=3):
    """Long: one of the last `recent` bars ran under a swing low of the bars before (at most 1 ATR deep) and closed
    back above it; short: the mirror. Returns (level, bars ago) or None."""
    n = len(b)
    if n < look + recent:
        return None
    lows = [(i, p) for i, p, kind in pivots(b[n - look - recent:n - recent], 2) if kind == ("L" if long_ else "H")]
    if not lows:
        return None
    for back in range(1, recent + 1):
        x = b[n - back]
        for _, level in lows:
            if long_ and x["l"] < level <= x["c"] and level - x["l"] <= a and b[-1]["c"] > level:
                return level, back - 1
            if not long_ and x["h"] > level >= x["c"] and x["h"] - level <= a and b[-1]["c"] < level:
                return level, back - 1
    return None


def momentum(b, a, long_, n=6):
    """Bars closing the trade's way among the last n, and the strongest bar against in the last 3."""
    sign = 1 if long_ else -1
    last = b[-n:]
    with_ = sum(1 for x in last if sign * (x["c"] - x["o"]) > 0)
    hard = None
    for x in b[-3:]:
        s = anatomy(x, a)
        clv = s["clv"] if long_ else 1 - s["clv"]
        if sign * (x["c"] - x["o"]) < 0 and s["body"] >= 0.6 and s["size"] >= 1.2 and clv <= 0.25:
            hard = x
    return with_, hard


def pullback(b, a, long_, look=30):
    """Since the last extreme of the trade's side: 'corrective' (bars at most 0.75x the size of the move into the
    extreme), 'impulsive' (bigger) or None when there is no pullback yet."""
    seg = b[-look:]
    if long_:
        m = max(range(len(seg)), key=lambda i: seg[i]["h"])
        s = min(range(max(0, m - 20), m + 1), key=lambda i: seg[i]["l"]) if m else 0
    else:
        m = min(range(len(seg)), key=lambda i: seg[i]["l"])
        s = max(range(max(0, m - 20), m + 1), key=lambda i: seg[i]["h"]) if m else 0
    back, move = seg[m + 1:], seg[s:m + 1]
    if len(back) < 2 or len(move) < 2:
        return None
    rb = sum(x["h"] - x["l"] for x in back) / len(back)
    rm = sum(x["h"] - x["l"] for x in move) / len(move)
    if not rm:
        return None
    return "corrective" if rb <= 0.75 * rm else "impulsive" if rb > rm else "even"


def compression(b):
    """NR7 on the last bar and inside bars among the last 3."""
    rngs = [x["h"] - x["l"] for x in b[-7:]]
    nr7 = len(rngs) == 7 and rngs[-1] == min(rngs)
    inside = sum(1 for p, x in zip(b[-4:-1], b[-3:]) if x["h"] <= p["h"] and x["l"] >= p["l"])
    return nr7, inside


def wick_pressure(b, long_, n=10):
    """(lower wicks - upper wicks) / ranges over n bars, from the trade's side: over 0 means price keeps being pushed
    the trade's way."""
    up = dn = rng = 0.0
    for x in b[-n:]:
        up += x["h"] - max(x["o"], x["c"])
        dn += min(x["o"], x["c"]) - x["l"]
        rng += x["h"] - x["l"]
    if not rng:
        return 0.0
    v = (dn - up) / rng
    return v if long_ else -v


def read(b, long_, a=None):
    """Everything above for one side. Returns seen (list of words), parts (points), check (bool) and details."""
    a = a or _atr(b)
    if len(b) < 40 or not a:
        return {"seen": [], "parts": {}, "points": 0, "check": False, "trigger": [], "against": []}
    side = "up" if long_ else "down"
    other = "down" if long_ else "up"
    parts, seen = {}, []
    pro, con = patterns(b, a, long_)
    # a pattern on the bar before still counts when the last bar did not undo it
    pro_prev, con_prev = patterns(b[:-1], a, long_)
    sign = 1 if long_ else -1
    if sign * (b[-1]["c"] - b[-2]["c"]) >= 0:
        pro += [(n + " (bar before)", s) for n, s in pro_prev if n not in [m for m, _ in pro]]
    else:
        con += [(n + " (bar before)", s) for n, s in con_prev if n not in [m for m, _ in con]]
    if pro:
        parts["pattern"] = min(15, sum(10 if s == 2 else 5 for _, s in pro))
    if con:
        parts["pattern_against"] = -min(15, sum(10 if s == 2 else 5 for _, s in con))
    seen += [n for n, _ in pro] + ["against: " + n for n, _ in con]

    st = structure(b)
    n = len(b)
    recent_ev = [(n - 1 - i, name) for i, name, _ in st["events"] if n - 1 - i <= 12]
    trig_struct = [name for ago, name in recent_ev if ago <= 2 and name.endswith(side)]
    if any(ago <= 6 and name == "CHoCH " + side for ago, name in recent_ev):
        parts["choch"] = 10
    elif any(ago <= 6 and name == "BOS " + side for ago, name in recent_ev):
        parts["bos"] = 5
    # only while the structure still points against the trade: a later break its way cancels it
    turned = st["bias"] == other
    choch_against = turned and any(name == "CHoCH " + other for ago, name in recent_ev)
    bos_against = turned and any(ago <= 6 and name == "BOS " + other for ago, name in recent_ev)
    if choch_against:
        parts["choch_against"] = -15
    elif bos_against:
        parts["bos_against"] = -10
    seen += ["%s %d bars ago" % (name, ago) for ago, name in recent_ev[-3:]]

    sw = sweep(b, a, long_)
    if sw:
        parts["sweep"] = 10
        seen.append("liquidity sweep of %.6g, reclaimed" % sw[0])

    with_, hard = momentum(b, a, long_)
    if hard is not None:
        parts["hard_against"] = -10
        seen.append("big bar against the trade")
    if with_ >= 4:
        parts["momentum"] = 3

    pb = pullback(b, a, long_)
    if pb == "corrective":
        parts["pullback"] = 5
    elif pb == "impulsive":
        parts["pullback"] = -5
    if pb:
        seen.append(pb + " pullback")

    nr7, inside = compression(b)
    if nr7 or inside:
        seen.append("compression" + (" NR7" if nr7 else "") + (" %d inside" % inside if inside else ""))

    wp = wick_pressure(b, long_)
    if wp >= 0.1:
        parts["wicks"] = 3
        seen.append("wicks push the trade's way")
    elif wp <= -0.1:
        parts["wicks"] = -3
        seen.append("wicks push against")

    trigger = [nm for nm, _ in pro] + (["sweep"] if sw else []) + trig_struct
    against = [nm for nm, _ in con] + (["hard bar"] if hard is not None else []) + (["CHoCH against"] if choch_against else [])
    return {"seen": [shape(b[-1], a)] + seen, "parts": parts, "points": sum(parts.values()),
            "check": bool(trigger) and not against, "trigger": trigger, "against": against,
            "structure": st["bias"], "pullback": pb}
