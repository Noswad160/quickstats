"""Turn an upcoming game into simulation inputs: team points from ratings, players from box scores."""
import pandas as pd

from . import player, team
from .sim import GameProj, TeamProj
from .store import Box


class Projector:
    """Fits everything once for a point in time, then projects any game after it."""

    def __init__(self, box: Box, as_of: pd.Timestamp, injuries: list[dict] | None = None):
        self.box, self.as_of = box, as_of
        self.teams = team.add_rest(box.teams)
        self.ratings = team.fit(self.teams, as_of)
        self.hist = player.History(box.players, self.teams, as_of)
        self.priors = player.league_rates(box.players[box.players["start"] < as_of].tail(40000))
        self.opp = player.opponent_factors(self.teams, as_of)
        self.injuries = {i["player_id"]: i["status"] for i in (injuries or [])}
        self.last_game = self.teams[self.teams["start"] < as_of].groupby("team_id")["start"].max()

    def _b2b(self, team_id: str, start: pd.Timestamp) -> bool:
        last = self.last_game.get(team_id)
        return last is not None and (start - last).total_seconds() < 1.6 * 86400

    def game(self, g: dict) -> GameProj:
        start = pd.Timestamp(g["start"])
        h, a = g["home_id"], g["away_id"]
        hp, ap, poss = self.ratings.expected(h, a, g.get("neutral", False), self._b2b(h, start), self._b2b(a, start))
        pace_factor = poss / self.ratings.league_pace
        teams = {}
        for side, tid, oid, pts in (("home", h, a, hp), ("away", a, h, ap)):
            players = player.project_team(self.hist, tid, oid, self.injuries, self.priors, self.opp, pace_factor)
            teams[side] = TeamProj(tid, g.get(f"{side}_abbr", tid), pts, players)
        return GameProj(g["game_id"], teams["home"], teams["away"])
