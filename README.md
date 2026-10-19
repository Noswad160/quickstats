# wxbot — weather prediction-market research bot

Collects daily-high-temperature market prices (Kalshi, Polymarket) and ensemble
weather forecasts (GEFS + ECMWF ENS via Open-Meteo), turns the forecasts into bucket
probabilities, and reports where the model disagrees with the market after fees.

**It does not place trades.** The plan is: collect data for a few weeks → calibrate
the model against observed outcomes → paper trade → only then consider small live size.

## Venue note
For a US-based user, live trading should target **Kalshi** (CFTC-regulated). The
international Polymarket exchange is not open to US persons; its data is collected
for research and cross-venue comparison only.

## Setup
```bash
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
pytest -q
```

## Running on GitHub Actions (default)
`.github/workflows/collect.yml` runs `collect` every 15 min and `observe` daily on
GitHub runners, committing gzipped run files to the `data` branch along with:
- `REPORT.md` — current model-vs-market disagreements
- `SCORECARD.md` — model vs market log loss/Brier on settled days, NWS error per station
- `PAPER.md` — simulated Kalshi trades and P&L (rules in `wxbot/paper.py`)
To analyse locally: `git clone -b data <repo> wxdata && python -m wxbot load wxdata && python -m wxbot edges`.

## Usage
```bash
python -m wxbot collect               # one snapshot of markets + forecasts
python -m wxbot collect --loop 15     # every 15 minutes (run under tmux/systemd/cron)
python -m wxbot observe               # observed highs from NWS climate reports (for calibration)
python -m wxbot edges --min-edge 0.03 # model vs market, best side per bucket
python -m wxbot scorecard             # grade model vs market on settled days
python -m wxbot paper                 # simulated Kalshi trading over all stored prices
```
Data goes to `data/wxbot.sqlite` (override with `--db` or `WXBOT_DB`).

## How pricing works
- Kalshi settles on the NWS Daily Climate Report, whose day runs midnight–midnight
  **local standard time**, so hourly ensemble temperatures are bucketed on that clock.
- Each member's daily max is smeared by a Gaussian (`WXBOT_SIGMA`, default 2 °F) to
  cover grid-vs-station error and ensemble under-dispersion; the reported value is a
  whole degree, so bucket `70..71` integrates over `[69.5, 71.5)`.
- Edge = model probability − price − taker fee (Kalshi: `ceil(0.07·C·P·(1−P))`).

## Before trusting any number
- Verify each market's resolution station in `wxbot/config.py` against the venue's rules.
- Sigma and per-station bias are uncalibrated defaults. Run `observe` daily and
  calibrate before reading anything into `edges`.
