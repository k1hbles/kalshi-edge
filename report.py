"""Scoring + backtest on data/panel.csv produced by analyze.py."""
import os, sys, math, numpy as np, pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__))
P = pd.read_csv(os.path.join(HERE, "data", "panel.csv"), parse_dates=["date"])
P = P[P.date >= "2026-07-01"].copy()
pd.set_option("display.width", 200); pd.set_option("display.max_columns", 30)

# market probability: mid of bid/ask at decision time; skip empty books
P["has_book"] = (P.ask < 0.995) & (P.bid > 0.005) & P.ask.notna()
P["mid"] = np.where(P.ask.notna(), (P.ask.fillna(1) + P.bid.fillna(0)) / 2, np.nan)
# normalise market mids across the event's brackets so they sum to 1
P["mkt"] = P.mid / P.groupby(["series", "date", "slot"]).mid.transform("sum")
for k in ["gfs", "nbs", "blend"]:
    P["q_" + k] = P["p_" + k] / P.groupby(["series", "date", "slot"])["p_" + k].transform("sum")
P["period"] = np.where(P.twc, "post(TWC)", "pre(NWS)")

def scores(df, cols):
    out = {}
    ev = df.groupby(["series", "date", "slot"])
    for c in cols:
        brier = ((df[c] - df.y) ** 2).groupby([df.series, df.date, df.slot]).sum().mean()
        ll = -np.log(df[df.y == 1][c].clip(1e-3, 1)).mean()
        out[c] = dict(brier=round(brier, 4), logloss=round(ll, 3))
    return pd.DataFrame(out).T

ok = P.dropna(subset=["mkt", "q_blend", "q_gfs", "q_nbs"])
ok = ok[ok.groupby(["series", "date", "slot"]).y.transform("sum") == 1]
print("events x slots scored:", ok.groupby(["series", "date", "slot"]).ngroups)
print("\n=== Scores by slot (Brier summed over brackets, mean over events; logloss of winning bracket) ===")
for slot, g in ok.groupby("slot"):
    print(slot); print(scores(g, ["mkt", "q_nbs", "q_gfs", "q_blend"]))
print("\n=== Scores by period x slot ===")
for (per, slot), g in ok.groupby(["period", "slot"]):
    s = scores(g, ["mkt", "q_blend", "q_nbs"]); print(per, slot, "n_ev", g.groupby(["series","date"]).ngroups, s.brier.to_dict(), s.logloss.to_dict())
print("\n=== Scores by city (all slots before D 12:00) ===")
for ser, g in ok[ok.slot != "D 12:00"].groupby("series"):
    s = scores(g, ["mkt", "q_blend", "q_nbs"]); print(ser, s.brier.to_dict(), s.logloss.to_dict())

# calibration of market vs model
print("\n=== Calibration (bins of prob; mean prob vs realised freq) ===")
bins = [0, .05, .15, .3, .5, .7, .85, .95, 1.0001]
for c in ["mkt", "q_blend"]:
    g = ok.groupby(pd.cut(ok[c], bins)).agg(n=("y", "size"), p=(c, "mean"), freq=("y", "mean"))
    print(c); print(g.round(3).T)

# ---------- backtest ----------
def fee(p, per_contract_round=True):
    f = 0.07 * p * (1 - p)
    return np.ceil(f * 100 - 1e-9) / 100 if per_contract_round else f

def taker(df, model, thr, round_fee=True, pmin=0.02, pmax=0.98):
    trades = []
    b = df[df.has_book]
    # YES buys at ask
    y = b[(b[model] - b.ask > thr) & (b.ask >= pmin) & (b.ask <= pmax)]
    for _, r in y.iterrows():
        trades.append(dict(side="yes", price=r.ask, pnl=r.y - r.ask - fee(r.ask, round_fee), win=r.y,
                           slot=r.slot, series=r.series, period=r.period, edge=r[model] - r.ask, vol3=r.vol_next3, volh=r.vol_h))
    # NO buys at (1 - bid)
    n = b[(b.bid - b[model] > thr) & (1 - b.bid >= pmin) & (1 - b.bid <= pmax)]
    for _, r in n.iterrows():
        pr = 1 - r.bid
        trades.append(dict(side="no", price=pr, pnl=(1 - r.y) - pr - fee(pr, round_fee), win=1 - r.y,
                           slot=r.slot, series=r.series, period=r.period, edge=r.bid - r[model], vol3=r.vol_next3, volh=r.vol_h))
    return pd.DataFrame(trades)

