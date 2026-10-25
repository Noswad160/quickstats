"""Team ratings: opponent-adjusted offense, defense and pace, from box scores before a date.

Points per 100 possessions for team A in a game is modelled as
    league + off[A] + def[B] + home_edge * (+1/2 home, -1/2 away) + b2b * (A on a back-to-back)
and possessions as league_pace + pace[A] + pace[B]. Both are fit by weighted ridge regression,
with each team's older games decayed so ratings follow form, and shrunk toward average when data is thin.
"""
from dataclasses import dataclass

import numpy as np
import pandas as pd

HALF_LIFE_GAMES = 25.0   # a team's own games, so the offseason doesn't erase last season
RIDGE = 6.0              # in "games" of weight pulling each rating toward zero
PACE_RIDGE = 6.0
B2B_PRIOR, B2B_RIDGE = -1.5, 200.0   # points per 100 on a back-to-back; data moves it only with lots of evidence


@dataclass
class Ratings:
    as_of: pd.Timestamp
    league_eff: float          # points per 100 possessions
    league_pace: float         # possessions per team per game
    off: dict[str, float]
    deff: dict[str, float]     # positive = worse defense (opponents score more)
    pace: dict[str, float]
    home_edge: float           # points per 100 swing between home and away
    b2b: float                 # points per 100 for a team on the second night of a back-to-back
    n_games: int

    def expected(self, home: str, away: str, neutral: bool = False,
                 home_b2b: bool = False, away_b2b: bool = False) -> tuple[float, float, float]:
        """(home points, away points, possessions)."""
        poss = self.league_pace + self.pace.get(home, 0) + self.pace.get(away, 0)
        h = 0 if neutral else self.home_edge / 2
        eff_h = self.league_eff + self.off.get(home, 0) + self.deff.get(away, 0) + h + self.b2b * home_b2b
        eff_a = self.league_eff + self.off.get(away, 0) + self.deff.get(home, 0) - h + self.b2b * away_b2b
        return poss * eff_h / 100, poss * eff_a / 100, poss


def add_rest(teams: pd.DataFrame) -> pd.DataFrame:
    """Adds days_rest and b2b to team-game rows."""
    t = teams.sort_values("start").copy()
    t["prev"] = t.groupby("team_id")["start"].shift()
    t["days_rest"] = (t["start"] - t["prev"]).dt.total_seconds() / 86400
    t["b2b"] = t["days_rest"].lt(1.6).fillna(False)
    return t.drop(columns="prev")


def fit(teams: pd.DataFrame, as_of: pd.Timestamp) -> Ratings:
    t = teams[teams["start"] < as_of]
    t = t[t["poss"] > 0]
    if t.empty:
        raise ValueError("no games before as_of")
    games_ago = t.groupby("team_id")["start"].rank(ascending=False, method="first") - 1
    w = 0.5 ** (games_ago / HALF_LIFE_GAMES).to_numpy()
    ids = sorted(set(t["team_id"]) | set(t["opp_id"]))
    ix = {tid: i for i, tid in enumerate(ids)}
    n, k = len(t), len(ids)

    # possessions per team per game: average both teams' estimates
    poss = ((t["poss"] + t["opp_poss"]) / 2).to_numpy()
    eff = (100 * t["pts"] / poss).to_numpy()
    league_eff = float(np.average(eff, weights=w))
    league_pace = float(np.average(poss, weights=w))

    rows = np.arange(n)
    a = t["team_id"].map(ix).to_numpy()
    b = t["opp_id"].map(ix).to_numpy()
    home = np.where(t["home"].to_numpy(), 0.5, -0.5)
    b2b = t["b2b"].to_numpy().astype(float) if "b2b" in t else np.zeros(n)

    X = np.zeros((n, 2 * k + 2))
    X[rows, a] = 1
    X[rows, k + b] = 1
    X[:, 2 * k] = home
    X[:, 2 * k + 1] = b2b
    y = eff - league_eff - B2B_PRIOR * b2b      # fit the back-to-back effect as a deviation from its prior
    reg = np.r_[np.full(2 * k, RIDGE), 1e-3, B2B_RIDGE]
    beta = np.linalg.solve((X * w[:, None]).T @ X + np.diag(reg), (X * w[:, None]).T @ y)
    beta[2 * k + 1] += B2B_PRIOR

    # pace: possessions = league + pace[A] + pace[B]
    P = np.zeros((n, k))
    P[rows, a] = 1
    P[rows, b] += 1
    yp = poss - league_pace
    gamma = np.linalg.solve((P * w[:, None]).T @ P + np.eye(k) * PACE_RIDGE, (P * w[:, None]).T @ yp)

    return Ratings(
        as_of=as_of, league_eff=league_eff, league_pace=league_pace,
        off={tid: float(beta[ix[tid]]) for tid in ids},
        deff={tid: float(beta[k + ix[tid]]) for tid in ids},
        pace={tid: float(gamma[ix[tid]]) for tid in ids},
        home_edge=float(beta[2 * k]), b2b=float(beta[2 * k + 1]), n_games=n // 2,
    )
