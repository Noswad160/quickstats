"""Observed daily highs from the NWS Daily Climate Report (CLI) -- what Kalshi settles on."""
import re
from datetime import datetime, timedelta

from . import config
from .http import get_json

_SUMMARY_DATE = re.compile(r"CLIMATE SUMMARY FOR\s+([A-Z]+)\s+(\d{1,2})\s+(\d{4})")
_MAXIMUM = re.compile(r"^\s*MAXIMUM\s+(-?\d+)", re.M)


def parse_cli(text: str) -> tuple[str, int] | None:
    """Return (date, max °F) from a CLI product, or None if it can't be parsed."""
    d = _SUMMARY_DATE.search(text)
    if not d:
        return None
    # The first MAXIMUM after the TEMPERATURE header is the observed value for the day.
    temp_section = text.find("TEMPERATURE")
    m = _MAXIMUM.search(text, temp_section if temp_section >= 0 else 0)
    if not m:
        return None
    date = datetime.strptime(f"{d[1].title()} {d[2]} {d[3]}", "%B %d %Y").date().isoformat()
    return date, int(m[1])


def forecast_highs(grid: dict, lst_offset: int) -> dict[str, float]:
    """{climate_date: forecast max °F} from a gridpoints payload's maxTemperature series.

    Each value covers a daytime period like '2026-10-19T12:00:00+00:00/PT13H'; its start,
    shifted to local standard time, names the climate day.
    """
    series = grid["properties"]["maxTemperature"]
    to_f = (lambda v: v * 9 / 5 + 32) if series.get("uom", "").endswith("degC") else (lambda v: v)
    out = {}
    for item in series.get("values", []):
        if item.get("value") is None:
            continue
        start = datetime.fromisoformat(item["validTime"].split("/")[0])
        day = (start + timedelta(hours=lst_offset)).date().isoformat()
        out[day] = round(to_f(item["value"]), 2)
    return out


def fetch_forecast_highs(station: config.Station) -> dict[str, float]:
    point = get_json(f"{config.NWS_API}/points/{station.lat:.4f},{station.lon:.4f}")
    return forecast_highs(get_json(point["properties"]["forecastGridData"]), station.lst_offset)


def fetch_recent_cli(station: config.Station, limit: int = 10) -> list[str]:
    """Texts of the latest CLI products for a station (newest first)."""
    listing = get_json(f"{config.NWS_API}/products/types/CLI/locations/{station.cli_code}")
    texts = []
    for item in listing.get("@graph", [])[:limit]:
        product = get_json(item["@id"])
        texts.append(product.get("productText", ""))
    return texts
