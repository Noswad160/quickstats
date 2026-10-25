"""Odds arithmetic: American/decimal prices, implied probability, removing the vig."""
import math


def american_to_decimal(american: float) -> float:
    return 1 + (american / 100 if american > 0 else 100 / -american)


def decimal_to_american(decimal: float) -> int:
    if decimal <= 1:
        raise ValueError("decimal odds must be > 1")
    return round((decimal - 1) * 100) if decimal >= 2 else round(-100 / (decimal - 1))


def implied_prob(american: float) -> float:
    """Probability the price implies, vig included."""
    return 1 / american_to_decimal(american)


def fair_american(p: float) -> int:
    """The no-vig price for an outcome with probability p: your own line."""
    p = min(max(p, 1e-4), 1 - 1e-4)
    return decimal_to_american(1 / p)


def devig(over_american: float, under_american: float) -> tuple[float, float]:
    """Book's fair probabilities for a two-way market, vig removed proportionally."""
    a, b = implied_prob(over_american), implied_prob(under_american)
    return a / (a + b), b / (a + b)


def ev(p: float, american: float) -> float:
    """Expected profit per $1 staked at this price if the true probability is p."""
    return p * american_to_decimal(american) - 1


def kelly(p: float, american: float) -> float:
    """Full-Kelly stake as a fraction of bankroll (0 when there's no edge)."""
    b = american_to_decimal(american) - 1
    return max(0.0, (p * b - (1 - p)) / b)


def fmt_american(a: float) -> str:
    return f"+{a:.0f}" if a > 0 else f"{a:.0f}" if math.isfinite(a) else "—"
