"""Bets as functions of a simulated game: win / push / lose per draw.

A push (exact number, or a player who doesn't play on a prop) refunds the stake, as books do.
"""
from dataclasses import dataclass

import numpy as np

from . import odds
from .sim import COMBOS, STATS, GameSim

WIN, PUSH, LOSE = 1, 0, -1
PROP_STATS = STATS + tuple(COMBOS)
STAT_NAMES = {"pts": "points", "reb": "rebounds", "ast": "assists", "fg3m": "threes", "stl": "steals",
              "blk": "blocks", "tov": "turnovers", "pra": "pts+reb+ast", "pr": "pts+reb", "pa": "pts+ast",
              "ra": "reb+ast", "sb": "steals+blocks"}


@dataclass(frozen=True)
class Leg:
    game_id: str
    market: str          # prop | spread | total | moneyline | team_total
    side: str            # over/under, home/away
    line: float | None
    price: float | None  # American odds offered, if any
    book: str = ""
    player_id: str = ""
    player: str = ""
    stat: str = ""
    team: str = ""       # team abbreviation for spread/moneyline/team_total
    team_side: str = ""  # home | away, for team totals (whose side is over/under)

    @property
    def label(self) -> str:
        if self.market == "prop":
            return f"{self.player} {self.side} {self.line:g} {STAT_NAMES.get(self.stat, self.stat)}"
        if self.market == "total":
            return f"Game {self.side} {self.line:g}"
        if self.market == "team_total":
            return f"{self.team} team total {self.side} {self.line:g}"
        if self.market == "spread":
            return f"{self.team} {self.line:+g}"
        return f"{self.team} moneyline"

    def outcome(self, sim: GameSim) -> np.ndarray:
        if self.market == "prop":
            side, _ = sim.players[self.player_id]
            x = sim.player_stat(self.player_id, self.stat)
            r = _over_under(x, self.line, self.side)
            return np.where(sim.team(side).played[self.player_id], r, PUSH)
        if self.market == "total":
            return _over_under(sim.total, self.line, self.side)
        if self.market == "team_total":
            return _over_under(sim.team(self.team_side).points, self.line, self.side)
        margin = sim.margin if self.side == "home" else -sim.margin
        if self.market == "spread":
            return np.sign(margin + self.line).astype(int)
        if self.market == "moneyline":
            # a tie after regulation goes to overtime: call it a coin flip, split evenly across draws
            home_wins_ot = np.arange(len(margin)) % 2 == 0
            flip = np.where(home_wins_ot == (self.side == "home"), WIN, LOSE)
            return np.where(margin > 0, WIN, np.where(margin < 0, LOSE, flip))
        raise ValueError(self.market)


def _over_under(x: np.ndarray, line: float, side: str) -> np.ndarray:
    diff = x - line if side == "over" else line - x
    return np.sign(diff).astype(int)


@dataclass
class Priced:
    leg: Leg
    p_win: float
    p_push: float

    @property
    def p_lose(self) -> float:
        return 1 - self.p_win - self.p_push

    @property
    def fair(self) -> int:
        """Our no-vig price, ignoring pushes."""
        decided = self.p_win + self.p_lose
        return odds.fair_american(self.p_win / decided if decided else 0.5)

    @property
    def ev(self) -> float | None:
        if self.leg.price is None:
            return None
        return self.p_win * (odds.american_to_decimal(self.leg.price) - 1) - self.p_lose


def price(leg: Leg, sim: GameSim) -> Priced:
    o = leg.outcome(sim)
    return Priced(leg, float(np.mean(o == WIN)), float(np.mean(o == PUSH)))


def my_line(x: np.ndarray, played: np.ndarray | None = None) -> float:
    """The half-point line closest to an even split: where we'd set it."""
    x = x[played] if played is not None and played.any() else x
    med = float(np.median(x))
    lo = np.floor(med) + 0.5
    cands = (lo - 1, lo, lo + 1)
    return min(cands, key=lambda c: abs(float(np.mean(x > c)) - 0.5))
