"""nbaparlay command line.

  python -m nbaparlay backfill --start 2025-10-21 --end 2026-06-30   store past box scores
  python -m nbaparlay update                  catch up box scores, snapshot injuries
  python -m nbaparlay picks [--date D]        my lines + best bets + parlays for today and tomorrow
  python -m nbaparlay backtest --start S --end E
"""
import argparse
import json
import logging
import os
from datetime import date

import pandas as pd

from . import backtest, espn, ingest, report, slate, store

log = logging.getLogger("nbaparlay")


def _write(path: str | None, text: str) -> None:
    if not path:
        print(text)
        return
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w") as f:
        f.write(text)
    log.info("wrote %s", path)


def cmd_backfill(a):
    log.info("stored %d games", ingest.backfill(a.data, a.start, a.end))


def cmd_update(a):
    res = ingest.update(a.data, a.date)
    log.info("added %d games; %d injuries; %d upcoming games", res["added"], len(res["injuries"]), len(res["slate"]))


def cmd_picks(a):
    box = store.load_box(a.data)
    today = a.date
    games = ingest.slate(today) + ingest.slate((pd.Timestamp(today) + pd.Timedelta(days=1)).date().isoformat())
    injuries = espn.parse_injuries(espn.injuries())
    res = slate.run(box, games, injuries, props=not a.no_props, min_edge=a.min_edge)
    bt = None
    if a.backtest_json and os.path.exists(a.backtest_json):
        bt = json.load(open(a.backtest_json))
    _write(a.out, report.slate_md(res, bt))
    if a.json:
        _write(a.json, json.dumps({"as_of": res["as_of"], "lines": res["lines"],
                                   "singles": [{"bet": p.leg.label, "book": p.leg.book, "price": p.leg.price,
                                                "p_win": p.p_win, "fair": p.fair, "ev": p.ev} for p in res["singles"]],
                                   "parlays": [{"bet": x.label, "price": x.book_price, "p_hit": x.p_hit,
                                                "fair": x.fair_price, "ev": x.ev, "same_game": x.same_game}
                                               for x in res["parlays"]]}, indent=1))
        store.save_snapshot(a.data, "slates", {"as_of": res["as_of"], "lines": res["lines"]})


def cmd_backtest(a):
    box = store.load_box(a.data)
    bt = backtest.run(box, a.start, a.end, n=a.sims)
    s = backtest.summarize(bt)
    log.info("backtest: %s", s)
    _write(a.out, report.backtest_md(s, a.start, a.end))
    if a.json:
        _write(a.json, json.dumps(s, indent=1))


def main() -> None:
    ap = argparse.ArgumentParser(prog="nbaparlay")
    ap.add_argument("--data", default=os.environ.get("NBA_DATA", "data"))
    ap.add_argument("-v", "--verbose", action="store_true")
    sub = ap.add_subparsers(dest="cmd", required=True)

    b = sub.add_parser("backfill")
    b.add_argument("--start", required=True)
    b.add_argument("--end", default=date.today().isoformat())
    b.set_defaults(func=cmd_backfill)

    u = sub.add_parser("update")
    u.add_argument("--date", default=date.today().isoformat())
    u.set_defaults(func=cmd_update)

    p = sub.add_parser("picks")
    p.add_argument("--date", default=date.today().isoformat())
    p.add_argument("--min-edge", type=float, default=0.03)
    p.add_argument("--no-props", action="store_true", help="skip The Odds API even if ODDS_API_KEY is set")
    p.add_argument("--out", help="markdown report path")
    p.add_argument("--json", help="also write machine-readable picks here")
    p.add_argument("--backtest-json", help="backtest summary to quote in the report")
    p.set_defaults(func=cmd_picks)

    t = sub.add_parser("backtest")
    t.add_argument("--start", required=True)
    t.add_argument("--end", required=True)
    t.add_argument("--sims", type=int, default=3000)
    t.add_argument("--out")
    t.add_argument("--json")
    t.set_defaults(func=cmd_backtest)

    a = ap.parse_args()
    logging.basicConfig(level=logging.DEBUG if a.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    a.func(a)


if __name__ == "__main__":
    main()
