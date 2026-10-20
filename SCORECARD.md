# wxbot scorecard

Model vs market on settled days, using the last prices and forecasts **before** each climate day began. Lower is better. The model needs to beat the market on many days before any edge is believable.

## Summary

| venue | days | model log loss | market log loss | model Brier | market Brier | days model better |
|---|---|---|---|---|---|---|
| kalshi | 7 | 1.370 | 0.673 | 0.690 | 0.370 | 0/7 |
| polymarket | 3 | 1.304 | 0.870 | 0.676 | 0.561 | 0/3 |

## NWS forecast error by station (observed − NWS high at day start)

| station | days | mean error °F | RMSE °F | bias applied now |
|---|---|---|---|---|
| AUS | 1 | +0.00 | 0.00 | +0.00 |
| CHI | 1 | +1.00 | 1.00 | +0.09 |
| DEN | 1 | +3.00 | 3.00 | +0.27 |
| LAX | 1 | +4.00 | 4.00 | +0.36 |
| LGA | 1 | +0.00 | 0.00 | +0.00 |
| MIA | 1 | +1.00 | 1.00 | +0.09 |
| NYC | 1 | -3.00 | 3.00 | -0.27 |
| ORD | 1 | +1.00 | 1.00 | +0.09 |
| PHL | 1 | +1.00 | 1.00 | +0.09 |

## Kernel width (sigma) check — in-sample, Kalshi only

| sigma °F | model log loss |
|---|---|
| 1.0 | 1.349 |
| 1.5 | 1.329 |
| 2.0 (current) | 1.370 |
| 2.5 | 1.439 |
| 3.0 | 1.517 |
| 4.0 | 1.672 |

## Days

| venue | station | date | observed | NWS high | model p(actual) | market p(actual) | winner |
|---|---|---|---|---|---|---|---|
| polymarket | ORD | 2026-10-19 | 68 | 67.0 | 0.22 | 0.38 | market |
| polymarket | MIA | 2026-10-19 | 86 | 85.0 | 0.29 | 0.35 | market |
| polymarket | LGA | 2026-10-19 | 64 | 64.0 | 0.31 | 0.56 | market |
| kalshi | LAX | 2026-10-19 | 80 | 76.0 | 0.36 | 0.88 | market |
| kalshi | PHL | 2026-10-19 | 67 | 66.0 | 0.33 | 0.60 | market |
| kalshi | DEN | 2026-10-19 | 71 | 68.0 | 0.12 | 0.25 | market |
| kalshi | AUS | 2026-10-19 | 80 | 80.0 | 0.26 | 0.34 | market |
| kalshi | MIA | 2026-10-19 | 86 | 85.0 | 0.34 | 0.61 | market |
| kalshi | CHI | 2026-10-19 | 68 | 67.0 | 0.28 | 0.57 | market |
| kalshi | NYC | 2026-10-19 | 62 | 65.0 | 0.19 | 0.56 | market |
