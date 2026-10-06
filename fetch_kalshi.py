"""Fetch settled Kalshi daily-high events, markets, and hourly candlesticks (read-only, unauthenticated)."""
import json, os, sys, time, datetime as dt
import requests
B = "https://api.elections.kalshi.com/trade-api/v2"
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
SERIES = sys.argv[1].split(",") if len(sys.argv) > 1 else ["KXHIGHNY","KXHIGHCHI","KXHIGHMIA","KXHIGHAUS","KXHIGHDEN","KXHIGHLAX","KXHIGHPHIL"]
START = dt.date(2026, 6, 1); END = dt.date(2026, 10, 4)
S = requests.Session()

def get(path, **params):
    for i in range(6):
        r = S.get(B + path, params=params, timeout=30)
        if r.status_code == 429:
            time.sleep(1 + i); continue
        time.sleep(0.07)
        return r.status_code, (r.json() if r.headers.get("content-type","").startswith("application/json") else {})
    return 429, {}

def ev_date(t):  # KXHIGHNY-26OCT04
    s = t.split("-")[1]
    return dt.datetime.strptime(s, "%y%b%d").date()

def norm_candle(c):
    # historical candles use 'close', live use 'close_dollars'
    def f(d, k):
        if not d: return None
        v = d.get(k + "_dollars", d.get(k))
        return float(v) if v is not None else None
    return dict(ts=c["end_period_ts"], vol=float(c.get("volume_fp", c.get("volume", 0)) or 0),
                oi=float(c.get("open_interest_fp", c.get("open_interest", 0)) or 0),
                p_close=f(c.get("price"), "close"), p_mean=f(c.get("price"), "mean"),
                ask=f(c.get("yes_ask"), "close"), bid=f(c.get("yes_bid"), "close"),
                ask_low=f(c.get("yes_ask"), "low"), bid_high=f(c.get("yes_bid"), "high"))

for ser in SERIES:
    fn = os.path.join(OUT, f"{ser}.json")
    if os.path.exists(fn): print("skip", ser); continue
    events, cur = [], None
    while True:
        p = dict(series_ticker=ser, status="settled", limit=200)
        if cur: p["cursor"] = cur
        sc, d = get("/events", **p)
        events += d.get("events", []); cur = d.get("cursor")
        if not cur or not d.get("events"): break
        if ev_date(d["events"][-1]["event_ticker"]) < START: break
    events = [e for e in events if START <= ev_date(e["event_ticker"]) <= END]
    print(ser, len(events), "events", flush=True)
    out = []
    for e in events:
        et = e["event_ticker"]
        sc, d = get("/markets", event_ticker=et, limit=100)
        ms, hist = d.get("markets", []), False
        if not ms:
            sc, d = get("/historical/markets", event_ticker=et, limit=100); ms, hist = d.get("markets", []), True
        for m in ms:
            ot = int(dt.datetime.fromisoformat(m["open_time"].replace("Z","+00:00")).timestamp())
            ct = int(dt.datetime.fromisoformat(m["close_time"].replace("Z","+00:00")).timestamp())
            path = (f"/historical/markets/{m['ticker']}/candlesticks" if hist
                    else f"/series/{ser}/markets/{m['ticker']}/candlesticks")
            sc, d = get(path, start_ts=ot, end_ts=ct, period_interval=60)
            if sc != 200 and not hist:
                sc, d = get(f"/historical/markets/{m['ticker']}/candlesticks", start_ts=ot, end_ts=ct, period_interval=60)
            keep = {k: m.get(k) for k in ["ticker","event_ticker","strike_type","floor_strike","cap_strike","result",
                    "expiration_value","open_time","close_time","rules_primary"]}
            keep["volume"] = float(m.get("volume_fp", m.get("volume", 0)) or 0)
            keep["hist"] = hist
            keep["candles"] = [norm_candle(c) for c in d.get("candlesticks", [])]
            out.append(keep)
    json.dump(out, open(fn, "w"))
    print(ser, "markets", len(out), flush=True)
