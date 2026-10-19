"""wxbot command line.

  python -m wxbot collect [--loop MINUTES]   snapshot markets + ensemble forecasts
  python -m wxbot observe                    pull observed highs (NWS CLI) for calibration
  python -m wxbot load DIR                   import run files (from --out-dir) into SQLite
  python -m wxbot edges [--min-edge 0.03]    model probability vs current prices (no trading)

collect/observe write to SQLite by default, or to gzipped run files with --out-dir DIR.
"""
import argparse
import logging
import sys
import time
from datetime import datetime, timedelta, timezone

from . import config, kalshi, nws, polymarket, pricing, runlog, store, weather

log = logging.getLogger("wxbot")


def _stations_in_use() -> list[config.Station]:
    return [s for s in config.STATIONS.values() if s.kalshi_series or s.polymarket_names]


def _sink(args, ts):
    if args.out_dir:
        return runlog.JsonlSink(args.out_dir, ts)
    return runlog.SqliteSink(store.connect(args.db), ts)


def _forecasts_due(args, ts: str) -> bool:
    if not (args.out_dir and args.forecast_every):
        return True
    last = runlog.read_state(args.out_dir).get("last_forecast_ts")
    return not last or datetime.fromisoformat(ts) - datetime.fromisoformat(last) >= \
        timedelta(minutes=args.forecast_every)


def collect_once(args) -> int:
    """Run one collection pass; returns the number of sources that failed."""
    ts = store.utcnow()
    sink, failures = _sink(args, ts), 0

    for st in config.STATIONS.values():
        if not st.kalshi_series:
            continue
        try:
            markets = kalshi.fetch_markets(st.kalshi_series)
            n = sink.snapshots([kalshi.to_snapshot(m, st.kalshi_series, ts) for m in markets])
            log.info("kalshi %s: %d markets", st.kalshi_series, n)
        except Exception:
            failures += 1
            log.exception("kalshi %s failed", st.kalshi_series)

    try:
        rows = [r for e in polymarket.fetch_temperature_events() for r in polymarket.to_snapshots(e, ts)]
        log.info("polymarket: %d markets (%d mapped to a station)",
                 sink.snapshots(rows), sum(1 for r in rows if r["station"]))
    except Exception:
        failures += 1
        log.exception("polymarket failed")

    if _forecasts_due(args, ts):
        ok = 0
        for st in _stations_in_use():
            for model in config.ENSEMBLE_MODELS:
                try:
                    by_date = weather.daily_max_by_member(weather.fetch_ensemble(st, model), st.lst_offset)
                    log.info("forecast %s %s: %d rows", st.key, model, sink.forecasts(st.key, model, by_date))
                    ok += 1
                except Exception:
                    failures += 1
                    log.exception("forecast %s %s failed", st.key, model)
            try:
                highs = nws.fetch_forecast_highs(st)
                sink.forecasts(st.key, "nws", {d: [v] for d, v in highs.items()})
                log.info("forecast %s nws: %d days", st.key, len(highs))
            except Exception:
                failures += 1
                log.exception("forecast %s nws failed", st.key)
        if ok and args.out_dir:
            runlog.write_state(args.out_dir, {**runlog.read_state(args.out_dir), "last_forecast_ts": ts})
    else:
        log.info("forecasts not due yet")

    if path := sink.close():
        log.info("wrote %s", path)
    return failures


def cmd_collect(args) -> int:
    while True:
        failures = collect_once(args)
        if not args.loop:
            return 1 if failures and args.strict else 0
        time.sleep(args.loop * 60)


def cmd_observe(args) -> int:
    sink, failures = _sink(args, store.utcnow()), 0
    for st in _stations_in_use():
        try:
            for text in nws.fetch_recent_cli(st, limit=args.limit):
                if parsed := nws.parse_cli(text):
                    sink.observation(st.key, parsed[0], parsed[1], "nws_cli")
                    log.info("obs %s %s: %s°F", st.key, *parsed)
        except Exception:
            failures += 1
            log.exception("observe %s failed", st.key)
    if path := sink.close():
        log.info("wrote %s", path)
    return 1 if failures and args.strict else 0


def cmd_load(args) -> int:
    n = runlog.load(store.connect(args.db), args.dir, since_days=args.since_days)
    log.info("loaded %d run files into %s", n, args.db)
    return 0


