"""Paper trader: replay every stored Kalshi snapshot in time order and trade the model.

Deterministic, so the whole ledger is rebuilt from the data on each run. Parameters
are fixed up front: tuning them on this same history makes the results in-sample.

Fills are assumed at the quoted best price for the full size. Real top-of-book depth
can be smaller, so stakes are kept small.
"""
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from . import kalshi
from .model import History, Model, day_start_utc, lst_today


@dataclass(frozen=True)
class Params:
    bankroll: float = 1000.0
    min_edge: float = 0.05        # EV per contract after fees, in dollars
    kelly_fraction: float = 0.10  # of full Kelly
    max_stake: float = 25.0       # per market
    max_event_stake: float = 50.0 # per station/day
    min_price: float = 0.03
    max_price: float = 0.97
    max_lead_days: int = 2        # only trade days at most this far ahead


@dataclass
class Trade:
    ts: str
    market_id: str
    station: str
    date: str
    lo: int | None
    hi: int | None
    side: str          # 'yes' | 'no'
    price: float       # paid per contract
    contracts: int
    fee: float
    model_p: float     # model probability the bought side wins
    pnl: float | None = None
    outcome: int | None = None

    @property
    def cost(self) -> float:
        return self.price * self.contracts + self.fee


@dataclass
class Ledger:
    params: Params
    trades: list[Trade] = field(default_factory=list)

    @property
    def settled(self):
        return [t for t in self.trades if t.pnl is not None]

    @property
    def open(self):
        return [t for t in self.trades if t.pnl is None]

    @property
    def realized(self) -> float:
        return sum(t.pnl for t in self.settled)

    @property
    def cash(self) -> float:
        return self.params.bankroll + self.realized - sum(t.cost for t in self.open)


def _settle_after(station: str, d: str) -> str:
    # The NWS climate report comes out the morning after; settle 12h after the day ends.
    end = datetime.fromisoformat(day_start_utc(station, d)) + timedelta(days=1, hours=12)
    return end.isoformat()


def _settle(ledger: Ledger, history: History, now: str) -> None:
    for t in ledger.open:
        obs = history.obs.get((t.station, t.date))
        if obs is None or now < _settle_after(t.station, t.date):
            continue
        in_bucket = (t.lo is None or obs >= t.lo) and (t.hi is None or obs <= t.hi)
        won = in_bucket if t.side == "yes" else not in_bucket
        t.outcome = obs
        t.pnl = (1.0 if won else 0.0) * t.contracts - t.cost


def _size(p: float, price: float, cash: float, room: float, prm: Params) -> int:
    """Contracts to buy: fractional Kelly, capped (fee included) by market/event limits and cash.

    The per-contract fee only shrinks with size (one round-up per order), so an order
    that cleared min_edge for one contract still clears it at n.
    """
    kelly = (p - price) / (1 - price)
    stake = min(prm.kelly_fraction * kelly * cash, prm.max_stake, room, cash)
    n = int(stake // price) if stake > 0 else 0
    while n > 0 and price * n + kalshi.taker_fee(price, n) > stake:
        n -= 1
    return n


def run(conn, history: History, model: Model, prm: Params = Params()) -> Ledger:
    ledger = Ledger(prm)
    held: set[str] = set()
    event_stake: dict[tuple, float] = defaultdict(float)

    snaps = conn.execute("""
        SELECT ts, market_id, station, target_date, lo, hi, yes_bid, yes_ask FROM market_snapshots
        WHERE venue = 'kalshi' AND station IS NOT NULL AND target_date IS NOT NULL
          AND (lo IS NOT NULL OR hi IS NOT NULL)
        ORDER BY ts, market_id""").fetchall()

    for s in snaps:
        ts, st, d = s["ts"], s["station"], s["target_date"]
        _settle(ledger, history, ts)
        if s["market_id"] in held:
            continue
        today = lst_today(st, ts)
        lead = (date.fromisoformat(d) - date.fromisoformat(today)).days
        if not 1 <= lead <= prm.max_lead_days:
            continue
        p_yes = model.prob(st, d, s["lo"], s["hi"], ts)
        if p_yes is None:
            continue

        options = []
        if s["yes_ask"] is not None:
            options.append(("yes", p_yes, s["yes_ask"]))
        if s["yes_bid"] is not None:
            options.append(("no", 1 - p_yes, round(1 - s["yes_bid"], 4)))
        options = [(side, p, c) for side, p, c in options
                   if prm.min_price <= c <= prm.max_price and p - c - kalshi.taker_fee(c) >= prm.min_edge]
        if not options:
            continue
        side, p, price = max(options, key=lambda o: o[1] - o[2] - kalshi.taker_fee(o[2]))

        room = prm.max_event_stake - event_stake[(st, d)]
        n = _size(p, price, ledger.cash, room, prm)
        if n <= 0:
            continue
        t = Trade(ts, s["market_id"], st, d, s["lo"], s["hi"], side, price, n, kalshi.taker_fee(price, n), p)
        ledger.trades.append(t)
        held.add(s["market_id"])
        event_stake[(st, d)] += t.cost

    _settle(ledger, history, "9999-12-31")
    return ledger


def _bucket(lo, hi):
    if lo is None:
        return f"≤{hi}"
    if hi is None:
        return f"≥{lo}"
    return f"{lo}–{hi}"


def render(ledger: Ledger) -> str:
    prm, settled, opened = ledger.params, ledger.settled, ledger.open
    staked = sum(t.cost for t in settled)
    wins = sum(t.pnl > 0 for t in settled)
    expected = sum(t.model_p * t.contracts - t.cost for t in settled)
    lines = [
        "# wxbot paper trading (Kalshi)", "",
        "**Simulated only.** Replays every stored price snapshot and trades the model with the "
        "rules below. Fills assume the full size at the quoted best price.", "",
        f"Rules: min edge ${prm.min_edge:.2f}/contract after fees · {prm.kelly_fraction:.0%} Kelly · "
        f"≤${prm.max_stake:.0f} per market · ≤${prm.max_event_stake:.0f} per city/day · "
        f"prices {prm.min_price:.2f}–{prm.max_price:.2f} · 1–{prm.max_lead_days} days ahead", "",
        "## Summary", "",
        f"- Starting bankroll: ${prm.bankroll:,.2f}",
        f"- Settled trades: {len(settled)} ({wins} won) · staked ${staked:,.2f}",
        f"- Realized P&L: **${ledger.realized:+,.2f}**"
        + (f" ({ledger.realized / staked:+.1%} on stake)" if staked else ""),
        f"- Model expected P&L on those trades: ${expected:+,.2f} "
        "(if realized is far below this over many trades, the model is overconfident)",
        f"- Open trades: {len(opened)} · cost ${sum(t.cost for t in opened):,.2f}",
        f"- Bankroll now (cash + open at cost): ${prm.bankroll + ledger.realized:,.2f}", "",
        "## Trades (newest first)", "",
        "| placed | station | date | bucket °F | side | price | qty | fee | model p | observed | P&L |",
        "|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for t in reversed(ledger.trades[-300:]):
        lines.append(f"| {t.ts[:16]} | {t.station} | {t.date} | {_bucket(t.lo, t.hi)} | {t.side} | "
                     f"{t.price:.2f} | {t.contracts} | {t.fee:.2f} | {t.model_p:.2f} | "
                     f"{'' if t.outcome is None else t.outcome} | "
                     f"{'open' if t.pnl is None else f'{t.pnl:+.2f}'} |")
    return "\n".join(lines) + "\n"
