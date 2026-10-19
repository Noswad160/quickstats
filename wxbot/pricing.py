"""Turn ensemble members into bucket probabilities and compare with market prices."""
import math


def _phi(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def bucket_probability(members: list[float], lo: int | None, hi: int | None,
                       sigma: float = 2.0, bias: float = 0.0) -> float:
    """P(reported integer high is in [lo, hi]) under a Gaussian-kernel ensemble mixture.

    Reported values are whole degrees, so bucket [lo, hi] covers the continuous
    interval [lo - 0.5, hi + 0.5). `bias` is added to every member (station correction).
    """
    if not members:
        raise ValueError("no ensemble members")
    a = -math.inf if lo is None else lo - 0.5
    b = math.inf if hi is None else hi + 0.5
    total = 0.0
    for m in members:
        mu = m + bias
        total += (_phi((b - mu) / sigma) if b != math.inf else 1.0) - \
                 (_phi((a - mu) / sigma) if a != -math.inf else 0.0)
    return total / len(members)


def recenter(members: list[float], center: float | None) -> list[float]:
    """Shift the ensemble so its mean equals `center` (e.g. the NWS forecast high).

    Raw ensembles run cold on daily highs (3-hourly output clips the peak, grid cells
    smooth local heat); the official forecast fixes the level, the ensemble keeps the spread.
    """
    if center is None or not members:
        return members
    shift = center - sum(members) / len(members)
    return [m + shift for m in members]


def edges(p: float, yes_bid: float | None, yes_ask: float | None, fee) -> dict:
    """Expected value per $1 contract of buying YES at the ask or NO at (1 - bid), after fees."""
    out = {"buy_yes": None, "buy_no": None}
    if yes_ask is not None:
        out["buy_yes"] = p - yes_ask - fee(yes_ask)
    if yes_bid is not None:
        no_price = 1.0 - yes_bid
        out["buy_no"] = (1.0 - p) - no_price - fee(no_price)
    return out
