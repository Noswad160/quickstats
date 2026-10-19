"""Row-object JSON files for the dashboard: one file per table it shows."""
import json
import os

from . import config, kalshi, paper, scorecard, store
from .model import History, Model, lst_today


def _bucket(lo, hi):
    if lo is None:
        return f"≤{hi}"
    if hi is None:
        return f"≥{lo}"
    return f"{lo}–{hi}"


def _mid(bid, ask):
    if bid is not None and ask is not None:
        return (bid + ask) / 2
    return ask if ask is not None else bid


def outlook(conn, mdl: Model, now: str) -> list[dict]:
    """Per Kalshi city/day still ahead: NWS high, model mean, market-implied high, favorite bucket."""
    events: dict[tuple, list] = {}
    for s in store.latest_snapshots(conn):
        if s["venue"] != "kalshi" or s["target_date"] <= lst_today(s["station"], now):
            continue
        events.setdefault((s["station"], s["target_date"]), []).append(s)
    rows = []
    for (st, d), books in sorted(events.items()):
        priced = [(b, _mid(b["yes_bid"], b["yes_ask"]) or 0.0) for b in books]
        total = sum(p for _, p in priced)
        centers = [((b["lo"] + b["hi"]) / 2 if b["lo"] is not None and b["hi"] is not None
                    else (b["lo"] + 0.5 if b["lo"] is not None else b["hi"] - 0.5), p) for b, p in priced]
        fav, fav_p = max(priced, key=lambda bp: bp[1])
        m = mdl.members(st, d, now)
        rows.append({
            "station": st, "city": config.STATIONS[st].name, "date": d,
            "nws_high": None if m is None else round(m[1], 1),
            "model_high": None if m is None else round(sum(m[0]) / len(m[0]), 1),
            "market_high": round(sum(c * p for c, p in centers) / total, 1) if total else None,
            "market_favorite": _bucket(fav["lo"], fav["hi"]), "favorite_price": round(fav_p, 3),
            "model_p_favorite": None if m is None else round(mdl.prob(st, d, fav["lo"], fav["hi"], now), 3),
        })
    return rows


def edges(conn, mdl: Model, now: str, min_edge: float = 0.03) -> list[dict]:
    rows = []
    for s in store.latest_snapshots(conn):
        if s["venue"] != "kalshi" or s["target_date"] <= lst_today(s["station"], now):
            continue
        p = mdl.prob(s["station"], s["target_date"], s["lo"], s["hi"], now)
        if p is None:
            continue
        opts = []
        if s["yes_ask"] is not None:
            opts.append(("Buy YES", s["yes_ask"], p - s["yes_ask"] - kalshi.taker_fee(s["yes_ask"])))
        if s["yes_bid"] is not None:
            c = 1 - s["yes_bid"]
            opts.append(("Buy NO", c, (1 - p) - c - kalshi.taker_fee(c)))
        if not opts:
            continue
        side, price, edge = max(opts, key=lambda o: o[2])
        if edge >= min_edge:
            rows.append({"market": s["market_id"], "station": s["station"], "date": s["target_date"],
                         "bucket": _bucket(s["lo"], s["hi"]), "side": side, "price": round(price, 3),
                         "model_p": round(p, 3), "edge": round(edge, 3), "as_of": s["ts"]})
    return sorted(rows, key=lambda r: -r["edge"])


def trades(ledger: paper.Ledger) -> list[dict]:
    return [{"trade": f"{t.market_id}@{t.ts}", "placed": t.ts, "station": t.station, "date": t.date,
             "bucket": _bucket(t.lo, t.hi), "side": t.side.upper(), "price": t.price, "qty": t.contracts,
             "cost": round(t.cost, 2), "model_p": round(t.model_p, 3), "observed": t.outcome,
             "pnl": None if t.pnl is None else round(t.pnl, 2), "status": "open" if t.pnl is None else
             ("won" if t.pnl > 0 else "lost")} for t in ledger.trades]


def pnl_by_day(ledger: paper.Ledger) -> list[dict]:
    """Realized P&L per settled climate day, with the running total."""
    by_day: dict[str, list] = {}
    for t in ledger.settled:
        by_day.setdefault(t.date, []).append(t)
    rows, running = [], 0.0
    for d in sorted(by_day):
        day = sum(t.pnl for t in by_day[d])
        running += day
        rows.append({"date": d, "trades": len(by_day[d]), "staked": round(sum(t.cost for t in by_day[d]), 2),
                     "pnl": round(day, 2), "cumulative_pnl": round(running, 2)})
    return rows


def scores(conn, h: History, sigma: float) -> list[dict]:
    return [{"event": f"{s.venue}:{s.station}:{s.date}", "venue": s.venue, "station": s.station, "date": s.date,
             "observed": s.observed, "nws_high": round(s.nws, 1), "model_p": round(s.model_p, 3),
             "market_p": round(s.market_p, 3), "model_logloss": round(s.model_logloss, 4),
             "market_logloss": round(s.market_logloss, 4)} for s in scorecard.score_events(conn, h, sigma)]


def status(conn, ledger: paper.Ledger, now: str) -> list[dict]:
    r = conn.execute("""SELECT (SELECT MAX(ts) FROM market_snapshots), (SELECT MAX(ts) FROM forecasts),
        (SELECT COUNT(DISTINCT ts) FROM market_snapshots), (SELECT COUNT(*) FROM observations),
        (SELECT MIN(ts) FROM market_snapshots)""").fetchone()
    prm = ledger.params
    return [{"exported_at": now, "latest_prices": r[0], "latest_forecast": r[1], "price_snapshots": r[2],
             "observed_days": r[3], "collecting_since": r[4], "bankroll_start": prm.bankroll,
             "realized_pnl": round(ledger.realized, 2), "open_trades": len(ledger.open),
             "open_cost": round(sum(t.cost for t in ledger.open), 2),
             "settled_trades": len(ledger.settled), "won_trades": sum(t.pnl > 0 for t in ledger.settled)}]


def export_all(conn, out_dir: str, sigma: float = config.KERNEL_SIGMA_F) -> list[str]:
    now = store.utcnow()
    h = History(conn)
    mdl = Model(h, sigma=sigma)
    ledger = paper.run(conn, h, mdl)
    files = {
        "status.json": status(conn, ledger, now),
        "outlook.json": outlook(conn, mdl, now),
        "edges.json": edges(conn, mdl, now),
        "trades.json": trades(ledger),
        "pnl_by_day.json": pnl_by_day(ledger),
        "scores.json": scores(conn, h, sigma),
    }
    os.makedirs(out_dir, exist_ok=True)
    paths = []
    for name, rows in files.items():
        path = os.path.join(out_dir, name)
        with open(path, "w") as f:
            json.dump(rows, f, separators=(",", ":"))
        paths.append(path)
    return paths
