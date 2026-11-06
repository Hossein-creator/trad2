"""Download closed 1h bars from KuCoin Futures public klines for the backtests. Uses no keys.
Usage: python trader/fetch_bars.py BARS_FOLDER [TOP_CONTRACTS] [DAYS] [MINUTES] [SYM,SYM,...]
"""
import concurrent.futures
import json
import os
import sys
import time
import urllib.request

API = "https://api-futures.kucoin.com"
MINUTES = int(sys.argv[4]) if len(sys.argv) > 4 else 60
STEP = MINUTES * 60 * 1000
WORKERS = 3


def get(path):
    req = urllib.request.Request(API + path, headers={"User-Agent": "fetch_bars.py"})
    for attempt in range(6):
        try:
            with urllib.request.urlopen(req, timeout=25) as r:
                return json.load(r)["data"]
        except Exception:
            if attempt == 5:
                raise
            time.sleep(2 + attempt * 3)


def fetch(c, out, start, end):
    sym = c["symbol"]
    got = {}
    t = end
    while t > start:
        f = max(start, t - 199 * STEP)
        raw = get("/api/v1/kline/query?symbol=%s&granularity=%d&from=%d&to=%d" % (sym, MINUTES, f, t)) or []
        if not raw:
            break                                 # before the contract's first listing
        for b in raw:
            got[int(b[0])] = [int(b[0])] + [float(x) for x in b[1:6]]
        t = f
        time.sleep(0.1)
    bars = [got[k] for k in sorted(got) if k + STEP <= end]
    json.dump({"symbol": sym, "multiplier": float(c["multiplier"]), "tick": float(c["tickSize"]), "bars": bars},
              open(os.path.join(out, sym + ".json"), "w"))
    print(sym, len(bars), flush=True)


def main():
    out = sys.argv[1]
    top = int(sys.argv[2]) if len(sys.argv) > 2 else 20
    days = int(sys.argv[3]) if len(sys.argv) > 3 else 370
    os.makedirs(out, exist_ok=True)
    rows = get("/api/v1/contracts/active")
    rows = [c for c in rows if c["symbol"].endswith("USDTM") and (c.get("assetClass") or "CRYPTO") == "CRYPTO"
            and c.get("status") == "Open"]
    rows = sorted(rows, key=lambda c: -float(c.get("turnoverOf24h") or 0))
    if len(sys.argv) > 5:                             # a comma list of contracts instead of the top ones
        want = set(sys.argv[5].split(","))
        rows = [c for c in rows if c["symbol"] in want]
    rows = rows[:top]
    end = int(time.time() // 3600) * 3600 * 1000
    start = end - days * 24 * 3600 * 1000
    with concurrent.futures.ThreadPoolExecutor(WORKERS) as pool:
        jobs = [pool.submit(fetch, c, out, start, end) for c in rows]
        for j in jobs:
            try:
                j.result()
            except Exception as e:
                print("ERR", str(e)[:100], flush=True)
    print("DONE", flush=True)


if __name__ == "__main__":
    sys.exit(main())
