"""Replay past games with only what was known before tip-off, and grade the model against
DraftKings' closing lines and the actual results.

The closing line is the sharpest public number there is. A model that can't get closer to the
final score than the close, or win more than 52.4% of its bets against it at -110, has no edge.
"""
import logging

import numpy as np
import pandas as pd

from . import odds
from .markets import WIN, Leg, my_line
from .project import Projector
from .sim import COMBOS, Params, simulate
from .store import Box

log = logging.getLogger(__name__)
BREAK_EVEN = 0.5238  # win rate needed at -110
PROP_CHECK = ("pts", "reb", "ast", "fg3m", "pra")


def run(box: Box, start: str, end: str, n: int = 3000, min_history_games: int = 150,
        known_inactives: bool = True, params: Params = Params()) -> pd.DataFrame:
    """known_inactives: treat players missing from a game's box score as listed Out beforehand.
    There's no stored history of injury reports, and nearly every inactive is announced before
    tip-off, so this stands in for the report the books (and live picks) see. Coach's-decision
    benchings stay unknown, as they are pregame."""
    g = box.games[(box.games["date"] >= start) & (box.games["date"] <= end) & box.games["completed"]]
    g = g.merge(box.lines, on="game_id", how="inner") if not box.lines.empty else g.iloc[0:0]
    rows, player_rows = [], []
    actual_by = {(r.game_id, r.player_id): r for r in box.players.itertuples(index=False)}
    listed = box.players.groupby("game_id")["player_id"].apply(set).to_dict()
    for day, day_games in g.groupby("date"):
        as_of = day_games["start"].min() - pd.Timedelta(minutes=30)
        if (box.games["start"] < as_of).sum() < min_history_games:
            continue
        try:
            proj = Projector(box, as_of)
        except ValueError:
            continue
        for _, r in day_games.iterrows():
            if known_inactives:
                in_box = listed.get(r["game_id"], set())
                for tid in (r["home_id"], r["away_id"]):
                    for pid in proj.hist.roster(tid):
                        if pid not in in_box:
                            proj.injuries[pid] = "Out"
            try:
                gp = proj.game(r.to_dict())
            except Exception:
                log.exception("projection failed %s", r["game_id"])
                continue
            if not gp.home.players or not gp.away.players:
                continue
            sim = simulate(gp, n=n, seed=int(r["game_id"]) % 2**32, prm=params)
            row = {"date": day, "game_id": r["game_id"], "home": r["home_abbr"], "away": r["away_abbr"],
                   "model_margin": float(np.mean(sim.margin)), "model_total": float(np.mean(sim.total)),
                   "actual_margin": r["home_pts"] - r["away_pts"], "actual_total": r["home_pts"] + r["away_pts"]}
            sp, tot = r.get("spread_home_close"), r.get("total_close")
            if pd.notna(sp):
                row["close_margin"] = -sp
                o = Leg(r["game_id"], "spread", "home", sp, None).outcome(sim)
                row["p_home_cover"] = float(np.mean(o == WIN) / max(np.mean(o != 0), 1e-9))
                row["home_covered"] = np.sign(row["actual_margin"] + sp)
            if pd.notna(tot):
                row["close_total"] = tot
                o = Leg(r["game_id"], "total", "over", tot, None).outcome(sim)
                row["p_over"] = float(np.mean(o == WIN) / max(np.mean(o != 0), 1e-9))
                row["went_over"] = np.sign(row["actual_total"] - tot)
            rows.append(row)
            for pid, (side, _) in sim.players.items():
                a = actual_by.get((r["game_id"], pid))
                played = sim.team(side).played[pid]
                if a is None or a.min <= 0 or not played.any():
                    continue
                row_p = {"game_id": r["game_id"], "player_id": pid, "date": day}
                past = proj.hist.by_player.get(pid)
                past = past[past["min"] > 0].tail(10) if past is not None else None
                for st in PROP_CHECK:
                    x = sim.player_stat(pid, st)[played]
                    actual_v = int(sum(getattr(a, c) for c in COMBOS[st])) if st in COMBOS else int(getattr(a, st))
                    row_p[f"model_{st}"] = float(np.mean(x))
                    if past is not None and len(past):  # naive baseline: his last-10-game average
                        cols = COMBOS.get(st, (st,))
                        row_p[f"naive_{st}"] = float(past[list(cols)].sum(axis=1).mean())
                    row_p[f"actual_{st}"] = actual_v
                    # probability integral transform: uniform on [0, 1] when the distribution is honest
                    row_p[f"pit_{st}"] = float(np.mean(x < actual_v) + 0.5 * np.mean(x == actual_v))
                    line = my_line(x)
                    row_p[f"p_over_{st}"] = float(np.mean(x > line))
                    row_p[f"over_{st}"] = int(actual_v > line)
                player_rows.append(row_p)
        log.info("backtest %s: %d games", day, len(day_games))
    out = pd.DataFrame(rows)
    out.attrs["players"] = pd.DataFrame(player_rows)
    return out