def find_edges(conn, min_edge: float, sigma: float) -> list[tuple]:
    """Best side per market whose edge clears `min_edge`.

    Only markets for future climate days are priced: once a day has started, the
    temperatures already observed matter and the forecast alone is misleading.
    Ensembles are recentred on the NWS forecast high; markets without one are skipped.
    """
    fees = {"kalshi": kalshi.taker_fee, "polymarket": lambda p: 0.0}
    now = datetime.now(timezone.utc)
    rows = []
    for s in store.latest_snapshots(conn):
        st = config.STATIONS[s["station"]]
        today_lst = (now + timedelta(hours=st.lst_offset)).date().isoformat()
        if s["target_date"] <= today_lst or (s["lo"] is None and s["hi"] is None):
            continue
        fc = store.latest_forecasts(conn, s["station"], s["target_date"])
        nws_high = (fc.pop("nws", None) or [None])[0]
        members = [t for m in fc.values() for t in m]
        if not members or nws_high is None:
            continue
        p = pricing.bucket_probability(pricing.recenter(members, nws_high), s["lo"], s["hi"], sigma=sigma)
        sides = {k: v for k, v in pricing.edges(p, s["yes_bid"], s["yes_ask"], fees[s["venue"]]).items()
                 if v is not None}
        if not sides:
            continue
        side, edge = max(sides.items(), key=lambda kv: kv[1])
        if edge >= min_edge:
            rows.append((edge, side, p, s, nws_high, len(members)))
    return sorted(rows, key=lambda r: -r[0])


def _fmt(v):
    return "-" if v is None else f"{v:.2f}"


def _bucket(s):
    lo, hi = s["lo"], s["hi"]
    if lo is None:
        return f"≤{hi}"
    if hi is None:
        return f"≥{lo}"
    return f"{lo}–{hi}" if lo != hi else f"{lo}"


def cmd_edges(args) -> int:
    conn = store.connect(args.db)
    rows = find_edges(conn, args.min_edge, args.sigma)
    header = ["venue", "station", "date", "bucket °F", "NWS high", "model p", "bid", "ask", "best side", "edge", "members",
              "price as of"]
    table = [[s["venue"], s["station"], s["target_date"], _bucket(s), f"{hi:.1f}", f"{p:.2f}", _fmt(s["yes_bid"]),
              _fmt(s["yes_ask"]), side, f"{edge:+.2f}", str(n), s["ts"]] for edge, side, p, s, hi, n in rows]

    if args.report:
        counts = conn.execute("""SELECT
            (SELECT COUNT(*) FROM market_snapshots), (SELECT COUNT(DISTINCT market_id) FROM market_snapshots),
            (SELECT MAX(ts) FROM market_snapshots), (SELECT MAX(ts) FROM forecasts),
            (SELECT COUNT(*) FROM observations)""").fetchone()
        with open(args.report, "w") as f:
            f.write("# wxbot edges report\n\n")
            f.write("**Research only — the model is not yet calibrated. Do not trade on this.**\n\n")
            f.write(f"Generated {store.utcnow()} · sigma {args.sigma}°F · min edge {args.min_edge:+.2f}\n\n")
            f.write(f"Snapshots: {counts[0]} ({counts[1]} markets) · latest prices {counts[2]} · "
                    f"latest forecast {counts[3]} · observations {counts[4]}\n\n")
            if table:
                f.write("| " + " | ".join(header) + " |\n|" + "---|" * len(header) + "\n")
                f.writelines("| " + " | ".join(r) + " |\n" for r in table)
            else:
                f.write("_No opportunities above threshold._\n")
        log.info("wrote %s (%d rows)", args.report, len(table))
    else:
        widths = [max(len(h), *(len(r[i]) for r in table)) for i, h in enumerate(header)]
        for r in [header, *table]:
            print("  ".join(c.ljust(w) for c, w in zip(r, widths)))
        if not table:
            print("(no opportunities above threshold)")
    return 0


def main() -> None:
    ap = argparse.ArgumentParser(prog="wxbot")
    ap.add_argument("--db", default=config.DB_PATH)
    ap.add_argument("-v", "--verbose", action="store_true")
    sub = ap.add_subparsers(dest="cmd", required=True)

    def add_output_args(p):
        p.add_argument("--out-dir", help="write gzipped run files here instead of SQLite")
        p.add_argument("--strict", action="store_true", help="exit 1 if any source failed")

    c = sub.add_parser("collect")
    add_output_args(c)
    c.add_argument("--loop", type=float, default=0, help="repeat every N minutes")
    c.add_argument("--forecast-every", type=float, default=0,
                   help="with --out-dir: only fetch forecasts if the last fetch is this many minutes old")
    c.set_defaults(func=cmd_collect)

    o = sub.add_parser("observe")
    add_output_args(o)
    o.add_argument("--limit", type=int, default=10, help="CLI products per station")
    o.set_defaults(func=cmd_observe)

    ld = sub.add_parser("load")
    ld.add_argument("dir")
    ld.add_argument("--since-days", type=float, help="only load run files from the last N days")
    ld.set_defaults(func=cmd_load)

    e = sub.add_parser("edges")
    e.add_argument("--min-edge", type=float, default=0.03)
    e.add_argument("--sigma", type=float, default=config.KERNEL_SIGMA_F)
    e.add_argument("--report", help="write a markdown report to this path instead of printing")
    e.set_defaults(func=cmd_edges)

    args = ap.parse_args()
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    sys.exit(args.func(args))


if __name__ == "__main__":
    main()
