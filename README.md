# nbaparlay — set your own NBA lines, then find the bets and parlays worth making

Every few hours on game days this:

1. **Pulls the data** from ESPN: every box score this season and last, the injury report, the
   schedule, and DraftKings' spreads, totals and moneylines (opening and current).
2. **Rates every team**: opponent-adjusted offense, defense and pace, home court and back-to-backs,
   weighted toward recent games.
3. **Projects every player**: minutes from recent role (adjusted when teammates are out), per-minute
   rates weighted toward recent form and shrunk toward average when the sample is small, adjusted for
   the opponent and the game's pace.
4. **Simulates each game 10,000 times.** Who plays (questionable players are coin flips), pace,
   each team's shooting night, blowouts that bench starters, and each player's share of the scoring
   all come from the same simulated game, so props and game lines are consistent and correlated.
5. **Sets my line** for every spread, total, moneyline and player prop, before looking at any book.
6. **Prices what the books offer** and lists the bets with positive expected value, then builds
   parlays from those legs only, priced jointly from the simulations.

Results go to the `nba-data` branch: `PICKS.md` (today's lines, bets and parlays) and `BACKTEST.md`.

## The honest part

- A parlay is only worth betting if its legs are. Books build in a bigger margin on parlays
  (it compounds with every leg), so a parlay of ordinary bets is a worse bet than any of them alone.
  This only builds parlays out of legs that each beat their price.
- `BACKTEST.md` replays past games using only data from before each tip-off and compares the model
  with DraftKings' closing line. If the model isn't closer to the final scores than the close, its
  "edges" are noise, and the picks report says so at the top.
- Player props are where public models most often have an edge (softer lines, more injury-driven
  moves). Prop prices need an [Odds API](https://the-odds-api.com) key: add it as the `ODDS_API_KEY`
  repository secret. The free tier covers a few nights a month; the $30 tier covers a season.

## What the 2025-26 backtest says

932 games, December to April, each projected with only data from before tip-off:

- **Spreads:** the model misses by 11.48 points a game, DraftKings' close by 11.13. Betting its
  picks went 53.2% over 656 bets (break-even 52.4%), well within luck. No proven edge.
- **Totals:** 15.92 vs 14.58 for the close, 49.4% betting. No edge.
- **Player projections:** slightly better than a last-10-game average (points 4.62 vs 4.70 off,
  pts+reb+ast 6.08 vs 6.20), and calibrated: outcomes land over my line about half the time.

So picks only include markets where the backtest beats the close. Right now that's player props
only, and only once prop prices are connected. Game-line bets switch on by themselves if a
future backtest shows the model beating the close.

## Commands

```bash
pip install -r requirements.txt
python -m nbaparlay backfill --start 2025-10-21          # store past box scores
python -m nbaparlay update                               # catch up, snapshot injuries
python -m nbaparlay picks --out PICKS.md                 # my lines, best bets, parlays
python -m nbaparlay backtest --start 2025-12-01 --end 2026-04-12 --out BACKTEST.md
pytest -q
```

On GitHub: Actions → nba → Run workflow, with task `backfill`, `backtest` or `picks`.
