"""Snapshot live order-book depth for open daily-high markets (read-only)."""
import requests, time
B = "https://api.elections.kalshi.com/trade-api/v2"
for ser in ["KXHIGHNY","KXHIGHCHI","KXHIGHMIA","KXHIGHAUS","KXHIGHDEN","KXHIGHLAX","KXHIGHPHIL"]:
    ms = requests.get(f"{B}/markets", params=dict(series_ticker=ser, status="open", limit=100)).json()["markets"]
    for m in sorted(ms, key=lambda m: m["ticker"]):
        ob = requests.get(f"{B}/markets/{m['ticker']}/orderbook", params=dict(depth=10)).json().get("orderbook_fp", {})
        yes = [(float(p), float(q)) for p, q in (ob.get("yes_dollars") or [])]
        no = [(float(p), float(q)) for p, q in (ob.get("no_dollars") or [])]
        bb = max(yes) if yes else (0, 0); bn = max(no) if no else (0, 0)   # best yes bid; best no bid -> yes ask = 1 - no bid
        ask = 1 - bn[0]
        # $ cost to buy YES within 5c of the best ask = sum over NO bids with price >= bn-0.05
        depth5 = sum(q * (1 - p) for p, q in no if p >= bn[0] - 0.05)
        print(f"{m['ticker']:28s} bid {bb[0]:.2f}x{bb[1]:7.0f}  ask {ask:.2f}x{bn[1]:7.0f}  $to-buy-YES-within-5c {depth5:8.0f}  vol {float(m.get('volume_fp',0)):9.0f}")
        time.sleep(0.1)
