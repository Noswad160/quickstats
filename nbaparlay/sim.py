"""Monte Carlo game simulation.

Each draw plays one version of the game:
  1. who plays (questionable players are coin flips weighted by their status),
  2. pace, shared by both teams, and each team's shooting night,
  3. team points, from the team model, cut when key players are missing,
  4. minutes, rescaled to 240 among players who are active, and starters' minutes trimmed in blowouts,
  5. each player's share of his team's points (Dirichlet, so teammates compete for shots),
  6. rebounds, assists, threes, steals, blocks, turnovers from per-minute rates (gamma-Poisson).
Because every leg in a game is read off the same draws, same-game parlays get real correlation.
"""
from dataclasses import dataclass, field

import numpy as np

STATS = ("pts", "reb", "ast", "fg3m", "stl", "blk", "tov")
COMBOS = {"pra": ("pts", "reb", "ast"), "pr": ("pts", "reb"), "pa": ("pts", "ast"), "ra": ("reb", "ast"),
          "sb": ("stl", "blk")}
# gamma-Poisson shape per stat: lower = more game-to-game variation
DISPERSION = {"reb": 12.0, "ast": 8.0, "fg3m": 6.0, "stl": 4.0, "blk": 3.0, "tov": 6.0}


@dataclass
class Params:
    pace_sd: float = 0.04          # game-to-game pace variation (fraction)
    team_eff_sd: float = 0.055     # a team's hot/cold shooting night (fraction)
    team_resid_sd: float = 7.0     # remaining team-points noise
    share_concentration: float = 35.0  # Dirichlet total: higher = steadier scoring shares
    replacement: float = 0.75      # fraction of a missing player's points the team recovers
    blowout_start: float = 12.0    # margin where starters start sitting
    blowout_rate: float = 0.012    # minutes lost per point of margin beyond that
    blowout_floor: float = 0.72
    max_minutes: float = 44.0


@dataclass
class PlayerProj:
    player_id: str
    name: str
    minutes: float                  # expected minutes if he plays
    minutes_sd: float
    rates: dict[str, float]         # per-minute expected stats, keys from STATS
    play_prob: float = 1.0
    starter: bool = False


@dataclass
class TeamProj:
    team_id: str
    name: str
    points: float                   # expected points with the usual roster available
    players: list[PlayerProj] = field(default_factory=list)


@dataclass
class GameProj:
    game_id: str
    home: TeamProj
    away: TeamProj


@dataclass
class TeamSim:
    points: np.ndarray
    played: dict[str, np.ndarray]                # player_id -> bool[n]
    stats: dict[str, dict[str, np.ndarray]]      # player_id -> stat -> int[n]


@dataclass
class GameSim:
    game_id: str
    n: int
    home: TeamSim
    away: TeamSim
    players: dict[str, tuple[str, PlayerProj]]   # player_id -> ("home"|"away", proj)

    @property
    def total(self) -> np.ndarray:
        return self.home.points + self.away.points

    @property
    def margin(self) -> np.ndarray:  # home minus away
        return self.home.points - self.away.points

    def team(self, side: str) -> TeamSim:
        return self.home if side == "home" else self.away

    def player_stat(self, player_id: str, stat: str) -> np.ndarray:
        side, _ = self.players[player_id]
        stats = self.team(side).stats[player_id]
        if stat in COMBOS:
            return sum(stats[s] for s in COMBOS[stat])
        return stats[stat]


def _gamma_poisson(rng, mean: np.ndarray, k: float) -> np.ndarray:
    lam = rng.gamma(k, np.maximum(mean, 1e-9) / k)
    return rng.poisson(lam)


def _team_points(rng, team: TeamProj, avail: np.ndarray, pace: np.ndarray, prm: Params) -> np.ndarray:
    exp_pts = np.array([p.minutes * p.rates.get("pts", 0.0) for p in team.players])
    total = exp_pts.sum() or 1.0
    missing_share = ((~avail) * exp_pts).sum(axis=1) / total
    mean = team.points * (1 - (1 - prm.replacement) * missing_share)
    eff = rng.lognormal(0.0, prm.team_eff_sd, len(pace))
    return np.maximum(60, mean * pace * eff + rng.normal(0, prm.team_resid_sd, len(pace)))


