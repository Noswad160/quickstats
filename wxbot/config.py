"""Stations, venue mappings and tunable parameters.

Every market must resolve against a specific station. Before trading a market,
read its rules on the venue and confirm the station below matches -- a model of
the wrong station is worthless.
"""
from dataclasses import dataclass, field
import os


@dataclass(frozen=True)
class Station:
    key: str                # internal id, e.g. "NYC"
    name: str
    icao: str               # NWS observing station
    lat: float
    lon: float
    lst_offset: int         # hours from UTC in *standard* time (NWS climate day ignores DST)
    cli_code: str           # NWS CLI product location code (daily climate report)
    cli_office: str         # issuing NWS office (WFO) for the CLI product
    kalshi_series: str | None = None
    polymarket_names: tuple[str, ...] = field(default_factory=tuple)


# Kalshi daily-high series resolve on the NWS Daily Climate Report (CLI) for these stations.
# Polymarket temperature markets have historically resolved on Weather Underground station
# history (e.g. LaGuardia for NYC), so NYC has a separate LGA entry for Polymarket.
STATIONS: dict[str, Station] = {s.key: s for s in [
    Station("NYC", "New York (Central Park)", "KNYC", 40.7789, -73.9692, -5, "NYC", "OKX", "KXHIGHNY"),
    Station("LGA", "New York (LaGuardia)", "KLGA", 40.7794, -73.8803, -5, "LGA", "OKX", None,
            ("new york city", "nyc", "new york")),
    Station("CHI", "Chicago (Midway)", "KMDW", 41.7861, -87.7522, -6, "MDW", "LOT", "KXHIGHCHI"),
    Station("ORD", "Chicago (O'Hare)", "KORD", 41.9602, -87.9316, -6, "ORD", "LOT", None, ("chicago",)),
    Station("MIA", "Miami", "KMIA", 25.7881, -80.3169, -5, "MIA", "MFL", "KXHIGHMIA", ("miami",)),
    Station("AUS", "Austin (Bergstrom)", "KAUS", 30.1945, -97.6699, -6, "AUS", "EWX", "KXHIGHAUS"),
    Station("DEN", "Denver", "KDEN", 39.8466, -104.6562, -7, "DEN", "BOU", "KXHIGHDEN"),
    Station("PHL", "Philadelphia", "KPHL", 39.8721, -75.2407, -5, "PHL", "PHI", "KXHIGHPHIL"),
    Station("LAX", "Los Angeles (LAX)", "KLAX", 33.9382, -118.3866, -8, "LAX", "LOX", "KXHIGHLAX"),
]}

KALSHI_SERIES_TO_STATION = {s.kalshi_series: s.key for s in STATIONS.values() if s.kalshi_series}

# Open-Meteo ensemble model ids. Each is requested separately so member keys stay unsuffixed.
ENSEMBLE_MODELS = ("gfs025", "ecmwf_ifs025")

# Pricing: each ensemble member is smeared by a Gaussian of this width (°F) to account for
# grid-point-vs-station error and ensemble under-dispersion. Calibrate from history later.
KERNEL_SIGMA_F = float(os.environ.get("WXBOT_SIGMA", "2.0"))

DB_PATH = os.environ.get("WXBOT_DB", "data/wxbot.sqlite")
USER_AGENT = os.environ.get("WXBOT_UA", "wxbot/0.1 (research; contact: see repo)")

KALSHI_API = "https://api.elections.kalshi.com/trade-api/v2"
POLY_GAMMA_API = "https://gamma-api.polymarket.com"
POLY_CLOB_API = "https://clob.polymarket.com"
OPEN_METEO_ENSEMBLE_API = "https://ensemble-api.open-meteo.com/v1/ensemble"
NWS_API = "https://api.weather.gov"
