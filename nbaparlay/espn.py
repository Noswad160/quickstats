"""ESPN's public NBA JSON: schedule, box scores, DraftKings lines, injuries.

stats.nba.com and the NBA CDN block cloud servers; ESPN doesn't, and its game summaries keep
DraftKings' opening and closing lines after the game, which makes backtesting possible.
"""
import logging
import re
import time

import requests

log = logging.getLogger(__name__)

BASE = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba"
REGULAR, POSTSEASON, PLAY_IN = 2, 3, 5

_session = requests.Session()
_session.headers["User-Agent"] = "Mozilla/5.0 (compatible; nbaparlay/0.1)"
_ATHLETE_ID = re.compile(r"/id/(\d+)")


def get(path: str, params: dict | None = None, retries: int = 3, pause: float = 0.25) -> dict:
    for attempt in range(retries + 1):
        try:
            r = _session.get(f"{BASE}/{path}", params=params, timeout=30)
            if r.status_code == 429 or r.status_code >= 500:
                raise requests.HTTPError(f"{r.status_code}", response=r)
            r.raise_for_status()
            time.sleep(pause)
            return r.json()
        except (requests.ConnectionError, requests.Timeout, requests.HTTPError) as exc:
            status = getattr(getattr(exc, "response", None), "status_code", None)
            if attempt == retries or (status is not None and 400 <= status < 500 and status != 429):
                raise
            log.warning("ESPN %s failed (%s); retrying", path, exc)
            time.sleep(2 ** (attempt + 1))


def scoreboard(date: str) -> dict:
    """date as YYYY-MM-DD."""
    return get("scoreboard", {"dates": date.replace("-", ""), "limit": 50})


def summary(event_id: str) -> dict:
    return get("summary", {"event": event_id})


def injuries() -> dict:
    return get("injuries")


def _num(x, default=0.0):
    try:
        return float(x)
    except (TypeError, ValueError):
        return default


def _made_att(s: str) -> tuple[int, int]:
    try:
        m, a = s.split("-")
        return int(m), int(a)
    except (AttributeError, ValueError):
        return 0, 0


def _minutes(s) -> float:
    if s in (None, "", "--"):
        return 0.0
    if isinstance(s, str) and ":" in s:
        m, sec = s.split(":")
        return int(m) + int(sec) / 60
    return _num(s)


def _odds(x) -> float | None:
    if x in (None, "", "OFF", "EVEN"):
        return 100.0 if x == "EVEN" else None
    try:
        return float(str(x).replace("+", ""))
    except ValueError:
        return None


def _line(x) -> float | None:
    if x in (None, ""):
        return None
    s = str(x).lstrip("ou").replace("+", "")
    if s.upper() in ("PK", "EVEN"):
        return 0.0
    try:
        return float(s)
    except ValueError:
        return None


def parse_events(board: dict) -> list[dict]:
    """Games on a scoreboard, with DraftKings lines when the game hasn't finished."""
    out = []
    for e in board.get("events", []):
        c = e["competitions"][0]
        teams = {t["homeAway"]: t for t in c["competitors"]}
        g = {
            "game_id": e["id"],
            "start": e["date"],
            "season": e["season"]["year"],
            "season_type": e["season"]["type"],
            "state": e["status"]["type"]["state"],          # pre | in | post
            "completed": e["status"]["type"]["completed"],
            "neutral": bool(c.get("neutralSite")),
            "home_id": teams["home"]["team"]["id"], "home_abbr": teams["home"]["team"]["abbreviation"],
            "away_id": teams["away"]["team"]["id"], "away_abbr": teams["away"]["team"]["abbreviation"],
            "home_name": teams["home"]["team"].get("displayName"), "away_name": teams["away"]["team"].get("displayName"),
            "home_pts": int(_num(teams["home"].get("score"), 0)) if e["status"]["type"]["completed"] else None,
            "away_pts": int(_num(teams["away"].get("score"), 0)) if e["status"]["type"]["completed"] else None,
        }
        odds = (c.get("odds") or [None])[0]
        out.append({"game": g, "lines": parse_lines(odds, e["id"]) if odds else None})
    return out


def parse_lines(o: dict, game_id: str) -> dict:
    """DraftKings open/close spread, total and moneyline from a scoreboard or pickcenter entry."""
    def side(market, key, when):
        m = (o.get(market) or {}).get(key) or {}
        return m.get(when) or {}
    row = {"game_id": game_id, "provider": (o.get("provider") or {}).get("name")}
    for when in ("open", "close"):
        hs = side("pointSpread", "home", when)
        row[f"spread_home_{when}"] = _line(hs.get("line"))
        row[f"spread_home_odds_{when}"] = _odds(hs.get("odds"))
        row[f"spread_away_odds_{when}"] = _odds(side("pointSpread", "away", when).get("odds"))
        ov = side("total", "over", when)
        row[f"total_{when}"] = _line(ov.get("line"))
        row[f"over_odds_{when}"] = _odds(ov.get("odds"))
        row[f"under_odds_{when}"] = _odds(side("total", "under", when).get("odds"))
        row[f"ml_home_{when}"] = _odds(side("moneyline", "home", when).get("odds"))
        row[f"ml_away_{when}"] = _odds(side("moneyline", "away", when).get("odds"))
    # older payloads only carry the current numbers at the top level
    if row["total_close"] is None and o.get("overUnder") is not None:
        row["total_close"] = _num(o.get("overUnder"), None)
    return row


