"""Walk-forward comparison of Kalshi daily-high bracket prices vs. MOS/NBM-based probabilities.

Inputs: data/KXHIGH*.json (fetch_kalshi.py), data/mos/*.csv (fetch_mos.py), data/cli_*.json (IEM CLI).
Outputs: printed tables + data/panel.csv (one row per bracket x decision time).
"""
import json, glob, os, math, datetime as dt
from zoneinfo import ZoneInfo
import numpy as np, pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__)); D = os.path.join(HERE, "data")
CITY = {  # series: (station, tz)
    "KXHIGHNY": ("KNYC", "America/New_York"), "KXHIGHCHI": ("KMDW", "America/Chicago"),
    "KXHIGHMIA": ("KMIA", "America/New_York"), "KXHIGHAUS": ("KAUS", "America/Chicago"),
    "KXHIGHDEN": ("KDEN", "America/Denver"), "KXHIGHLAX": ("KLAX", "America/Los_Angeles"),
    "KXHIGHPHIL": ("KPHL", "America/New_York")}
# decision slots: (name, day offset relative to target day, local hour)
SLOTS = [("D-1 11:00", -1, 11), ("D-1 18:00", -1, 18), ("D 09:00", 0, 9), ("D 12:00", 0, 12)]
DELAY = {"GFS": 5, "NBS": 3}  # conservative hours from model init until the text product is usable
EVAL_START = dt.date(2026, 7, 1)
UTC = dt.timezone.utc
Phi = lambda x: 0.5 * (1 + math.erf(x / math.sqrt(2)))

def ev_date(t): return dt.datetime.strptime(t.split("-")[1], "%y%b%d").date()

# ---------- forecasts: one row per (station, model, runtime, target date) ----------
def load_mos(st):
    rows = []
    for m in ["GFS", "NBS"]:
        df = pd.concat([pd.read_csv(f, low_memory=False) for f in sorted(glob.glob(f"{D}/mos/{st}_{m}_*.csv"))])
        col = "n_x" if m == "GFS" else "txn"
        df = df[df[col].notna()].copy()
        df["runtime"] = pd.to_datetime(df["runtime"], utc=True); df["ftime"] = pd.to_datetime(df["ftime"], utc=True)
        df = df[df.ftime.dt.hour < 9]   # daytime-max rows end 00Z-06Z next UTC day
        df["target"] = (df.ftime - pd.Timedelta(hours=12)).dt.date
        df["fc"] = df[col].astype(float); df["model"] = m
        df["sd"] = pd.to_numeric(df["xnd"], errors="coerce") if m == "NBS" else np.nan
        rows.append(df[["model", "runtime", "target", "fc", "sd"]].drop_duplicates(["runtime", "target"]))
    return pd.concat(rows)

def latest_fc(fc, model, target, t_utc):
    sub = fc[(fc.model == model) & (fc.target == target) & (fc.runtime + pd.Timedelta(hours=DELAY[model]) <= t_utc)]
    if sub.empty: return None
    r = sub.loc[sub.runtime.idxmax()]
    return r.fc, r.sd, r.runtime

def bracket(m):
    st, f, c = m["strike_type"], m["floor_strike"], m["cap_strike"]
    if st == "less": return -np.inf, c - 0.5
    if st == "greater": return f + 0.5, np.inf
    return f - 0.5, c + 0.5

def pnorm(lo, hi, mu, sd):
    a = 0 if lo == -np.inf else Phi((lo - mu) / sd); b = 1 if hi == np.inf else Phi((hi - mu) / sd)
    return max(b - a, 1e-4)

