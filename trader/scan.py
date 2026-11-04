"""Scan several KuCoin contracts once a minute with trader-kucoin's check.

Prints one line per event (for a background monitor), sends nothing:
  PREP       a contract is within NEAR_PCT of a range edge: get the order form ready
  TRIGGERED  a closed bar broke out and passed every gate: entry written to trader/kucoin-entry.json
  PAUSE      inside a news window: no new signals
  ERR        a check failed
Usage: python -u trader/scan.py --minutes 30 SOL XRP ZEC ...
"""
import argparse
import datetime
import json
import shutil
import subprocess
import sys
import time

NEAR_PCT = 0.12                       # pre-alert distance to the trigger level
MIN_STOP_PCT = 0.33                   # stop at the far range edge must be this far for 1.2R net at 2R
PAUSES_UTC = [("12:15", "12:45")]     # US ECI 13:30 Berlin, +-15 minutes
KUCOIN = "trader-kucoin/kucoin.py"


def check(sym):
    out = f"trader/entry-{sym}.json"
    p = subprocess.run([sys.executable, KUCOIN, "check", sym, "--json", "--write", out],
                       capture_output=True, text=True, timeout=90)
    return json.loads(p.stdout), out


def in_pause(now):
    hm = now.strftime("%H:%M")
    return any(a <= hm < b for a, b in PAUSES_UTC)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--minutes", type=int, default=30)
    ap.add_argument("symbols", nargs="+")
    a = ap.parse_args()
    end = time.time() + a.minutes * 60
    seen, paused = set(), False
    while time.time() < end:
        now = datetime.datetime.utcnow()
        if in_pause(now):
            if not paused:
                print(f"PAUSE {now:%H:%M} UTC: news window, no new signals", flush=True)
                paused = True
        else:
            paused = False
            for sym in a.symbols:
                try:
                    res, path = check(sym)
                except Exception as e:
                    key = ("err", sym, str(e)[:60])
                    if key not in seen:
                        seen.add(key)
                        print(f"ERR {sym}: {str(e)[:120]}", flush=True)
                    continue
                rg = res.get("range") or {}
                last = (res.get("last") or {}).get("close")
                if res["status"] == "triggered":
                    shutil.copy(path, "trader/kucoin-entry.json")
                    t = res["trigger"]
                    print(f"TRIGGERED {sym} {res['side'].upper()} bar {t['bar']} UTC close {t['price']} "
                          f"volume {t['volume_x']}x range {rg.get('low')}-{rg.get('high')}", flush=True)
                    return 0
                if res["status"] != "waiting" or not last:
                    continue
                width = rg.get("width_pct") or 0
                if not 0.15 <= width <= 1.5 or width < MIN_STOP_PCT:
                    continue
                for side, lvl in (("LONG", rg.get("long_above")), ("SHORT", rg.get("short_below"))):
                    if not lvl:
                        continue
                    dist = abs(lvl - last) / last * 100
                    key = ("prep", sym, side, lvl)
                    if dist <= NEAR_PCT and key not in seen:
                        seen.add(key)
                        print(f"PREP {sym} {side} at close {'above' if side == 'LONG' else 'below'} {lvl}, "
                              f"last {last} ({dist:.2f} % away), range {width} % wide", flush=True)
        time.sleep(max(5, 65 - datetime.datetime.utcnow().second))   # just after the next bar closes
    print("END scan time is up, nothing triggered", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
