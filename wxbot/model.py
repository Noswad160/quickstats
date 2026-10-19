"""Point-in-time pricing model shared by `edges`, the scorecard and the paper trader.

Everything takes an `as_of` UTC timestamp and only looks at forecasts fetched, and
observations dated, before it, so backtests can't peek at the future.
"""
from bisect import bisect_right
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone

from . import config, pricing

BIAS_SHRINK = 10  # observations needed before the station bias counts half


def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat()


def day_start_utc(station: str, d: str) -> str:
    """UTC instant the climate day `d` (local standard time) begins at `station`."""
    midnight = datetime.combine(date.fromisoformat(d), datetime.min.time(), tzinfo=timezone.utc)
    return iso(midnight - timedelta(hours=config.STATIONS[station].lst_offset))


def lst_today(station: str, as_of: str) -> str:
    t = datetime.fromisoformat(as_of) + timedelta(hours=config.STATIONS[station].lst_offset)
    return t.date().isoformat()


class History:
    """All forecasts and observations, indexed for as-of lookups."""

    def __init__(self, conn):
        fc = defaultdict(lambda: defaultdict(dict))  # (station, date) -> model -> ts -> members
        for r in conn.execute("SELECT ts, station, target_date, model, tmax_f FROM forecasts ORDER BY member"):
            fc[(r[1], r[2])][r[3]].setdefault(r[0], []).append(r[4])
        self._fc = {k: {m: (sorted(by_ts), by_ts) for m, by_ts in models.items()} for k, models in fc.items()}
        self.obs = {(r[0], r[1]): r[2] for r in
                    conn.execute("SELECT station, obs_date, tmax_f FROM observations")}
        self._errors: dict[str, list[tuple[str, float]]] | None = None

    def forecasts(self, station: str, d: str, as_of: str) -> dict[str, list[float]]:
        """Latest fetch of each model at or before `as_of`."""
        out = {}
        for model, (times, by_ts) in self._fc.get((station, d), {}).items():
            i = bisect_right(times, as_of)
            if i:
                out[model] = by_ts[times[i - 1]]
        return out

    def center_errors(self, station: str) -> list[tuple[str, float]]:
        """[(date, observed - NWS forecast high as of the day's start)], oldest first."""
        if self._errors is None:
            errs = defaultdict(list)
            for (st, d), tmax in sorted(self.obs.items(), key=lambda kv: kv[0][1]):
                if st not in config.STATIONS:
                    continue
                nws = self.forecasts(st, d, day_start_utc(st, d)).get("nws")
                if nws:
                    errs[st].append((d, tmax - nws[0]))
            self._errors = errs
        return self._errors.get(station, [])

    def bias(self, station: str, before: str) -> float:
        """Shrunk mean forecast error from days strictly before `before`."""
        errs = [e for d, e in self.center_errors(station) if d < before]
        if not errs:
            return 0.0
        return sum(errs) / (len(errs) + BIAS_SHRINK)


class Model:
    def __init__(self, history: History, sigma: float = config.KERNEL_SIGMA_F, use_bias: bool = True):
        self.h, self.sigma, self.use_bias = history, sigma, use_bias
        self._cache: dict = {}

    def members(self, station: str, d: str, as_of: str) -> tuple[list[float], float] | None:
        """(recentred members, NWS high) for a station/day, or None if not priceable."""
        key = (station, d, as_of)
        if key not in self._cache:
            fc = dict(self.h.forecasts(station, d, as_of))
            nws = (fc.pop("nws", None) or [None])[0]
            ens = [t for m in fc.values() for t in m]
            if nws is None or not ens:
                self._cache[key] = None
            else:
                b = self.h.bias(station, lst_today(station, as_of)) if self.use_bias else 0.0
                self._cache[key] = (pricing.recenter(ens, nws + b), nws)
        return self._cache[key]

    def prob(self, station: str, d: str, lo: int | None, hi: int | None, as_of: str) -> float | None:
        m = self.members(station, d, as_of)
        return None if m is None else pricing.bucket_probability(m[0], lo, hi, sigma=self.sigma)