def build():
    panel, fcrows = [], []
    for ser, (st, tz) in CITY.items():
        fn = f"{D}/{ser}.json"
        if not os.path.exists(fn): print("missing", ser); continue
        mk = json.load(open(fn)); fc = load_mos(st); Z = ZoneInfo(tz)
        cli = {r["valid"]: r["high"] for r in json.load(open(f"{D}/cli_{st}.json"))["results"]}
        ev = {}
        for m in mk: ev.setdefault(m["event_ticker"], []).append(m)
        for et, ms in ev.items():
            d = ev_date(et)
            vals = [m["expiration_value"] for m in ms if m["expiration_value"]]
            truth = float(vals[0]) if vals else np.nan
            twc = any("Weather Company" in m["rules_primary"] for m in ms)
            for slot, off, hr in SLOTS:
                t_loc = dt.datetime.combine(d + dt.timedelta(days=off), dt.time(hr), Z)
                ts = int(t_loc.timestamp()); t_utc = pd.Timestamp(t_loc.astimezone(UTC))
                f = {mm: latest_fc(fc, mm, d, t_utc) for mm in ["GFS", "NBS"]}
                fcrows.append(dict(series=ser, date=d, slot=slot, truth=truth,
                                   gfs=f["GFS"][0] if f["GFS"] else np.nan, nbs=f["NBS"][0] if f["NBS"] else np.nan,
                                   nbs_sd=f["NBS"][1] if f["NBS"] else np.nan,
                                   gfs_run=f["GFS"][2] if f["GFS"] else None, nbs_run=f["NBS"][2] if f["NBS"] else None))
                for m in ms:
                    cs = {c["ts"]: c for c in m["candles"]}
                    c = cs.get(ts)
                    nxt = [cs[k] for k in sorted(cs) if k > ts]
                    lo, hi = bracket(m)
                    panel.append(dict(series=ser, date=d, slot=slot, ticker=m["ticker"], twc=twc, lo=lo, hi=hi,
                        y=1 if m["result"] == "yes" else 0, truth=truth, cli=cli.get(d.isoformat()),
                        ask=c["ask"] if c else np.nan, bid=c["bid"] if c else np.nan,
                        last=c["p_close"] if c else np.nan, vol_h=c["vol"] if c else 0,
                        vol_next3=sum(x["vol"] for x in nxt[:3]), vol_total=m["volume"],
                        ask_low_after=min([x["ask_low"] for x in nxt if x["ask_low"] is not None] or [np.nan]),
                        bid_high_after=max([x["bid_high"] for x in nxt if x["bid_high"] is not None] or [np.nan])))
    return pd.DataFrame(panel), pd.DataFrame(fcrows)

def walk_forward_params(fcdf):
    """For each (series, slot, date) estimate bias & sigma from days <= date-2 (known before any decision)."""
    out = []
    fcdf = fcdf.sort_values("date")
    for (ser, slot), g in fcdf.groupby(["series", "slot"]):
        g = g.copy(); g["blend"] = np.nan
        for i, r in g.iterrows():
            past = g[(g.date <= r.date - dt.timedelta(days=2)) & g.truth.notna()].tail(45)
            row = dict(series=ser, slot=slot, date=r.date, n_train=len(past))
            for k in ["gfs", "nbs"]:
                e = (past.truth - past[k]).dropna()
                b = e.tail(30).mean() if len(e) >= 10 else 0.0
                s = max(np.sqrt(((e - b) ** 2).mean()) if len(e) >= 10 else 3.0, 1.0)
                row[k + "_mu"] = r[k] + b if pd.notna(r[k]) else np.nan; row[k + "_sig"] = s
                row[k + "_bias"] = b
            # blend: equal-weight of bias-corrected; sigma from past blend errors
            out.append(row)
    P = pd.DataFrame(out)
    # blend sigma: compute bias-corrected blend errors walk-forward (second pass)
    P = P.merge(fcdf[["series", "slot", "date", "truth"]], on=["series", "slot", "date"])
    P["blend_mu"] = P[["gfs_mu", "nbs_mu"]].mean(axis=1)
    P["blend_err"] = P.truth - P.blend_mu
    sig = []
    for (ser, slot), g in P.sort_values("date").groupby(["series", "slot"]):
        for i, r in g.iterrows():
            past = g[(g.date <= r.date - dt.timedelta(days=2))].blend_err.dropna().tail(45)
            sig.append((i, max(np.sqrt((past ** 2).mean()), 1.0) if len(past) >= 10 else 3.0))
    for i, s in sig: P.loc[i, "blend_sig"] = s
    return P.drop(columns=["truth", "blend_err"])

if __name__ == "__main__":
    panel, fcdf = build()
    fcdf.to_csv(f"{D}/forecasts.csv", index=False)
    P = walk_forward_params(fcdf)
    panel = panel.merge(P, on=["series", "slot", "date"], how="left")
    for k in ["gfs", "nbs", "blend"]:
        panel["p_" + k] = [pnorm(r.lo, r.hi, r[k + "_mu"], r[k + "_sig"]) if pd.notna(r[k + "_mu"]) else np.nan
                           for _, r in panel.iterrows()]
    panel.to_csv(f"{D}/panel.csv", index=False)
    print(panel.shape)
