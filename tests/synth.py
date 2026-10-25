"""A small fake league with known team strengths, written in the same format as real ESPN data."""
from datetime import date, timedelta

import numpy as np

from nbaparlay import store

TEAMS = {"1": 6.0, "2": 3.0, "3": 0.0, "4": -2.0, "5": -3.0, "6": -4.0}   # true net rating per 100


def player_ids(team: str) -> list[str]:
    return [f"{team}{j:02d}" for j in range(10)]


def make_league(root: str, days: int = 60, seed: int = 0, start: str = "2025-10-21") -> None:
    rng = np.random.default_rng(seed)
    d0 = date.fromisoformat(start)
    ids = list(TEAMS)
    game_no = 0
    minutes_template = np.array([36, 34, 32, 30, 28, 22, 18, 16, 14, 10], float)
    share_template = minutes_template ** 1.6 / (minutes_template ** 1.6).sum()
    for d in range(days):
        day = (d0 + timedelta(days=d)).isoformat()
        order = rng.permutation(ids)
        games = []
        for k in range(0, len(order), 2):
            home, away = order[k], order[k + 1]
            game_no += 1
            gid = str(900000 + game_no)
            poss = rng.normal(100, 4)
            pts = {}
            for side, t, o in (("home", home, away), ("away", away, home)):
                eff = 112 + TEAMS[t] / 2 - TEAMS[o] / 2 + (1.5 if side == "home" else -1.5) + rng.normal(0, 10)
                pts[side] = int(round(poss * eff / 100))
            teams_rows, player_rows = [], []
            for side, t in (("home", home), ("away", away)):
                fga, oreb, tov, fta = 88, 10, 13, 22
                teams_rows.append({"game_id": gid, "team_id": t, "home": side == "home", "pts": pts[side],
                                   "fgm": 40, "fga": fga, "fg3m": 12, "fg3a": 35, "ftm": 17, "fta": fta,
                                   "oreb": oreb, "dreb": 33, "reb": 43, "ast": 25, "stl": 8, "blk": 5,
                                   "tov": tov, "poss": round(poss, 1)})
                mins = np.maximum(0, minutes_template + rng.normal(0, 3, 10))
                mins = mins * 240 / mins.sum()
                shares = rng.dirichlet(share_template * 35)
                for j, pid in enumerate(player_ids(t)):
                    p = int(round(shares[j] * pts[side]))
                    player_rows.append({"game_id": gid, "team_id": t, "player_id": pid, "name": f"Player {pid}",
                                        "position": "G", "starter": j < 5, "dnp": False, "min": round(float(mins[j]), 2),
                                        "pts": p, "reb": int(rng.poisson(mins[j] * (0.25 if j % 2 else 0.12))),
                                        "ast": int(rng.poisson(mins[j] * (0.2 if j % 3 == 0 else 0.08))),
                                        "fg3m": int(min(p // 3, rng.poisson(mins[j] * 0.06))), "fg3a": 0, "fgm": 0,
                                        "fga": 0, "ftm": 0, "fta": 0, "stl": int(rng.poisson(mins[j] * 0.03)),
                                        "blk": int(rng.poisson(mins[j] * 0.02)), "tov": int(rng.poisson(mins[j] * 0.04)),
                                        "oreb": 0, "pf": 2, "pm": 0})
            spread_home = -round((TEAMS[home] - TEAMS[away] + 3) / 2 * 2) / 2
            games.append({
                "game": {"game_id": gid, "start": f"{day}T23:30Z", "season": 2026, "season_type": 2, "completed": True,
                         "state": "post", "neutral": False, "home_id": home, "away_id": away,
                         "home_abbr": f"T{home}", "away_abbr": f"T{away}", "home_pts": pts["home"], "away_pts": pts["away"]},
                "teams": teams_rows, "players": player_rows,
                "lines": {"game_id": gid, "provider": "Draft Kings", "spread_home_close": spread_home,
                          "spread_home_odds_close": -110.0, "spread_away_odds_close": -110.0, "total_close": 224.5,
                          "over_odds_close": -110.0, "under_odds_close": -110.0, "ml_home_close": -150.0,
                          "ml_away_close": 130.0},
            })
        store.save_box(root, day, games)


def upcoming(day: str, home: str = "1", away: str = "6", lines: dict | None = None) -> dict:
    return {"game": {"game_id": "999001", "start": f"{day}T23:30Z", "season": 2026, "season_type": 2, "state": "pre",
                     "completed": False, "neutral": False, "home_id": home, "away_id": away,
                     "home_abbr": f"T{home}", "away_abbr": f"T{away}", "home_name": "Home", "away_name": "Away"},
            "lines": lines}
