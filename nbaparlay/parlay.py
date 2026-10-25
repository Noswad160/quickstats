"""Find parlays the model says are worth more than they pay.

A parlay is only +EV when its legs are. This builds parlays from legs that each beat their price,
prices them jointly off the simulations (legs in the same game share draws, so their correlation is
real, not assumed), and ranks them by expected value.

Cross-game parlays pay the product of the legs' prices. Same-game parlays don't: books reprice them
for correlation, so for those we report the fair price you'd need the book to offer.
"""
from dataclasses import dataclass
from itertools import combinations

import numpy as np

from . import odds
from .markets import LOSE, PUSH, WIN, Priced
from .sim import GameSim


@dataclass
class Parlay:
    legs: list[Priced]
    p_hit: float          # every leg wins or pushes, and at least one wins
    ev: float | None      # per $1, at the product of the legs' prices (cross-game only)
    book_price: float | None
    fair_price: int
    same_game: bool

    @property
    def kelly(self) -> float:
        if self.book_price is None:
            return 0.0
        return odds.kelly(self.p_hit, self.book_price)

    @property
    def label(self) -> str:
        return " + ".join(p.leg.label for p in self.legs)


def _key(p: Priced) -> tuple:
    """Legs with the same key can't go in one parlay: they're the same bet, or nearly so."""
    leg = p.leg
    if leg.market == "prop":
        return ("prop", leg.player_id, leg.stat)
    if leg.market in ("spread", "moneyline"):
        return ("result", leg.game_id)          # a team's spread and moneyline are close to one bet
    return (leg.market, leg.game_id, leg.team_side)


def candidates(priced: list[Priced], min_edge: float = 0.03, min_prob: float = 0.30) -> list[Priced]:
    """Legs with a price that beat it by min_edge, best first, one side per market."""
    good = [p for p in priced if p.ev is not None and p.ev >= min_edge and p.p_win >= min_prob]
    good.sort(key=lambda p: -p.ev)
    seen, out = set(), []
    for p in good:
        k = _key(p)
        if k not in seen:
            seen.add(k)
            out.append(p)
    return out


def build(legs: list[Priced], sims: dict[str, GameSim], max_legs: int = 4, pool: int = 24,
          max_per_game: int = 3, top: int = 20) -> list[Parlay]:
    pool_legs = legs[:pool]
    outcomes = {id(p): p.leg.outcome(sims[p.leg.game_id]) for p in pool_legs}
    decimal = {id(p): odds.american_to_decimal(p.leg.price) for p in pool_legs}
    found: list[Parlay] = []
    for k in range(2, max_legs + 1):
        for combo in combinations(pool_legs, k):
            games = [p.leg.game_id for p in combo]
            n_games = len(set(games))
            if n_games not in (1, k):
                continue  # either all different games (book pays the product) or one game (an SGP)
            if n_games == 1 and k > max_per_game:
                continue
            if len({_key(p) for p in combo}) < k:
                continue
            payout = np.ones(len(outcomes[id(combo[0])]))
            any_win = np.zeros_like(payout, dtype=bool)
            for p in combo:
                o = outcomes[id(p)]
                payout *= np.where(o == WIN, decimal[id(p)], np.where(o == PUSH, 1.0, 0.0))
                any_win |= o == WIN
            alive = payout > 0
            p_hit = float(np.mean(alive & any_win))
            same_game = n_games == 1
            book = None if same_game else float(np.prod([decimal[id(p)] for p in combo]))
            ev = float(np.mean(payout)) - 1 if not same_game else None
            found.append(Parlay(list(combo), p_hit, ev,
                                None if book is None else odds.decimal_to_american(book),
                                odds.fair_american(p_hit), same_game))
    cross = sorted((x for x in found if not x.same_game), key=lambda x: -x.ev)[:top]
    # same-game: rank by how far the true hit chance is above what the legs imply on their own
    sgp = [x for x in found if x.same_game]
    for x in sgp:
        x.ev = None
    sgp.sort(key=lambda x: -(x.p_hit / np.prod([p.p_win for p in x.legs])))
    return cross + sgp[:top]
