"""Pull finished box scores, the upcoming slate with DraftKings lines, and injuries from ESPN."""
import logging
from datetime import date, timedelta

import requests

from . import espn, store

log = logging.getLogger(__name__)

# Regular seasons we backfill by default (ESPN labels a season by the year it ends).
SEASON_STARTS = {2026: "2025-10-21", 2027: "2026-10-20"}
KEEP_TYPES = {espn.REGULAR, espn.POSTSEASON, espn.PLAY_IN}


def days(start: str, end: str):
    d, e = date.fromisoformat(start), date.fromisoformat(end)
    while d <= e:
        yield d.isoformat()
        d += timedelta(days=1)


def fetch_day(root: str, day: str, force: bool = False) -> int:
    """Store every finished game on `day`. Skips days already stored unless force."""
    if store.has_box(root, day) and not force:
        return 0
    events = espn.parse_events(espn.scoreboard(day))
    done = [e for e in events if e["game"]["completed"] and e["game"]["season_type"] in KEEP_TYPES]
    if not done:
        if events and all(e["game"]["state"] == "post" for e in events):
            store.save_box(root, day, [])   # e.g. all postponed: nothing to come back for
        return 0
    if any(e["game"]["state"] != "post" for e in events):
        return 0  # day still in progress; come back when it's over
    games = []
    for e in done:
        try:
            games.append(espn.parse_summary(espn.summary(e["game"]["game_id"])))
        except requests.HTTPError as exc:
            if exc.response is not None and exc.response.status_code == 404:
                log.warning("no summary for %s; skipping that game", e["game"]["game_id"])
                continue
            log.exception("summary %s failed", e["game"]["game_id"])
            return 0
        except Exception:
            log.exception("summary %s failed", e["game"]["game_id"])
            return 0  # don't store a partial day
    store.save_box(root, day, games)
    log.info("%s: %d games", day, len(games))
    return len(games)


def backfill(root: str, start: str, end: str) -> int:
    n = 0
    for day in days(start, end):
        n += fetch_day(root, day)
    return n


def slate(day: str) -> list[dict]:
    """Games on `day` that haven't started, with DraftKings lines."""
    return [e for e in espn.parse_events(espn.scoreboard(day)) if e["game"]["state"] == "pre"]


def update(root: str, today: str) -> dict:
    """Catch up on finished games through yesterday, snapshot injuries, return today's + tomorrow's slate."""
    start = SEASON_STARTS[max(SEASON_STARTS)]
    yesterday = (date.fromisoformat(today) - timedelta(days=1)).isoformat()
    added = backfill(root, start, yesterday)
    inj = espn.parse_injuries(espn.injuries())
    store.save_snapshot(root, "injuries", inj)
    tomorrow = (date.fromisoformat(today) + timedelta(days=1)).isoformat()
    games = slate(today) + slate(tomorrow)
    return {"added": added, "injuries": inj, "slate": games}
