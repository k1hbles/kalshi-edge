"""Download IEM MOS archive (GFS MAV + NBM NBS text) for settlement stations."""
import os, time, requests
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "mos"); os.makedirs(OUT, exist_ok=True)
ST = ["KNYC","KMDW","KMIA","KAUS","KDEN","KLAX","KPHL"]
RNG = [("2026-05-28T00:00Z","2026-07-15T00:00Z","a"),("2026-07-15T00:00Z","2026-08-31T00:00Z","b"),("2026-08-31T00:00Z","2026-10-06T00:00Z","c")]
for st in ST:
    for m in ["GFS","NBS"]:
        for s,e,tag in RNG:
            fn = f"{OUT}/{st}_{m}_{tag}.csv"
            if os.path.exists(fn) and os.path.getsize(fn) > 1000: continue
            r = requests.get("https://mesonet.agron.iastate.edu/cgi-bin/request/mos.py",
                             params=dict(station=st, model=m, sts=s, ets=e, format="csv"), timeout=300)
            open(fn,"w").write(r.text); print(fn, len(r.text), flush=True); time.sleep(1)