def summarize(bt: pd.DataFrame, threshold: float = 0.55) -> dict:
    """Headline numbers. Bets are placed when the model's probability passes `threshold`."""
    if bt.empty:
        return {"games": 0}
    s = {"games": len(bt)}
    for kind, model, close, actual in (("spread", "model_margin", "close_margin", "actual_margin"),
                                       ("total", "model_total", "close_total", "actual_total")):
        d = bt.dropna(subset=[close]) if close in bt else bt.iloc[0:0]
        if d.empty:
            continue
        s[f"{kind}_mae_model"] = float(np.mean(np.abs(d[model] - d[actual])))
        s[f"{kind}_mae_close"] = float(np.mean(np.abs(d[close] - d[actual])))
        p_col, res_col = ("p_home_cover", "home_covered") if kind == "spread" else ("p_over", "went_over")
        d = d[d[res_col] != 0]
        pick_yes = d[p_col] >= threshold
        pick_no = d[p_col] <= 1 - threshold
        wins = int(((pick_yes & (d[res_col] > 0)) | (pick_no & (d[res_col] < 0))).sum())
        bets = int((pick_yes | pick_no).sum())
        s[f"{kind}_bets"] = bets
        s[f"{kind}_win_rate"] = wins / bets if bets else None
        s[f"{kind}_roi_at_-110"] = (wins * (odds.american_to_decimal(-110) - 1) - (bets - wins)) / bets if bets else None
        # calibration: how well the model's probabilities score vs a coin flip
        y = (d[res_col] > 0).astype(float)
        s[f"{kind}_brier_model"] = float(np.mean((d[p_col] - y) ** 2))
        s[f"{kind}_brier_coinflip"] = 0.25
    pl = bt.attrs.get("players")
    if pl is not None and not pl.empty:
        for stat in PROP_CHECK:
            s[f"player_{stat}_mae"] = float(np.mean(np.abs(pl[f"model_{stat}"] - pl[f"actual_{stat}"])))
            if f"naive_{stat}" in pl:
                ok = pl[f"naive_{stat}"].notna()
                s[f"player_{stat}_mae_naive"] = float(np.mean(np.abs(pl.loc[ok, f"naive_{stat}"] - pl.loc[ok, f"actual_{stat}"])))
                s[f"player_{stat}_mae_model_same"] = float(np.mean(np.abs(pl.loc[ok, f"model_{stat}"] - pl.loc[ok, f"actual_{stat}"])))
            s[f"player_{stat}_model_p_over"] = float(np.mean(pl[f"p_over_{stat}"]))
            pit = pl[f"pit_{stat}"]
            # share of outcomes in the model's outer 10% tails on each side: 0.20 total when honest
            s[f"player_{stat}_tails"] = float(np.mean((pit < 0.1) | (pit > 0.9)))
            s[f"player_{stat}_over_my_line"] = float(np.mean(pl[f"over_{stat}"]))
        s["player_games"] = len(pl)
    return s
