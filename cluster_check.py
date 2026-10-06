"""Event-clustered standard errors for key backtest results (imports report.py functions)."""
import io, contextlib, numpy as np, pandas as pd, json, glob
with contextlib.redirect_stdout(io.StringIO()):
    import report as R
def csum(t, name):
    t = t.copy(); g = t.groupby(["series", "date"]).pnl.sum(); n = len(t)
    m = t.pnl.mean(); se = np.sqrt(((g - g.mean() * 0) ** 2).sum() - 0) / n  # cluster-robust SE of mean (sum of cluster residuals)
    res = (t.pnl - m).groupby([t.series, t.date]).sum(); se = np.sqrt((res ** 2).sum()) / n
    print(f"{name:40s} n={n:5d} clusters={len(res):4d} pnl/ct={m:+.4f} clusterSE={se:.4f} t={m/se:+.2f}  $pnl_total(1ct each)={t.pnl.sum():+.1f}")
def tk(df, model, thr):
    t = R.taker(df, model, thr); return t
# need date in trades: rebuild taker with date
def taker2(df, model, thr):
    out = []
    for idx, r in df[df.has_book].iterrows(): pass
P = R.P
def taker_d(df, model, thr):
    t = R.taker(df, model, thr)
    b = df[df.has_book]
    y = b[(b[model] - b.ask > thr) & (b.ask >= .02) & (b.ask <= .98)]
    n = b[(b.bid - b[model] > thr) & (1 - b.bid >= .02) & (1 - b.bid <= .98)]
    t["date"] = list(y.date) + list(n.date); return t
for thr in [0.05, 0.10, 0.20]:
    csum(taker_d(P.dropna(subset=["q_blend"]), "q_blend", thr), f"blend taker thr{thr}")
    csum(taker_d(P.dropna(subset=["q_gfs"]), "q_gfs", thr), f"gfsMOS taker thr{thr}")
t = taker_d(P.dropna(subset=["q_blend"]), "q_blend", 0.10)
for s, g in t.groupby("series"): csum(g, f"blend thr.10 {s}")
mia = t[t.series == "KXHIGHMIA"]
for s, g in mia.groupby("side"): csum(g, f"  MIA side {s}")
for s, g in mia.groupby("period"): csum(g, f"  MIA {s}")
C = R.combo(R.ok, "q_gfs").dropna(subset=["p_combo"])
C["p_combo"] = C.p_combo / C.groupby(["series", "date", "slot"]).p_combo.transform("sum")
for thr in [0.02, 0.04, 0.06, 0.10]:
    tt = taker_d(C, "p_combo", thr); csum(tt, f"combo(mkt+GFS MOS) thr{thr}")
    if thr == 0.04:
        for s, g in tt.groupby("side"): csum(g, f"   side {s}")
        for s, g in tt.groupby("period"): csum(g, f"   {s}")
print("combo eval period:", C.date.min(), C.date.max())
# TWC switch date per city
for f in sorted(glob.glob(R.os.path.join(R.HERE, "data", "KXHIGH*.json"))):
    d = json.load(open(f)); tw = sorted(m["event_ticker"] for m in d if "Weather Company" in m["rules_primary"])
    tw = sorted(tw, key=lambda e: R.pd.to_datetime(e.split("-")[1], format="%y%b%d"))
    print(f.split("/")[-1], "first TWC-worded event:", tw[0] if tw else None)
