"""Markdown reports: today's lines and picks, and the backtest."""
from .odds import fmt_american
from .sim import COMBOS

MAIN_STATS = ("pts", "reb", "ast", "fg3m", "pra")


def _pct(p) -> str:
    return "—" if p is None else f"{p * 100:.0f}%"


def slate_md(res: dict, backtest: dict | None = None) -> str:
    out = ["# NBA lines and parlays", "", f"Generated {res['as_of'][:16].replace('T', ' ')} UTC.", ""]
    if backtest and backtest.get("games"):
        verdict = ("beats" if backtest.get("spread_mae_model", 9e9) < backtest.get("spread_mae_close", 0)
                   else "does not beat")
        out += [f"**Backtest: over {backtest['games']} past games the model {verdict} DraftKings' closing spread** "
                f"(off by {backtest.get('spread_mae_model', 0):.2f} points per game vs the close's "
                f"{backtest.get('spread_mae_close', 0):.2f}). Treat the picks below accordingly.", ""]
    out += ["Every number here is the model's own line, set before comparing with any book. "
            "Edge = expected profit per $1 at the book's price if the model is right.", ""]

    if res["singles"]:
        out += ["## Best single bets", "", "| bet | book | price | model chance | my price | edge |",
                "|---|---|---|---|---|---|"]
        for p in res["singles"][:25]:
            out.append(f"| {p.leg.label} | {p.leg.book} | {fmt_american(p.leg.price)} | {_pct(p.p_win)} | "
                       f"{fmt_american(p.fair)} | {p.ev * 100:+.1f}% |")
        out.append("")
    cross = [x for x in res["parlays"] if not x.same_game]
    sgp = [x for x in res["parlays"] if x.same_game]
    if cross:
        out += ["## Parlays (different games)", "", "| legs | pays | model chance | my price | edge | ¼-Kelly stake |",
                "|---|---|---|---|---|---|"]
        for x in cross[:10]:
            out.append(f"| {x.label} | {fmt_american(x.book_price)} | {_pct(x.p_hit)} | {fmt_american(x.fair_price)} | "
                       f"{x.ev * 100:+.1f}% | {x.kelly / 4 * 100:.1f}% of bankroll |")
        out.append("")
    if sgp:
        out += ["## Same-game parlays", "",
                "Books reprice these for correlation, so there's no fixed payout. Only bet one if the book offers "
                "more than **my price**.", "", "| legs | model chance | my price |", "|---|---|---|"]
        for x in sgp[:10]:
            out.append(f"| {x.label} | {_pct(x.p_hit)} | {fmt_american(x.fair_price)} |")
        out.append("")
    if not res["singles"]:
        out += ["_No bet clears the minimum edge right now._", ""]

    out += ["## My lines", ""]
    for gl in res["lines"]:
        g = gl["game"]
        out += [f"### {g['matchup']}  ·  {g['start'][:16].replace('T', ' ')} UTC", "",
                f"Score {g['away']} {g['away_pts']:.0f}, {g['home']} {g['home_pts']:.0f} · "
                f"spread {g['home']} {g['spread_home']:+g} · total {g['total']:g} · "
                f"moneyline {g['home']} {fmt_american(g['ml_home'])} / {g['away']} {fmt_american(g['ml_away'])}", "",
                "| player | team | min | plays | " + " | ".join(MAIN_STATS) + " |",
                "|---|---|---|---|" + "---|" * len(MAIN_STATS)]
        for p in gl["players"]:
            cells = [f"{p[s]['line']:g} ({fmt_american(p[s]['over'])})" for s in MAIN_STATS]
            out.append(f"| {p['player']} | {p['team']} | {p['minutes']:.0f} | {_pct(p['play_prob'])} | " + " | ".join(cells) + " |")
        out.append("")
    out += ["Lines are shown as `line (my over price)`. Combos: " + ", ".join(f"{k} = {'+'.join(v)}" for k, v in COMBOS.items())]
    return "\n".join(out) + "\n"


def backtest_md(s: dict, start: str, end: str) -> str:
    if not s.get("games"):
        return "# Backtest\n\n_No games with closing lines in range._\n"
    def f(k, fmt="{:.2f}"):
        v = s.get(k)
        return "—" if v is None else fmt.format(v)
    lines = ["# Backtest", "", f"{s['games']} games from {start} to {end}, each projected with only data from before tip-off.", "",
             "| | model | DraftKings close |", "|---|---|---|",
             f"| spread: average miss vs final margin (pts) | {f('spread_mae_model')} | {f('spread_mae_close')} |",
             f"| total: average miss vs final total (pts) | {f('total_mae_model')} | {f('total_mae_close')} |", "",
             "Betting the side the model gives at least 55%, at -110 (break-even is 52.4%):", "",
             "| market | bets | win rate | ROI |", "|---|---|---|---|",
             f"| spread | {s.get('spread_bets', 0)} | {f('spread_win_rate', '{:.1%}')} | {f('spread_roi_at_-110', '{:+.1%}')} |",
             f"| total | {s.get('total_bets', 0)} | {f('total_win_rate', '{:.1%}')} | {f('total_roi_at_-110', '{:+.1%}')} |", ""]
    if s.get("player_games"):
        lines += [f"Player projections over {s['player_games']} player-games: average miss "
                  f"{f('player_pts_mae', '{:.1f}')} points, {f('player_reb_mae', '{:.1f}')} rebounds, "
                  f"{f('player_ast_mae', '{:.1f}')} assists.", ""]
    return "\n".join(lines) + "\n"
