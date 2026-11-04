"""Weekend swing trade on KuCoin Futures: one trade, Friday to Monday 22:00 Berlin, 1x. Sends nothing.

Rules, on closed 4-hour bars:
  Trend    long: close > EMA50 and EMA20 > EMA50; short: close < EMA50 and EMA20 < EMA50
  Entry    not stretched: price within 1 ATR(14) of the EMA20 (a pullback, not a chase)
  Stop     beyond the extreme of the last 12 bars (2 days) plus 0.5 ATR, 2 % to 8 % away
  Target   2R; at least 1.2R after taker fees in and out and the funding until the time stop
  Size     whole contracts, loss at the stop (fees and funding in) <= the smaller of
           max_loss_per_trade_usdt and max_loss_pct of equity; value <= max_position_pct of equity
  Count    MAX_TRADES weekend trades, never twice in one contract: from trader/weekend-log.json
Usage: python trader/weekend.py SOL XRP ZEC ...   [--equity USDT] [--log]
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
import kucoin as K  # noqa: E402

API = "https://api-futures.kucoin.com"
BAR_MS = 4 * 3600 * 1000
TARGET_R, MIN_NET_R = 2.0, 1.2
MIN_STOP, MAX_STOP = 2.0, 8.0            # stop distance in %
SWING_BARS, ATR_BARS = 12, 14
LOG = "trader/weekend-log.json"
MAX_TRADES = 2


def get(path):
    with urllib.request.urlopen(urllib.request.Request(API + path, headers={"User-Agent": "weekend.py"}), timeout=20) as r:
        return json.load(r)["data"]


def ema(xs, n):
    k, e = 2 / (n + 1), sum(xs[:n]) / n
    for x in xs[n:]:
        e = x * k + e * (1 - k)
    return e


def atr(bars, n):
    trs = [max(h - l, abs(h - pc), abs(l - pc)) for (_, _, h, l, _), (_, _, _, _, pc) in zip(bars[1:], bars[:-1])]
    return sum(trs[-n:]) / n


def time_stop(now):
    """Monday 22:00 Berlin (CET, UTC+1 from 25 Oct 2026) after now, in UTC."""
    days = (0 - now.weekday()) % 7 or 7
    return (now + datetime.timedelta(days=days)).replace(hour=21, minute=0, second=0, microsecond=0)


def weekend_key(now):
    return (now - datetime.timedelta(days=(now.weekday() - 4) % 7)).strftime("%Y-%m-%d")   # that Friday


def evaluate(sym, equity, cfg, now, close_by):
    c = get("/api/v1/contracts/" + sym)
    mult, tick = float(c["multiplier"]), float(c["tickSize"])
    fee = float(c.get("takerFeeRate") or 0.0006)
    px = float(c["lastTradePrice"])
    end = int(time.time() * 1000)
    raw = get("/api/v1/kline/query?symbol=%s&granularity=240&from=%d&to=%d" % (sym, end - 199 * BAR_MS, end))
    bars = [(int(b[0]), float(b[1]), float(b[2]), float(b[3]), float(b[4])) for b in raw]
    bars = [b for b in bars if b[0] + BAR_MS <= end]                       # closed bars only
    if len(bars) < 60:
        return {"symbol": sym, "verdict": "no-data", "why": "only %d closed 4h bars" % len(bars)}
    closes = [b[4] for b in bars]
    e20, e50, a = ema(closes, 20), ema(closes, 50), atr(bars, ATR_BARS)
    last = closes[-1]
    if last > e50 and e20 > e50:
        side = "long"
    elif last < e50 and e20 < e50:
        side = "short"
    else:
        return {"symbol": sym, "verdict": "no-trend", "why": "4h EMA20/EMA50 mixed"}
    res = {"symbol": sym, "side": side, "price": px, "ema20": e20, "ema50": e50, "atr": a,
           "strength": abs(last - e50) / a}
    if abs(px - e20) > a:
        return dict(res, verdict="stretched", why="%.1f ATR from the EMA20: wait for a pullback" % (abs(px - e20) / a))
    recent = bars[-SWING_BARS:]
    if side == "long":
        stop = K.round_away(min(b[3] for b in recent) - 0.5 * a, tick, down=True)
        risk = px - stop
    else:
        stop = K.round_away(max(b[2] for b in recent) + 0.5 * a, tick, down=False)
        risk = stop - px
    pct = risk / px * 100
    if not MIN_STOP <= pct <= MAX_STOP:
        return dict(res, verdict="stop", why="stop %.2f %% away, outside %.0f-%.0f %%" % (pct, MIN_STOP, MAX_STOP))
    target = K.round_away(px + TARGET_R * risk if side == "long" else px - TARGET_R * risk, tick, down=side == "long")
    fr = get("/api/v1/funding-rate/%s/current" % sym)
    interval = int(fr.get("granularity") or 28800000) / 1000
    nxt = datetime.datetime.fromtimestamp(int(fr["fundingTime"]) / 1000, datetime.UTC).replace(tzinfo=None)
    n_fund = 0 if nxt > close_by else int((close_by - nxt).total_seconds() // interval) + 1
    rate = abs(float(fr.get("value") or 0))
    pays = (float(fr.get("value") or 0) > 0) == (side == "long")   # longs pay a positive rate, shorts a negative one
    fund_unit = n_fund * max(rate, 0.0001) * px * mult            # assume at least 0.01 % a period, paid
    per_lot_loss = risk * mult + (px + stop) * mult * fee + fund_unit
    per_lot_win = abs(target - px) * mult - (px + target) * mult * fee - fund_unit
    budget = min(float(cfg["max_loss_per_trade_usdt"]), equity * float(cfg["max_loss_pct"]) / 100)
    lots = int(math.floor(budget / per_lot_loss + 1e-9))
    cap = int(math.floor(equity * float(cfg["max_position_pct"]) / 100 / (px * mult) + 1e-9))
    lots = min(lots, cap)
    res.update(stop=stop, target=target, stop_pct=pct, lots=lots, multiplier=mult, tick=tick,
               fundings=n_fund, funding_now=float(fr.get("value") or 0), funding_pays_now=pays,
               max_loss=lots * per_lot_loss, win=lots * per_lot_win,
               net_r=per_lot_win / per_lot_loss, value=lots * mult * px)
    if lots < 1:
        return dict(res, verdict="size", why="one contract loses %.2f USDT at the stop, over %.2f" % (per_lot_loss, budget))
    if res["net_r"] < MIN_NET_R:
        return dict(res, verdict="net-r", why="%.2fR after fees and funding, under %.1fR" % (res["net_r"], MIN_NET_R))
    return dict(res, verdict="ok", why="")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("symbols", nargs="+")
    ap.add_argument("--equity", type=float)
    ap.add_argument("--config", default="trader/kucoin.json")
    ap.add_argument("--log", action="store_true", help="record the best ticket as this weekend's one trade")
    a = ap.parse_args()
    cfg = K.read_config(a.config)
    now = datetime.datetime.now(datetime.UTC).replace(tzinfo=None)
    close_by = time_stop(now)
    wk = weekend_key(now)
    log = json.load(open(LOG)) if os.path.exists(LOG) else []
    taken = [x for x in log if x.get("weekend") == wk]
    if len(taken) >= MAX_TRADES:
        print("This weekend already has %d trades logged (%s), the limit is %d." % (len(taken), wk, MAX_TRADES))
        return 1
    held = {x["symbol"] for x in taken}
    equity = a.equity
    if equity is None:
        acct = K.private("GET", "/api/v1/account-overview?currency=USDT") or {}
        equity = float(acct.get("accountEquity") or 0)
    print("Weekend swing check %s UTC, equity %.2f USDT, time stop %s UTC (%s Berlin)" % (
        now.strftime("%Y-%m-%d %H:%M"), equity, close_by.strftime("%a %d.%m. %H:%M"),
        (close_by + datetime.timedelta(hours=1)).strftime("%a %H:%M")))
    rows = []
    for s in a.symbols:
        try:
            rows.append(evaluate(K.symbol_of(s), equity, cfg, now, close_by))
        except Exception as e:
            rows.append({"symbol": s, "verdict": "error", "why": str(e)[:100]})
    for r in rows:
        print("  %-11s %-6s %-10s %s" % (r["symbol"], r.get("side", ""), r["verdict"],
                                        r["why"] or "net %.2fR, stop %.2f %%" % (r["net_r"], r["stop_pct"])))
    ok = sorted([r for r in rows if r["verdict"] == "ok" and r["symbol"] not in held], key=lambda r: -r["strength"])
    if not ok:
        print("No weekend trade passes the rules. Nothing to take.")
        return 1
    b = ok[0]
    t = b["tick"]
    print("\nWEEKEND TICKET  %s %s, %d contracts (= %s %s), market, isolated 1x" % (
        b["side"].upper(), b["symbol"], b["lots"], K.fmt(b["lots"] * b["multiplier"], 1e-8).rstrip("0").rstrip("."),
        K.base_of(b["symbol"])))
    print("  entry about %s, value %.2f USDT" % (K.fmt(b["price"], t), b["value"]))
    print("  stop-loss %s (%.2f %%), take-profit %s (2R), both on the last price" % (
        K.fmt(b["stop"], t), b["stop_pct"], K.fmt(b["target"], t)))
    print("  max loss %.2f USDT, at the target +%.2f USDT (%.2fR net, fees and %d fundings in)" % (
        b["max_loss"], b["win"], b["net_r"], b["fundings"]))
    print("  funding now %+.4f %% (%s)" % (b["funding_now"] * 100, "you pay" if b["funding_pays_now"] else "you receive"))
    print("  time stop: close at market by %s Berlin" % (close_by + datetime.timedelta(hours=1)).strftime("%a %d.%m. %H:%M"))
    if a.log:
        log.append({"weekend": wk, "logged_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"), "close_by": close_by.strftime(
            "%Y-%m-%dT%H:%M:%SZ"), **{k: b[k] for k in ("symbol", "side", "price", "stop", "target", "lots", "max_loss")}})
        json.dump(log, open(LOG, "w"), indent=2)
        print("Logged as weekend trade %d of %d." % (len(taken) + 1, MAX_TRADES))
    return 0


if __name__ == "__main__":
    sys.exit(main())
