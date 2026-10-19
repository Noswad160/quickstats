"""Kalshi public market data (no auth needed for reads)."""
import re
from datetime import datetime

from . import config
from .http import get_json

_EVENT_DATE = re.compile(r"-(\d{2})([A-Z]{3})(\d{2})$")


def fetch_markets(series_ticker: str, status: str = "open") -> list[dict]:
    markets, cursor = [], None
    while True:
        params = {"series_ticker": series_ticker, "status": status, "limit": 200}
        if cursor:
            params["cursor"] = cursor
        page = get_json(f"{config.KALSHI_API}/markets", params=params)
        markets.extend(page.get("markets", []))
        cursor = page.get("cursor")
        if not cursor:
            return markets


def event_date(event_ticker: str) -> str | None:
    """'KXHIGHNY-26OCT20' -> '2026-10-20'."""
    m = _EVENT_DATE.search(event_ticker or "")
    if not m:
        return None
    yy, mon, dd = m.groups()
    return datetime.strptime(f"{yy}{mon.title()}{dd}", "%y%b%d").date().isoformat()


def bucket(market: dict) -> tuple[int | None, int | None]:
    """Inclusive bounds on the reported integer °F that resolves the market YES.

    strike_type 'between' covers floor..cap inclusive; 'greater' means strictly above
    floor_strike; 'less' means strictly below cap_strike. Confirm against each market's
    rules_primary text before trading.
    """
    kind = market.get("strike_type")
    lo, hi = market.get("floor_strike"), market.get("cap_strike")
    if kind == "between" and lo is not None and hi is not None:
        return int(lo), int(hi)
    if kind == "greater" and lo is not None:
        return int(lo) + 1, None
    if kind == "less" and hi is not None:
        return None, int(hi) - 1
    return None, None


def _price(market: dict, field: str) -> float | None:
    """Prices come as integer cents ('yes_bid') and/or dollar strings ('yes_bid_dollars')."""
    dollars = market.get(f"{field}_dollars")
    if dollars not in (None, ""):
        return float(dollars)
    cents = market.get(field)
    return None if cents is None else cents / 100.0


def to_snapshot(market: dict, series_ticker: str, ts: str) -> dict:
    lo, hi = bucket(market)
    bid, ask = _price(market, "yes_bid"), _price(market, "yes_ask")
    return {
        "ts": ts,
        "venue": "kalshi",
        "market_id": market["ticker"],
        "event_id": market.get("event_ticker"),
        "title": market.get("title") or market.get("subtitle"),
        "station": config.KALSHI_SERIES_TO_STATION.get(series_ticker),
        "target_date": event_date(market.get("event_ticker", "")),
        "unit": "F",
        "lo": lo,
        "hi": hi,
        # An empty side shows as 0 bid / 100 ask; store as missing instead.
        "yes_bid": bid if bid else None,
        "yes_ask": ask if ask and ask < 1.0 else None,
        "last_price": _price(market, "last_price"),
        "volume": market.get("volume"),
        "close_time": market.get("close_time"),
        "raw": market,
    }


def taker_fee(price: float, contracts: int = 1, rate: float = 0.07) -> float:
    """Kalshi taker fee in dollars: ceil to the cent of rate * C * P * (1 - P)."""
    cents = rate * contracts * price * (1 - price) * 100
    return -(-round(cents, 6) // 1) / 100