def summarize(t):
    if t.empty: return dict(n=0)
    m = t.pnl.mean(); se = t.pnl.std() / math.sqrt(len(t)) if len(t) > 1 else np.nan
    return dict(n=len(t), hit=round(t.win.mean(), 3), avg_px=round(t.price.mean(), 3), pnl_per_ct=round(m, 4),
                se=round(se, 4), t=round(m / se, 2) if se else np.nan, roi=round(t.pnl.sum() / t.price.sum(), 3))

print("\n=== Taker backtest: buy YES at ask / NO at 1-bid when model edge > thr; fee ceil(0.07P(1-P)) per contract ===")
for model in ["q_blend", "q_nbs", "q_gfs"]:
    for thr in [0.05, 0.10, 0.15, 0.20]:
        t = taker(P.dropna(subset=[model]), model, thr)
        print(model, thr, "ALL", summarize(t))
        if model == "q_blend":
            for slot in sorted(P.slot.unique()):
                print("    ", slot, summarize(t[t.slot == slot]) if not t.empty else {})
            for per in ["pre(NWS)", "post(TWC)"]:
                print("    ", per, summarize(t[t.period == per]) if not t.empty else {})
t = taker(P.dropna(subset=["q_blend"]), "q_blend", 0.10)
print("\nblend thr .10 by city:"); [print("   ", s, summarize(g)) for s, g in t.groupby("series")]
print("blend thr .10 by side:"); [print("   ", s, summarize(g)) for s, g in t.groupby("side")]
print("blend thr .10 by price bucket:"); [print("   ", s, summarize(g)) for s, g in t.groupby(pd.cut(t.price, [0, .1, .3, .5, .7, .9, 1]))]
print("blend thr .10 with exact (unrounded) fee:", summarize(taker(P.dropna(subset=["q_blend"]), "q_blend", 0.10, round_fee=False)))

# market-based sanity: does the market itself beat a 'fade' ?  (no-skill benchmark)
# ---------- maker backtest ----------
def maker(df, model, thr):
    """Post YES bid at bid+1c (if < ask) when model-(bid+1c) > thr; filled if yes_ask later trades down to <= our price
    before close. Same for NO via YES offer at ask-1c filled if yes_bid later >= it. Maker fee assumed 0 (check series)."""
    tr = []
    b = df[df.has_book & (df.ask - df.bid >= 0.02)]
    for _, r in b.iterrows():
        L = round(r.bid + 0.01, 2)
        if r[model] - L > thr and pd.notna(r.ask_low_after) and r.ask_low_after <= L:
            tr.append(dict(side="yes", price=L, pnl=r.y - L, win=r.y, slot=r.slot, series=r.series, period=r.period))
        U = round(r.ask - 0.01, 2)
        if (U - r[model]) > thr and pd.notna(r.bid_high_after) and r.bid_high_after >= U:
            tr.append(dict(side="no", price=1 - U, pnl=(1 - r.y) - (1 - U), win=1 - r.y, slot=r.slot, series=r.series, period=r.period))
    return pd.DataFrame(tr)
print("\n=== Maker backtest (optimistic queue: filled if opposite quote later reaches our price) ===")
for thr in [0.05, 0.10, 0.15]:
    t = maker(P.dropna(subset=["q_blend"]), "q_blend", thr); print("q_blend", thr, summarize(t))
    if thr == 0.10 and not t.empty:
        [print("    ", s, summarize(g)) for s, g in t.groupby("slot")]
# spread stats: how often 1c spread
b = P[P.has_book]
print("\nspread distribution at decision times:", (b.ask - b.bid).round(2).value_counts(normalize=True).head(6).round(3).to_dict())

