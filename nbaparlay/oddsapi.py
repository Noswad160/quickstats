"""Player prop prices from The Odds API (the-odds-api.com). Optional: needs ODDS_API_KEY.

Props cost one credit per market per region per game, so a 12-game night with 8 markets is ~100
credits. The free tier (500/month) covers a few nights; the $30 tier covers a season.
"""
import logging
import os
import re
import unicodedata

import requests

from .markets import Leg

log = logging.getLogger(__name__)

BASE = "https://api.the-odds-api.com/v4/sports/basketball_nba"
MARKETS = {
    "player_points": "pts", "player_rebounds": "reb", "player_assists": "ast", "player_threes": "fg3m",
    "player_points_rebounds_assists": "pra", "player_points_rebounds": "pr", "player_points_assists": "pa",
    "player_rebounds_assists": "ra",
}
DEFAULT_BOOKS = "draftkings,fanduel,betmgm,williamhill_us,espnbet,betrivers,fanatics"


def norm_name(name: str) -> str:
    s = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower()
    s = re.sub(r"[.'’\-]", "", s)
    s = re.sub(r"\b(jr|sr|ii|iii|iv)\b", "", s)
    return " ".join(s.split())


def _get(path: str, key: str, **params) -> list | dict:
    r = requests.get(f"{BASE}/{path}", params={"apiKey": key, **params}, timeout=30)
    r.raise_for_status()
    log.info("odds api %s: %s credits left", path, r.headers.get("x-requests-remaining"))
    return r.json()


def events(key: str) -> list[dict]:
    return _get("events", key)


def event_props(key: str, event_id: str, books: str = DEFAULT_BOOKS) -> dict:
    return _get(f"events/{event_id}/odds", key, regions="us", markets=",".join(MARKETS),
                oddsFormat="american", bookmakers=books)


def parse_props(payload: dict, game_id: str, players: dict[str, str]) -> list[Leg]:
    """players: normalized name -> ESPN player id for everyone we simulated in this game."""
    legs = []
    for book in payload.get("bookmakers", []):
        for m in book.get("markets", []):
            stat = MARKETS.get(m.get("key"))
            if not stat:
                continue
            for o in m.get("outcomes", []):
                pid = players.get(norm_name(o.get("description", "")))
                side = (o.get("name") or "").lower()
                if not pid or side not in ("over", "under") or o.get("point") is None:
                    continue
                legs.append(Leg(game_id=game_id, market="prop", side=side, line=float(o["point"]),
                                price=float(o["price"]), book=book.get("title", book.get("key", "")),
                                player_id=pid, player=o["description"], stat=stat))
    return legs


def best_prices(legs: list[Leg]) -> list[Leg]:
    """For each exact bet (player, stat, side, line), keep the book paying the most."""
    best: dict[tuple, Leg] = {}
    for leg in legs:
        k = (leg.game_id, leg.player_id, leg.stat, leg.side, leg.line)
        if k not in best or leg.price > best[k].price:
            best[k] = leg
    return list(best.values())


def match_events(evs: list[dict], slate: list[dict]) -> dict[str, str]:
    """ESPN game id -> Odds API event id, matched on team names."""
    out = {}
    for g in slate:
        for e in evs:
            if e.get("home_team") == g.get("home_name") and e.get("away_team") == g.get("away_name"):
                out[g["game_id"]] = e["id"]
    return out


def fetch_props(slate: list[dict], sims: dict, key: str | None = None) -> list[Leg]:
    key = key or os.environ.get("ODDS_API_KEY")
    if not key:
        return []
    ids = match_events(events(key), slate)
    legs = []
    for game_id, event_id in ids.items():
        if game_id not in sims:
            continue
        names = {norm_name(p.name): pid for pid, (_, p) in sims[game_id].players.items()}
        try:
            legs += parse_props(event_props(key, event_id), game_id, names)
        except requests.HTTPError:
            log.exception("props for %s failed", game_id)
    return best_prices(legs)
