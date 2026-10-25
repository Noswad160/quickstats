"""Player projections for one team in one game, from box scores before tip-off."""
import numpy as np
import pandas as pd

from .sim import STATS, PlayerProj

MIN_HALF_LIFE = 4.0        # games: minutes follow role changes quickly
RATE_HALF_LIFE = 15.0      # games: per-minute production is steadier
RATE_GAMES = 50
PRIOR_MINUTES = 150.0      # shrink rates toward the starter/bench average by this many minutes
ROSTER_DAYS = 45
STATUS_PLAY_PROB = {"Out": 0.0, "Doubtful": 0.15, "Questionable": 0.5, "Day-To-Day": 0.6, "Probable": 0.9}
OPP_WEIGHT = 0.5           # how much of an opponent's allowed-rate difference passes through


def _decay(n: int, half_life: float) -> np.ndarray:
    return 0.5 ** (np.arange(n)[::-1] / half_life)


def league_rates(players: pd.DataFrame) -> dict[bool, dict[str, float]]:
    """Per-minute averages for starters and bench players."""
    p = players[players["min"] > 0]
    out = {}
    for starter in (True, False):
        g = p[p["starter"] == starter]
        mins = g["min"].sum() or 1.0
        out[starter] = {s: g[s].sum() / mins for s in STATS}
    return out


def opponent_factors(teams: pd.DataFrame, as_of: pd.Timestamp, half_life_days: float = 40.0) -> dict[str, dict[str, float]]:
    """How much more (>1) or less of each stat a defense allows per possession than average."""
    t = teams[teams["start"] < as_of].copy()
    if t.empty:
        return {}
    w = 0.5 ** ((as_of - t["start"]).dt.total_seconds() / 86400 / half_life_days)
    out: dict[str, dict[str, float]] = {}
    league = {s: np.average(t[s] / t["poss"].clip(lower=1), weights=w) for s in ("reb", "ast", "fg3m", "stl", "blk", "tov")}
    t["w"] = w
    for opp, g in t.groupby("opp_id"):  # rows are the offense; opp_id is the defense allowing it
        f = {}
        for s, lg in league.items():
            allowed = np.average(g[s] / g["poss"].clip(lower=1), weights=g["w"])
            n_eff = g["w"].sum()
            shrunk = (allowed * n_eff + lg * 5) / (n_eff + 5)
            f[s] = (shrunk / lg) ** OPP_WEIGHT if lg else 1.0
        out[opp] = f
    return out


class History:
    """Box-score rows before a point in time, indexed by player and team."""

    def __init__(self, players: pd.DataFrame, teams: pd.DataFrame, as_of: pd.Timestamp):
        p = players[players["start"] < as_of].sort_values("start")
        self.as_of = as_of
        self.by_player = {pid: g for pid, g in p.groupby("player_id", sort=False)}
        # current team = team of his latest appearance; on the roster if he's played for them recently
        latest = p.groupby("player_id").tail(1)
        recent = latest[latest["start"] > as_of - pd.Timedelta(days=ROSTER_DAYS)]
        played = p[(p["min"] > 0) & (p["start"] > as_of - pd.Timedelta(days=ROSTER_DAYS))]
        played_for = set(zip(played["player_id"], played["team_id"]))
        recent = recent[[(pid, tid) in played_for for pid, tid in zip(recent["player_id"], recent["team_id"])]]
        self.rosters = recent.groupby("team_id")["player_id"].apply(list).to_dict()
        t = teams[teams["start"] < as_of].sort_values("start")
        self.team_games = {tid: g["game_id"] for tid, g in t.groupby("team_id", sort=False)}

    def roster(self, team_id: str) -> list[str]:
        """Players whose latest game was for this team, within the last ROSTER_DAYS."""
        return self.rosters.get(team_id, [])


def project_player(hist: pd.DataFrame, team_games: pd.Series, priors: dict[bool, dict[str, float]],
                   status: str | None, opp: dict[str, float], pace_factor: float) -> PlayerProj | None:
    """hist: this player's rows before tip-off, oldest first. team_games: his current team's recent game ids."""
    played = hist[hist["min"] > 0]
    if played.empty:
        return None
    last = played.tail(10)
    wm = _decay(len(last), MIN_HALF_LIFE)
    mu = float(np.average(last["min"], weights=wm))
    sd = float(np.sqrt(np.average((last["min"] - mu) ** 2, weights=wm))) if len(last) > 1 else 6.0
    starter = bool(played.tail(5)["starter"].mean() >= 0.5)

    r = played.tail(RATE_GAMES)
    wr = _decay(len(r), RATE_HALF_LIFE) * r["min"].to_numpy()
    mins = wr.sum()  # effective (decayed) minutes behind the rates
    prior = priors[starter]
    rates = {}
    for s in STATS:
        observed = float(np.sum(wr * (r[s] / r["min"]).to_numpy()) / max(wr.sum(), 1e-9))
        shrunk = (observed * mins + prior[s] * PRIOR_MINUTES) / (mins + PRIOR_MINUTES)
        if s != "pts":
            shrunk *= opp.get(s, 1.0) * pace_factor
        rates[s] = shrunk

    # how often he's played in his team's recent games, for players without an injury tag
    recent_team = set(team_games.tail(5))
    appeared = hist[hist["game_id"].isin(recent_team) & (hist["min"] > 0)]["game_id"].nunique()
    seen = len(recent_team & set(hist["game_id"])) or 1
    usual = min(1.0, appeared / seen)                 # what the team ratings already assume
    base = max(0.25, usual)                           # untagged players: keep some chance he suits up
    play_prob = STATUS_PLAY_PROB.get(status, base) if status else base

    row = hist.iloc[-1]
    return PlayerProj(player_id=str(row["player_id"]), name=str(row["name"]), minutes=mu,
                      minutes_sd=max(3.0, sd), rates=rates, play_prob=play_prob, starter=starter, usual_prob=usual)


def project_team(hist: History, team_id: str, opp_id: str, injuries: dict[str, str], priors, opp_factors,
                 pace_factor: float, min_minutes: float = 4.0) -> list[PlayerProj]:
    games = hist.team_games.get(team_id, pd.Series(dtype=str))
    out = []
    for pid in hist.roster(team_id):
        proj = project_player(hist.by_player[pid], games, priors, injuries.get(pid),
                              opp_factors.get(opp_id, {}), pace_factor)
        if proj and proj.minutes >= min_minutes:
            out.append(proj)
    return sorted(out, key=lambda x: -x.minutes)
