"""Data on disk: one gzipped JSON file per date of finished games, plus snapshots.

  <root>/box/YYYY-MM-DD.json.gz        parsed summaries of that date's finished games
  <root>/injuries/<UTC time>.json.gz   injury report snapshots
  <root>/slates/<UTC time>.json.gz     upcoming games + DraftKings lines + our projections at that time
"""
import gzip
import json
import os
from datetime import datetime, timezone

import pandas as pd


def utcnow() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")


def _write(path: str, obj) -> str:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with gzip.open(path, "wt", encoding="utf-8") as f:
        json.dump(obj, f, separators=(",", ":"))
    return path


def _read(path: str):
    with gzip.open(path, "rt", encoding="utf-8") as f:
        return json.load(f)


def box_path(root: str, date: str) -> str:
    return os.path.join(root, "box", f"{date}.json.gz")


def save_box(root: str, date: str, games: list[dict]) -> str:
    return _write(box_path(root, date), games)


def has_box(root: str, date: str) -> bool:
    return os.path.exists(box_path(root, date))


def save_snapshot(root: str, kind: str, obj, ts: str | None = None) -> str:
    ts = (ts or utcnow()).replace(":", "")
    return _write(os.path.join(root, kind, f"{ts}.json.gz"), obj)


def latest_snapshot(root: str, kind: str):
    d = os.path.join(root, kind)
    if not os.path.isdir(d):
        return None
    files = sorted(f for f in os.listdir(d) if f.endswith(".json.gz"))
    return _read(os.path.join(d, files[-1])) if files else None


def snapshots(root: str, kind: str):
    d = os.path.join(root, kind)
    if not os.path.isdir(d):
        return
    for f in sorted(os.listdir(d)):
        if f.endswith(".json.gz"):
            yield f.removesuffix(".json.gz"), _read(os.path.join(d, f))


class Box:
    """All stored finished games as DataFrames."""

    def __init__(self, games: pd.DataFrame, teams: pd.DataFrame, players: pd.DataFrame, lines: pd.DataFrame):
        self.games, self.teams, self.players, self.lines = games, teams, players, lines


def load_box(root: str) -> Box:
    games, teams, players, lines = [], [], [], []
    d = os.path.join(root, "box")
    for f in sorted(os.listdir(d)) if os.path.isdir(d) else []:
        if not f.endswith(".json.gz"):
            continue
        date = f[:10]
        for g in _read(os.path.join(d, f)):
            games.append({**g["game"], "date": date})
            teams.extend(g["teams"])
            players.extend(g["players"])
            if g.get("lines"):
                lines.append(g["lines"])
    gdf = pd.DataFrame(games)
    if gdf.empty:
        return Box(gdf, pd.DataFrame(), pd.DataFrame(), pd.DataFrame())
    gdf["start"] = pd.to_datetime(gdf["start"], utc=True)
    gdf = gdf.drop_duplicates("game_id", keep="last")
    tdf = pd.DataFrame(teams).drop_duplicates(["game_id", "team_id"], keep="last")
    pdf = pd.DataFrame(players).drop_duplicates(["game_id", "player_id"], keep="last")
    meta = gdf[["game_id", "start", "date", "season", "season_type"]]
    tdf = tdf.merge(meta, on="game_id")
    pdf = pdf.merge(meta, on="game_id")
    # each team row gets its opponent's id and points for convenience
    opp = tdf[["game_id", "team_id", "pts", "poss"]].rename(
        columns={"team_id": "opp_id", "pts": "opp_pts", "poss": "opp_poss"})
    tdf = tdf.merge(opp, on="game_id")
    tdf = tdf[tdf["team_id"] != tdf["opp_id"]].reset_index(drop=True)
    ldf = pd.DataFrame(lines).drop_duplicates("game_id", keep="last") if lines else pd.DataFrame()
    return Box(gdf.reset_index(drop=True), tdf, pdf.reset_index(drop=True), ldf)