def parse_summary(s: dict) -> dict:
    """A finished game's box score: team rows, player rows, and DraftKings open/close lines."""
    h = s["header"]
    c = h["competitions"][0]
    comp = {t["homeAway"]: t for t in c["competitors"]}
    game_id = h["id"]
    game = {
        "game_id": game_id, "start": c["date"], "season": h["season"]["year"], "season_type": h["season"]["type"],
        "completed": c["status"]["type"]["completed"], "state": c["status"]["type"]["state"],
        "neutral": bool(c.get("neutralSite")),
        "home_id": comp["home"]["team"]["id"], "away_id": comp["away"]["team"]["id"],
        "home_abbr": comp["home"]["team"].get("abbreviation"), "away_abbr": comp["away"]["team"].get("abbreviation"),
        "home_pts": int(_num(comp["home"].get("score"))), "away_pts": int(_num(comp["away"].get("score"))),
    }
    teams = []
    for t in s.get("boxscore", {}).get("teams", []):
        st = {x["name"]: x.get("displayValue") for x in t.get("statistics", [])}
        fgm, fga = _made_att(st.get("fieldGoalsMade-fieldGoalsAttempted"))
        fg3m, fg3a = _made_att(st.get("threePointFieldGoalsMade-threePointFieldGoalsAttempted"))
        ftm, fta = _made_att(st.get("freeThrowsMade-freeThrowsAttempted"))
        oreb, tov = int(_num(st.get("offensiveRebounds"))), int(_num(st.get("totalTurnovers", st.get("turnovers"))))
        side = t.get("homeAway")
        teams.append({
            "game_id": game_id, "team_id": t["team"]["id"], "home": side == "home",
            "pts": game["home_pts"] if side == "home" else game["away_pts"],
            "fgm": fgm, "fga": fga, "fg3m": fg3m, "fg3a": fg3a, "ftm": ftm, "fta": fta,
            "oreb": oreb, "dreb": int(_num(st.get("defensiveRebounds"))), "reb": int(_num(st.get("totalRebounds"))),
            "ast": int(_num(st.get("assists"))), "stl": int(_num(st.get("steals"))), "blk": int(_num(st.get("blocks"))),
            "tov": tov, "poss": round(fga - oreb + tov + 0.44 * fta, 1),
        })
    players = []
    for tp in s.get("boxscore", {}).get("players", []):
        team_id = tp["team"]["id"]
        for block in tp.get("statistics", []):
            keys = block.get("keys") or []
            for a in block.get("athletes", []):
                vals = dict(zip(keys, a.get("stats") or []))
                fgm, fga = _made_att(vals.get("fieldGoalsMade-fieldGoalsAttempted"))
                fg3m, fg3a = _made_att(vals.get("threePointFieldGoalsMade-threePointFieldGoalsAttempted"))
                ftm, fta = _made_att(vals.get("freeThrowsMade-freeThrowsAttempted"))
                ath = a.get("athlete") or {}
                if not ath.get("id"):
                    continue  # occasional unnamed placeholder rows
                players.append({
                    "game_id": game_id, "team_id": team_id, "player_id": ath["id"], "name": ath.get("displayName"),
                    "position": (ath.get("position") or {}).get("abbreviation"),
                    "starter": bool(a.get("starter")), "dnp": bool(a.get("didNotPlay")) or not a.get("stats"),
                    "min": round(_minutes(vals.get("minutes")), 2),
                    "pts": int(_num(vals.get("points"))), "reb": int(_num(vals.get("rebounds"))),
                    "ast": int(_num(vals.get("assists"))), "fg3m": fg3m, "fg3a": fg3a, "fgm": fgm, "fga": fga,
                    "ftm": ftm, "fta": fta, "stl": int(_num(vals.get("steals"))), "blk": int(_num(vals.get("blocks"))),
                    "tov": int(_num(vals.get("turnovers"))), "oreb": int(_num(vals.get("offensiveRebounds"))),
                    "pf": int(_num(vals.get("fouls"))), "pm": int(_num(vals.get("plusMinus"))),
                })
    pick = (s.get("pickcenter") or [None])[0]
    return {"game": game, "teams": teams, "players": players,
            "lines": parse_lines(pick, game_id) if pick else None}


def parse_injuries(d: dict) -> list[dict]:
    out = []
    for team in d.get("injuries", []):
        for i in team.get("injuries", []):
            a = i.get("athlete", {})
            pid = a.get("id")
            if not pid:
                for link in a.get("links", []):
                    if m := _ATHLETE_ID.search(link.get("href", "")):
                        pid = m.group(1)
                        break
            if not pid:
                continue
            out.append({
                "player_id": pid, "name": a.get("displayName"), "team_id": (a.get("team") or {}).get("id") or team.get("id"),
                "status": i.get("status"), "updated": i.get("date"), "comment": i.get("shortComment"),
                "return_date": (i.get("details") or {}).get("returnDate"),
            })
    return out
