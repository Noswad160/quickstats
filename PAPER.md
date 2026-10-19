# wxbot paper trading (Kalshi)

**Simulated only.** Replays every stored price snapshot and trades the model with the rules below. Fills assume the full size at the quoted best price.

Rules: min edge $0.05/contract after fees · 10% Kelly · ≤$25 per market · ≤$50 per city/day · prices 0.03–0.97 · 1–2 days ahead

## Summary

- Starting bankroll: $1,000.00
- Settled trades: 0 (0 won) · staked $0.00
- Realized P&L: **$+0.00**
- Model expected P&L on those trades: $+0.00 (if realized is far below this over many trades, the model is overconfident)
- Open trades: 16 · cost $296.55
- Bankroll now (cash + open at cost): $1,000.00

## Trades (newest first)

| placed | station | date | bucket °F | side | price | qty | fee | model p | observed | P&L |
|---|---|---|---|---|---|---|---|---|---|---|
| 2026-10-19T00:59 | PHL | 2026-10-19 | ≥68 | yes | 0.17 | 46 | 0.46 | 0.27 |  | open |
| 2026-10-19T00:59 | PHL | 2026-10-19 | 66–67 | no | 0.38 | 63 | 1.04 | 0.67 |  | open |
| 2026-10-19T00:59 | PHL | 2026-10-19 | 62–63 | yes | 0.03 | 179 | 0.37 | 0.11 |  | open |
| 2026-10-19T00:59 | NYC | 2026-10-19 | 62–63 | no | 0.43 | 55 | 0.95 | 0.81 |  | open |
| 2026-10-19T00:59 | NYC | 2026-10-19 | 60–61 | no | 0.87 | 28 | 0.23 | 0.94 |  | open |
| 2026-10-19T00:59 | MIA | 2026-10-19 | 85–86 | no | 0.35 | 68 | 1.09 | 0.66 |  | open |
| 2026-10-19T00:59 | MIA | 2026-10-19 | 83–84 | yes | 0.14 | 87 | 0.74 | 0.28 |  | open |
| 2026-10-19T00:59 | LAX | 2026-10-19 | ≥79 | no | 0.19 | 124 | 1.34 | 0.62 |  | open |
| 2026-10-19T00:59 | DEN | 2026-10-19 | 71–72 | no | 0.67 | 8 | 0.13 | 0.88 |  | open |
| 2026-10-19T00:59 | DEN | 2026-10-19 | 69–70 | no | 0.48 | 50 | 0.88 | 0.73 |  | open |
| 2026-10-19T00:59 | DEN | 2026-10-19 | 67–68 | yes | 0.13 | 138 | 1.10 | 0.31 |  | open |
| 2026-10-19T00:59 | CHI | 2026-10-19 | 69–70 | no | 0.75 | 17 | 0.23 | 0.82 |  | open |
| 2026-10-19T00:59 | CHI | 2026-10-19 | 67–68 | no | 0.44 | 54 | 0.94 | 0.72 |  | open |
| 2026-10-19T00:59 | CHI | 2026-10-19 | 65–66 | yes | 0.17 | 67 | 0.67 | 0.28 |  | open |
| 2026-10-19T00:59 | AUS | 2026-10-19 | 80–81 | no | 0.66 | 32 | 0.51 | 0.74 |  | open |
| 2026-10-19T00:59 | AUS | 2026-10-19 | 78–79 | no | 0.49 | 49 | 0.86 | 0.76 |  | open |