# ---------- liquidity ----------
print("\n=== Liquidity ===")
ev = P[P.slot == "D 09:00"].groupby(["series", "date"]).agg(vol=("vol_total", "sum"))
print("contracts traded per event (whole life): median by city"); print(ev.groupby("series").vol.median())
br = P[P.slot == "D 09:00"]
print("median per-bracket lifetime volume:", br.vol_total.median(), " mean:", round(br.vol_total.mean()))
for slot in sorted(P.slot.unique()):
    s = P[(P.slot == slot)]
    print(slot, "median contracts traded in the 3h after decision, per bracket:", s.vol_next3.median(),
          " per event:", s.groupby(["series", "date"]).vol_next3.sum().median())
t = taker(P.dropna(subset=["q_blend"]), "q_blend", 0.10)
if not t.empty:
    print("signals (thr .10): median vol in 3h after signal on that bracket:", t.vol3.median(), " signals/day:",
          round(len(t) / P.date.nunique(), 2))

# ---------- does the model add information beyond the market? logistic y ~ logit(mkt) + logit(model) ----------
def logit(p): p = np.clip(p, 0.005, 0.995); return np.log(p / (1 - p))
def logreg(X, y, it=50):
    X = np.column_stack([np.ones(len(X)), X]); b = np.zeros(X.shape[1])
    for _ in range(it):
        p = 1 / (1 + np.exp(-X @ b)); W = p * (1 - p); H = X.T @ (X * W[:, None]); b += np.linalg.solve(H, X.T @ (y - p))
    se = np.sqrt(np.diag(np.linalg.inv(H))); return b, se
print("\n=== Encompassing test: logistic y ~ a + b1*logit(mkt) + b2*logit(model)  (b2>0 significant => model adds info) ===")
for slot, g in ok.groupby("slot"):
    for mdl in ["q_blend", "q_gfs"]:
        b, se = logreg(np.column_stack([logit(g.mkt), logit(g[mdl])]), g.y.values)
        print(slot, mdl, "b_mkt=%.2f(%.2f) b_model=%.2f(%.2f) n=%d" % (b[1], se[1], b[2], se[2], len(g)))

# ---------- settlement cross-check: Kalshi expiration_value vs IEM NWS CLI high ----------
print("\n=== Kalshi settled value vs IEM NWS CLI daily high ===")
e = P[P.slot == "D 09:00"].drop_duplicates(["series", "date"]).dropna(subset=["truth", "cli"])
e = e.assign(diff=e.truth - e.cli.astype(float))
print(e.groupby("period").agg(n=("diff", "size"), mismatches=("diff", lambda d: int((d != 0).sum())),
                              max_abs=("diff", lambda d: d.abs().max())))
print(e[e["diff"] != 0][["series", "date", "truth", "cli", "period"]].to_string())

# ---------- walk-forward combination: p = logistic(a + b1 logit(mkt) + b2 logit(model)), fit on events with date <= D-2 ----------
print("\n=== Walk-forward combo (market + MOS) taker backtest ===")
def combo(df, mdl, min_train=300):
    df = df.sort_values("date").copy(); df["p_combo"] = np.nan
    for slot, g in df.groupby("slot"):
        for d in sorted(g.date.unique()):
            tr = g[g.date <= d - pd.Timedelta(days=2)]
            if len(tr) < min_train: continue
            b, _ = logreg(np.column_stack([logit(tr.mkt), logit(tr[mdl])]), tr.y.values)
            te = g[g.date == d]
            z = b[0] + b[1] * logit(te.mkt) + b[2] * logit(te[mdl])
            df.loc[te.index, "p_combo"] = 1 / (1 + np.exp(-z))
    return df
for mdl in ["q_gfs", "q_blend"]:
    C = combo(ok, mdl)
    C = C.dropna(subset=["p_combo"])
    C["p_combo"] = C.p_combo / C.groupby(["series", "date", "slot"]).p_combo.transform("sum")
    s = scores(C, ["mkt", "p_combo"]); print(mdl, "out-of-sample scores", s.to_dict())
    for thr in [0.02, 0.04, 0.06, 0.10]:
        t = taker(C, "p_combo", thr); print("  ", mdl, thr, summarize(t))
        if thr == 0.04 and not t.empty:
            for k, g in t.groupby("slot"): print("      ", k, summarize(g))
            for k, g in t.groupby("period"): print("      ", k, summarize(g))
