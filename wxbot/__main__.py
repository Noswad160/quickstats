"""wxbot command line.

  python -m wxbot collect [--loop MINUTES]   snapshot markets + ensemble forecasts
  python -m wxbot observe                    pull observed highs (NWS CLI) for calibration
  python -m wxbot edges [--min-edge 0.03]    model probability vs current prices (no trading)
"""
import argparse
import logging
import time

from . import config, kalshi, nws, polymarket, pricing, store, weather

log = logging.getLogger("wxbot")


def _stations_in_use() -> list[config.Station]:
    return [s for s in config.STATIONS.values() if s.kalshi_series or s.polymarket_names]


def collect_once(conn) -> None:
    ts = store.utcnow()

    for st in config.STATIONS.values():
        if not st.kalshi_series:
            continue
        try:
            markets = kalshi.fetch_markets(st.kalshi_series)
            n = store.insert_snapshots(conn, [kalshi.to_snapshot(m, st.kalshi_series, ts) for m in markets])
            log.info("kalshi %s: %d markets", st.kalshi_series, n)
        except Exception:
            log.exception("kalshi %s failed", st.kalshi_series)

    try:
        rows = [r for e in polymarket.fetch_temperature_events() for r in polymarket.to_snapshots(e, ts)]
        log.info("polymarket: %d markets (%d mapped to a station)",
                 store.insert_snapshots(conn, rows), sum(1 for r in rows if r["station"]))
    except Exception:
        log.exception("polymarket failed")

    for st in _stations_in_use():
        for model in config.ENSEMBLE_MODELS:
            try:
                by_date = weather.daily_max_by_member(weather.fetch_ensemble(st, model), st.lst_offset)
                log.info("forecast %s %s: %d rows", st.key, model,
                         store.insert_forecasts(conn, ts, st.key, model, by_date))
            except Exception:
                log.exception("forecast %s %s failed", st.key, model)


def cmd_collect(args) -> None:
    conn = store.connect(args.db)
    while True:
        collect_once(conn)
        if not args.loop:
            return
        time.sleep(args.loop * 60)


def cmd_observe(args) -> None:
    conn = store.connect(args.db)
    for st in _stations_in_use():
        try:
            for text in nws.fetch_recent_cli(st, limit=args.limit):
                parsed = nws.parse_cli(text)
                if parsed:
                    store.upsert_observation(conn, st.key, parsed[0], parsed[1], "nws_cli", text)
                    log.info("obs %s %s: %s°F", st.key, *parsed)
        except Exception:
            log.exception("observe %s failed", st.key)


def cmd_edges(args) -> None:
    conn = store.connect(args.db)
    fees = {"kalshi": kalshi.taker_fee, "polymarket": lambda p: 0.0}
    rows = []
    for s in store.latest_snapshots(conn):
        members = store.latest_members(conn, s["station"], s["target_date"])
        if not members or (s["lo"] is None and s["hi"] is None):
            continue
        p = pricing.bucket_probability(members, s["lo"], s["hi"], sigma=args.sigma)
        e = pricing.edges(p, s["yes_bid"], s["yes_ask"], fees[s["venue"]])
        best = max((v, k) for k, v in e.items() if v is not None) if any(v is not None for v in e.values()) else None
        if best and best[0] >= args.min_edge:
            rows.append((best[0], best[1], p, s, len(members)))

    rows.sort(key=lambda r: -r[0])
    print(f"{'venue':10} {'stn':4} {'date':10} {'bucket':>9} {'model':>6} {'bid':>5} {'ask':>5} "
          f"{'side':7} {'edge':>6} n  snapshot")
    for edge, side, p, s, n in rows:
        b = f"{'' if s['lo'] is None else s['lo']}..{'' if s['hi'] is None else s['hi']}"
        fmt = lambda v: "  -  " if v is None else f"{v:5.2f}"
        print(f"{s['venue']:10} {s['station']:4} {s['target_date']:10} {b:>9} {p:6.2f} {fmt(s['yes_bid'])} "
              f"{fmt(s['yes_ask'])} {side:7} {edge:+6.2f} {n:<3}{s['ts']}")
    if not rows:
        print("(no opportunities above threshold)")


def main() -> None:
    ap = argparse.ArgumentParser(prog="wxbot")
    ap.add_argument("--db", default=config.DB_PATH)
    ap.add_argument("-v", "--verbose", action="store_true")
    sub = ap.add_subparsers(dest="cmd", required=True)

    c = sub.add_parser("collect")
    c.add_argument("--loop", type=float, default=0, help="repeat every N minutes")
    c.set_defaults(func=cmd_collect)

    o = sub.add_parser("observe")
    o.add_argument("--limit", type=int, default=10, help="CLI products per station")
    o.set_defaults(func=cmd_observe)

    e = sub.add_parser("edges")
    e.add_argument("--min-edge", type=float, default=0.03)
    e.add_argument("--sigma", type=float, default=config.KERNEL_SIGMA_F)
    e.set_defaults(func=cmd_edges)

    args = ap.parse_args()
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    args.func(args)


if __name__ == "__main__":
    main()
