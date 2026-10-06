# kalshi_edge

Do free public weather forecasts beat Kalshi's daily high-temperature markets?

**Short answer: no.** Across 7 cities and 96 days (Jul–Oct 2026), the market's prices were better calibrated
than forecast-only probabilities at every decision time. A fee-aware taker strategy lost money (statistically
significant), and the best result (market price blended with GFS MOS) was not significant and decayed to ~0
after Kalshi switched its settlement source.

## Setup
- **Markets:** KXHIGH{NY, CHI, MIA, AUS, DEN, LAX, PHIL}, every settled event 2026-06-01 → 2026-10-04 (June is used for training only).
- **Prices:** hourly yes_bid / yes_ask candles from Kalshi's public API at four decision times
  (11:00 and 18:00 local the day before; 09:00 and 12:00 on the day).
- **Forecasts:** GFS MOS and NBM text (NBS) daily max from the Iowa Environmental Mesonet archive. Only runs that
  were actually available at each decision time are used, so there is no look-ahead.
- **Model:** forecast + walk-forward bias and spread → normal bracket probabilities. A logistic blend of market and
  model log-odds is refit walk-forward on data at least 2 days old.
- **Fees:** `ceil(0.07 · P · (1 − P))` per contract, checked against Kalshi's documented worked example.
- **Fills:** taker pays the ask; maker is simulated 1¢ inside the spread (optimistic queue assumption).
- **Standard errors:** clustered by city-day.

## Results (Brier score summed over brackets, lower is better)
| Decision time | Market | GFS MOS | NBS | Blend |
|---|---|---|---|---|
| Day before 11:00 | **0.654** | 0.744 | 0.738 | 0.710 |
| Day before 18:00 | **0.619** | 0.726 | 0.733 | 0.694 |
| Same day 09:00 | **0.575** | 0.706 | 0.711 | 0.670 |
| Same day 12:00 | **0.503** | 0.706 | 0.701 | 0.662 |

- **Taker strategy (blend, edge > 0.10):** −2.5¢ per contract, t = −2.66.
- **Market + GFS MOS combination:** +1.7–2.2¢ per contract, t ≈ 1.1–1.35 (not significant). +4.6¢ before the
  settlement switch, +0.6¢ after.
- **Maker strategy:** −0.7¢ per contract. Spreads are already 1¢ wide 64% of the time.
- **Settlement:** Kalshi moved to The Weather Company on 2026-08-14. Settlement matched the NWS climate report on
  671 of 672 city-days; the exception is Miami on 2026-08-29 (Kalshi 90°F vs NWS 85°F).
- **Capacity:** roughly $300–800 a day deployable across all 7 cities, so even a real +2¢ edge is about $10 a day.

## Files
| File | Purpose |
|---|---|
| `fetch_kalshi.py` | Events, markets and hourly candles (switches to `/historical` endpoints automatically) |
| `fetch_mos.py` | IEM GFS MOS and NBS archives |
| `analyze.py` | Per-bracket panel and walk-forward model probabilities |
| `report.py` | Scores, calibration, taker/maker/combination backtests, liquidity, NWS cross-check |
| `cluster_check.py` | City-day clustered standard errors and switch-date detection |
| `book_snapshot.py` | Live order-book depth |
| `results.txt` | Full output |

Data (`data/`) is not committed. Run the fetch scripts to rebuild it. All endpoints are public and unauthenticated.

## Limitations
96 summer/autumn days; hourly quotes without size; simple normal-distribution models (no ensembles); the
7 cities × 4 times × 4 thresholds grid creates a multiple-testing problem.
