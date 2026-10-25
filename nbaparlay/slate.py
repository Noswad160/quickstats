"""Run a slate: simulate every game, set our lines, price what the books offer, build parlays."""
import logging

import numpy as np
import pandas as pd

from . import markets, odds, oddsapi, parlay
from .markets import Leg, my_line, price
from .project import Projector
from .sim import GameSim, simulate
from .store import Box

log = logging.getLogger(__name__)
SIMS = 10000
LINE_STATS = ("pts", "reb", "ast", "fg3m", "pra", "pr", "pa", "ra", "stl", "blk", "tov")


def game_lines(g: dict, lines: dict | None) -> list[Leg]:
    """DraftKings spread/total/moneyline legs from ESPN, current ('close') numbers."""
    if not lines:
        return []
    gid, out = g["game_id"], []
    sp = lines.get("spread_home_close")
    if sp is not None:
        if lines.get("spread_home_odds_close") is not None:
            out.append(Leg(gid, "spread", "home", sp, lines["spread_home_odds_close"], "DraftKings", team=g["home_abbr"]))
        if lines.get("spread_away_odds_close") is not None:
            out.append(Leg(gid, "spread", "away", -sp, lines["spread_away_odds_close"], "DraftKings", team=g["away_abbr"]))
    tot = lines.get("total_close")
    if tot is not None:
        for side in ("over", "under"):
            if lines.get(f"{side}_odds_close") is not None:
                out.append(Leg(gid, "total", side, tot, lines[f"{side}_odds_close"], "DraftKings"))
    for side, abbr in (("home", g["home_abbr"]), ("away", g["away_abbr"])):
        if lines.get(f"ml_{side}_close") is not None:
            out.append(Leg(gid, "moneyline", side, None, lines[f"ml_{side}_close"], "DraftKings", team=abbr))
    return out


def my_lines(g: dict, sim: GameSim) -> dict:
    """Our numbers for the game and every player, before looking at any book."""
    p_home = float(np.mean(markets.Leg(g["game_id"], "moneyline", "home", None, None).outcome(sim) == markets.WIN))
    game = {
        "game_id": g["game_id"], "matchup": f"{g['away_abbr']} @ {g['home_abbr']}", "start": g["start"],
        "home": g["home_abbr"], "away": g["away_abbr"],
        "home_pts": round(float(np.mean(sim.home.points)), 1), "away_pts": round(float(np.mean(sim.away.points)), 1),
        "spread_home": -my_line(sim.margin), "total": my_line(sim.total),
        "ml_home": odds.fair_american(p_home), "ml_away": odds.fair_american(1 - p_home), "p_home": round(p_home, 3),
    }
    players = []
    for pid, (side, proj) in sim.players.items():
        played = sim.team(side).played[pid]
        if proj.play_prob <= 0 or not played.any():
            continue
        row = {"player_id": pid, "player": proj.name, "team": g[f"{side}_abbr"], "game_id": g["game_id"],
               "minutes": round(proj.minutes, 1), "play_prob": round(proj.play_prob, 2)}
        for stat in LINE_STATS:
            x = sim.player_stat(pid, stat)[played]
            line = my_line(x)
            p_over = float(np.mean(x > line))
            row[stat] = {"mean": round(float(np.mean(x)), 2), "line": line, "p_over": round(p_over, 3),
                         "over": odds.fair_american(p_over), "under": odds.fair_american(1 - p_over)}
        players.append(row)
    players.sort(key=lambda r: (r["team"], -r["minutes"]))
    return {"game": game, "players": players}


def run(box: Box, slate: list[dict], injuries: list[dict], as_of: pd.Timestamp | None = None,
        props: bool = True, n: int = SIMS, min_edge: float = 0.03) -> dict:
    as_of = as_of or pd.Timestamp.now(tz="UTC")
    proj = Projector(box, as_of, injuries)
    sims, lines, legs = {}, [], []
    for i, entry in enumerate(slate):
        g = entry["game"]
        try:
            gp = proj.game(g)
        except Exception:
            log.exception("projection failed for %s", g["game_id"])
            continue
        if not gp.home.players or not gp.away.players:
            log.warning("no player history for %s; skipping", g["game_id"])
            continue
        sim = simulate(gp, n=n, seed=int(g["game_id"]) % 2**32 + i)
        sims[g["game_id"]] = sim
        lines.append(my_lines(g, sim))
        legs += game_lines(g, entry.get("lines"))
    if props:
        try:
            legs += oddsapi.fetch_props([e["game"] for e in slate], sims)
        except Exception:
            log.exception("props fetch failed")
    priced = [price(leg, sims[leg.game_id]) for leg in legs if leg.game_id in sims]
    singles = parlay.candidates(priced, min_edge=min_edge)
    parlays = parlay.build(singles, sims) if len(singles) >= 2 else []
    return {"as_of": as_of.isoformat(), "lines": lines, "priced": priced, "singles": singles, "parlays": parlays,
            "ratings": proj.ratings}
