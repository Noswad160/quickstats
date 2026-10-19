"""Ensemble forecasts of daily max temperature from Open-Meteo (GEFS, ECMWF ENS, ...).

NWS daily climate values use a midnight-to-midnight *local standard time* day, even
during daylight saving, so hourly data is bucketed with a fixed standard-time offset
instead of the city's wall-clock timezone.
"""
from collections import defaultdict
from datetime import datetime, timedelta

from . import config
from .http import get_json

MIN_HOURS_PER_DAY = 24  # skip partial days at the ends of the forecast window


def fetch_ensemble(station: config.Station, model: str, forecast_days: int = 4) -> dict:
    return get_json(config.OPEN_METEO_ENSEMBLE_API, params={
        "latitude": station.lat,
        "longitude": station.lon,
        "hourly": "temperature_2m",
        "models": model,
        "temperature_unit": "fahrenheit",
        "timezone": "GMT",
        "forecast_days": forecast_days,
    })


def daily_max_by_member(payload: dict, lst_offset: int) -> dict[str, list[float]]:
    """Return {climate_date: [tmax per member]} from an Open-Meteo hourly ensemble payload."""
    hourly = payload["hourly"]
    times = [datetime.fromisoformat(t) + timedelta(hours=lst_offset) for t in hourly["time"]]
    member_keys = sorted(k for k in hourly if k.startswith("temperature_2m"))

    hours = defaultdict(int)
    maxes: dict[str, dict[str, float]] = defaultdict(dict)  # date -> member -> max
    for i, t in enumerate(times):
        d = t.date().isoformat()
        hours[d] += 1
        for k in member_keys:
            v = hourly[k][i]
            if v is None:
                continue
            cur = maxes[d].get(k)
            maxes[d][k] = v if cur is None else max(cur, v)

    out = {}
    for d, per_member in maxes.items():
        if hours[d] >= MIN_HOURS_PER_DAY and len(per_member) == len(member_keys):
            out[d] = [per_member[k] for k in member_keys]
    return out