def _minutes(rng, team: TeamProj, avail: np.ndarray, margin: np.ndarray, prm: Params) -> np.ndarray:
    n = avail.shape[0]
    mu = np.array([p.minutes for p in team.players])
    sd = np.array([p.minutes_sd for p in team.players])
    starter = np.array([p.starter for p in team.players])
    m = np.clip(rng.normal(mu, sd, (n, len(mu))), 0, 48) * avail
    # blowouts: starters sit, bench plays more
    cut = np.clip(1 - prm.blowout_rate * np.maximum(0, np.abs(margin) - prm.blowout_start), prm.blowout_floor, 1)
    m = np.where(starter, m * cut[:, None], m)
    total = m.sum(axis=1, keepdims=True)
    m = np.where(total > 0, m * 240 / np.maximum(total, 1e-9), 0)
    return np.minimum(m, prm.max_minutes)


def _team_stats(rng, team: TeamProj, avail, minutes, points, pace, prm: Params) -> dict[str, dict[str, np.ndarray]]:
    n = len(points)
    rate = {s: np.array([p.rates.get(s, 0.0) for p in team.players]) for s in STATS}
    # scoring shares: expected points given these minutes, then Dirichlet noise around them
    w = minutes * rate["pts"]
    w_sum = w.sum(axis=1, keepdims=True)
    share_mean = np.where(w_sum > 0, w / np.maximum(w_sum, 1e-9), 0)
    alpha = np.maximum(share_mean * prm.share_concentration, 1e-6)
    shares = rng.gamma(alpha)
    shares = np.where(minutes > 0, shares, 0)
    shares = shares / np.maximum(shares.sum(axis=1, keepdims=True), 1e-9)
    pts = np.rint(shares * points[:, None]).astype(int)
    # threes move with how much a player scored relative to expectation
    exp_pts_player = np.maximum(share_mean * points[:, None], 1e-9)
    hot = np.where(minutes > 0, (pts / exp_pts_player) ** 0.8, 0)
    out: dict[str, dict[str, np.ndarray]] = {}
    for j, p in enumerate(team.players):
        s = {"pts": pts[:, j]}
        for stat in ("reb", "ast", "stl", "blk", "tov"):
            s[stat] = _gamma_poisson(rng, rate[stat][j] * minutes[:, j] * pace, DISPERSION[stat])
        s["fg3m"] = np.minimum(_gamma_poisson(rng, rate["fg3m"][j] * minutes[:, j] * hot[:, j], DISPERSION["fg3m"]),
                               pts[:, j] // 3)
        for stat in STATS:
            s[stat] = np.where(avail[:, j], s[stat], 0)
        out[p.player_id] = s
    return out


def simulate(game: GameProj, n: int = 10000, seed: int | None = None, prm: Params = Params()) -> GameSim:
    rng = np.random.default_rng(seed)
    pace = rng.lognormal(0.0, prm.pace_sd, n)
    avail = {side: rng.random((n, len(t.players))) < np.array([p.play_prob for p in t.players])
             for side, t in (("home", game.home), ("away", game.away))}
    pts = {side: _team_points(rng, t, avail[side], pace, prm)
           for side, t in (("home", game.home), ("away", game.away))}
    margin = pts["home"] - pts["away"]
    sims = {}
    for side, team in (("home", game.home), ("away", game.away)):
        minutes = _minutes(rng, team, avail[side], margin, prm)
        stats = _team_stats(rng, team, avail[side], minutes, pts[side], pace, prm)
        # team total is the sum of its players' points so props and game lines agree
        team_pts = sum(stats[p.player_id]["pts"] for p in team.players) if team.players else np.rint(pts[side])
        sims[side] = TeamSim(points=np.asarray(team_pts),
                             played={p.player_id: avail[side][:, j] & (minutes[:, j] > 0)
                                     for j, p in enumerate(team.players)},
                             stats=stats)
    players = {p.player_id: (side, p) for side, t in (("home", game.home), ("away", game.away)) for p in t.players}
    return GameSim(game.game_id, n, sims["home"], sims["away"], players)
