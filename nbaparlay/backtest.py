"""Replay past games with only what was known before tip-off, and grade the model against
DraftKings' closing lines and the actual results.

The closing line is the sharpest public number there is. A model that can't get closer to the
final score than the close, or win more than 52.4% of its bets against it at -110, has no edge.
"""
import logging

import numpy as np
import pandas as pd

from . import odds
from .markets import WIN, Leg
from .project import Projector
from .sim import simulate
from .store import Box

log = logging.getLogger(__name__)
BREAK_EVEN = 0.5238  # win rate needed at -110


def run(box: Box, start: str, end: str, n: int = 3000, min_history_games: int = 150) -> pd.DataFrame:
    g = box.games[(box.games["date"] >= start) & (box.games["date"] <= end) & box.games["completed"]]
    g = g.merge(box.lines, on="game_id", how="inner") if not box.lines.empty else g.iloc[0:0]
    rows, player_rows = [], []
    actual_by = {(r.game_id, r.player_id): r for r in box.players.itertuples(index=False)}
    for day, day_games in g.groupby("date"):
        as_of = day_games["start"].min() - pd.Timedelta(minutes=30)
        if (box.games["start"] < as_of).sum() < min_history_games:
            continue
        try:
            proj = Projector(box, as_of)
        except ValueError:
            continue
        for _, r in day_games.iterrows():
            try:
                gp = proj.game(r.to_dict())
            except Exception:
                log.exception("projection failed %s", r["game_id"])
                continue
            if not gp.home.players or not gp.away.players:
                continue
            sim = simulate(gp, n=n, seed=int(r["game_id"]) % 2**32)
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
                player_rows.append({"game_id": r["game_id"], "player_id": pid, "date": day,
                                    **{f"model_{st}": float(np.mean(sim.player_stat(pid, st)[played])) for st in ("pts", "reb", "ast")},
                                    **{f"actual_{st}": int(getattr(a, st)) for st in ("pts", "reb", "ast")}})
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
        for stat in ("pts", "reb", "ast"):
            s[f"player_{stat}_mae"] = float(np.mean(np.abs(pl[f"model_{stat}"] - pl[f"actual_{stat}"])))
        s["player_games"] = len(pl)
    return s
