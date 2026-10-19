"""Grade model vs market on settled days.

For every event (one station/day, several buckets) with an observed high, compare the
model's probabilities with the market's last prices before the climate day began.
Lower log loss / Brier wins. If the model doesn't beat the market here, it has no edge.
"""
import math
from collections import defaultdict
from dataclasses import dataclass

from . import config
from .model import History, Model, day_start_utc

EPS = 1e-3
SIGMA_GRID = (1.0, 1.5, 2.0, 2.5, 3.0, 4.0)


@dataclass
class EventScore:
    venue: str
    station: str
    date: str
    observed: int
    nws: float
    model_p: float        # probability each side gave the bucket that happened
    market_p: float
    model_logloss: float
    market_logloss: float
    model_brier: float
    market_brier: float


def _mid(bid, ask):
    if bid is not None and ask is not None:
        return (bid + ask) / 2
    if ask is not None:
        return ask / 2
    if bid is not None:
        return (bid + 1) / 2
    return 0.0


def _contains(lo, hi, v):
    return (lo is None or v >= lo) and (hi is None or v <= hi)


def pre_day_books(conn, history: History) -> dict[tuple, list]:
    """{(venue, event, station, date): [latest pre-day snapshot per market]} for observed days."""
    rows = conn.execute("""
        SELECT venue, event_id, market_id, station, target_date, lo, hi, yes_bid, yes_ask, ts
        FROM market_snapshots WHERE station IS NOT NULL AND target_date IS NOT NULL
        ORDER BY ts""").fetchall()
    latest = {}
    for r in rows:
        st, d = r["station"], r["target_date"]
        if (st, d) not in history.obs or st not in config.STATIONS:
            continue
        if r["ts"] < day_start_utc(st, d):
            latest[(r["venue"], r["market_id"])] = r
    events = defaultdict(list)
    for r in latest.values():
        events[(r["venue"], r["event_id"], r["station"], r["target_date"])].append(r)
    return events


def score_events(conn, history: History, sigma: float) -> list[EventScore]:
    model = Model(history, sigma=sigma)
    out = []
    for (venue, _, st, d), books in sorted(pre_day_books(conn, history).items(), key=lambda kv: kv[0][3]):
        obs = history.obs[(st, d)]
        hit = [i for i, b in enumerate(books) if _contains(b["lo"], b["hi"], obs)]
        if len(hit) != 1:
            continue  # bucket set doesn't cover the outcome (gaps / partial listing)
        cutoff = day_start_utc(st, d)
        m = model.members(st, d, cutoff)
        if m is None:
            continue
        model_p = [model.prob(st, d, b["lo"], b["hi"], cutoff) for b in books]
        mkt = [_mid(b["yes_bid"], b["yes_ask"]) for b in books]
        total_m, total_k = sum(model_p), sum(mkt)
        if total_k <= 0:
            continue
        model_p = [p / total_m for p in model_p]
        mkt = [p / total_k for p in mkt]
        i = hit[0]
        out.append(EventScore(
            venue, st, d, obs, m[1], model_p[i], mkt[i],
            -math.log(max(model_p[i], EPS)), -math.log(max(mkt[i], EPS)),
            sum((p - (j == i)) ** 2 for j, p in enumerate(model_p)),
            sum((p - (j == i)) ** 2 for j, p in enumerate(mkt)),
        ))
    return out


def _mean(xs):
    return sum(xs) / len(xs) if xs else float("nan")


def render(conn, history: History, sigma: float) -> str:
    scores = score_events(conn, history, sigma)
    lines = ["# wxbot scorecard", "",
             "Model vs market on settled days, using the last prices and forecasts **before** each "
             "climate day began. Lower is better. The model needs to beat the market on many days "
             "before any edge is believable.", ""]

    lines += ["## Summary", "", "| venue | days | model log loss | market log loss | model Brier | "
              "market Brier | days model better |", "|---|---|---|---|---|---|---|"]
    for venue in sorted({s.venue for s in scores}):
        v = [s for s in scores if s.venue == venue]
        better = sum(s.model_logloss < s.market_logloss for s in v)
        lines.append(f"| {venue} | {len(v)} | {_mean([s.model_logloss for s in v]):.3f} | "
                     f"{_mean([s.market_logloss for s in v]):.3f} | {_mean([s.model_brier for s in v]):.3f} | "
                     f"{_mean([s.market_brier for s in v]):.3f} | {better}/{len(v)} |")
    if not scores:
        lines.append("| _no settled days yet_ | | | | | | |")

    lines += ["", "## NWS forecast error by station (observed − NWS high at day start)", "",
              "| station | days | mean error °F | RMSE °F | bias applied now |", "|---|---|---|---|---|"]
    for st in sorted(config.STATIONS):
        errs = [e for _, e in history.center_errors(st)]
        if errs:
            rmse = math.sqrt(_mean([e * e for e in errs]))
            lines.append(f"| {st} | {len(errs)} | {_mean(errs):+.2f} | {rmse:.2f} | "
                         f"{history.bias(st, '9999-12-31'):+.2f} |")

    if scores:
        lines += ["", "## Kernel width (sigma) check — in-sample, Kalshi only", "",
                  "| sigma °F | model log loss |", "|---|---|"]
        for sg in SIGMA_GRID:
            k = [s for s in score_events(conn, history, sg) if s.venue == "kalshi"]
            if k:
                lines.append(f"| {sg}{' (current)' if sg == sigma else ''} | {_mean([s.model_logloss for s in k]):.3f} |")

    lines += ["", "## Days", "", "| venue | station | date | observed | NWS high | model p(actual) | "
              "market p(actual) | winner |", "|---|---|---|---|---|---|---|---|"]
    for s in reversed(scores[-200:]):
        win = "model" if s.model_logloss < s.market_logloss else "market"
        lines.append(f"| {s.venue} | {s.station} | {s.date} | {s.observed} | {s.nws:.1f} | "
                     f"{s.model_p:.2f} | {s.market_p:.2f} | {win} |")
    return "\n".join(lines) + "\n"
