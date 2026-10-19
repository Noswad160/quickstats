"""Polymarket public market data via the Gamma API.

Read-only: data collection is fine from anywhere, but the international exchange is
not open to US persons for trading.
"""
import json
import re
from datetime import datetime

from . import config
from .http import get_json

_TITLE = re.compile(r"highest temperature in (?P<city>.+?) on (?P<month>[A-Za-z]+) (?P<day>\d{1,2})", re.I)
_RANGE = re.compile(r"(-?\d+)\s*-\s*(-?\d+)\s*°?\s*([FC])", re.I)
_ABOVE = re.compile(r"(-?\d+)\s*°?\s*([FC])\s*or\s*(higher|above|more)", re.I)
_BELOW = re.compile(r"(-?\d+)\s*°?\s*([FC])\s*or\s*(lower|below|less)", re.I)
_SINGLE = re.compile(r"^\s*(-?\d+)\s*°?\s*([FC])\s*$", re.I)

_CITY_TO_STATION = {name: s.key for s in config.STATIONS.values() for name in s.polymarket_names}


def fetch_temperature_events(tag_slug: str = "weather", page_size: int = 100, max_pages: int = 20) -> list[dict]:
    events = []
    for page in range(max_pages):
        batch = get_json(f"{config.POLY_GAMMA_API}/events", params={
            "tag_slug": tag_slug, "closed": "false", "limit": page_size, "offset": page * page_size,
        })
        if not batch:
            break
        events.extend(e for e in batch if _TITLE.search(e.get("title", "")))
        if len(batch) < page_size:
            break
    return events


def parse_title(title: str, ref_year: int) -> tuple[str | None, str | None]:
    """'Highest temperature in NYC on October 20?' -> ('nyc', '2026-10-20')."""
    m = _TITLE.search(title or "")
    if not m:
        return None, None
    try:
        d = datetime.strptime(f"{m['month']} {m['day']} {ref_year}", "%B %d %Y").date()
    except ValueError:
        return m["city"].strip().lower(), None
    return m["city"].strip().lower(), d.isoformat()


def parse_bucket(label: str) -> tuple[int | None, int | None, str | None]:
    """'74-75°F' -> (74, 75, 'F'); '77°F or higher' -> (77, None, 'F'); '12°C' -> (12, 12, 'C')."""
    label = label or ""
    if m := _ABOVE.search(label):
        return int(m[1]), None, m[2].upper()
    if m := _BELOW.search(label):
        return None, int(m[1]), m[2].upper()
    if m := _RANGE.search(label):
        return int(m[1]), int(m[2]), m[3].upper()
    if m := _SINGLE.search(label):
        return int(m[1]), int(m[1]), m[2].upper()
    return None, None, None


def _float(v) -> float | None:
    try:
        return None if v in (None, "") else float(v)
    except (TypeError, ValueError):
        return None


def to_snapshots(event: dict, ts: str) -> list[dict]:
    ref_year = int((event.get("endDate") or ts)[:4])
    city, target_date = parse_title(event.get("title", ""), ref_year)
    station = _CITY_TO_STATION.get(city or "")
    rows = []
    for m in event.get("markets", []):
        if m.get("closed"):
            continue
        lo, hi, unit = parse_bucket(m.get("groupItemTitle") or m.get("question", ""))
        token_ids = m.get("clobTokenIds")
        if isinstance(token_ids, str):
            token_ids = json.loads(token_ids)
        yes_token = token_ids[0] if token_ids else m.get("id")
        rows.append({
            "ts": ts,
            "venue": "polymarket",
            "market_id": str(yes_token),
            "event_id": str(event.get("id")),
            "title": m.get("question"),
            # Only price markets we can map to a °F station model.
            "station": station if unit == "F" else None,
            "target_date": target_date,
            "unit": unit,
            "lo": lo,
            "hi": hi,
            "yes_bid": _float(m.get("bestBid")),
            "yes_ask": _float(m.get("bestAsk")),
            "last_price": _float(m.get("lastTradePrice")),
            "volume": _float(m.get("volumeNum") or m.get("volume")),
            "close_time": m.get("endDate"),
            "raw": m,
        })
    return rows
