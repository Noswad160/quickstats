import json

import numpy as np
import pandas as pd
import pytest

from nbaparlay import backtest, espn, odds, oddsapi, parlay, report, slate, store, team
from nbaparlay.markets import LOSE, PUSH, WIN, Leg, Priced, my_line, price
from nbaparlay.project import Projector
from nbaparlay.sim import GameProj, PlayerProj, TeamProj, simulate
from tests import synth

FIX = "tests/fixtures/"


def fixture(name):
    return json.load(open(FIX + name))


# --- odds ------------------------------------------------------------------------

def test_odds_conversions():
    assert odds.american_to_decimal(-110) == pytest.approx(1.9091, abs=1e-4)
    assert odds.american_to_decimal(150) == 2.5
    assert odds.decimal_to_american(2.5) == 150 and odds.decimal_to_american(1.5) == -200
    assert odds.fair_american(0.5) == 100
    o, u = odds.devig(-110, -110)
    assert o == pytest.approx(0.5)
    assert odds.ev(0.55, -110) == pytest.approx(0.55 * 1.90909 - 1, abs=1e-4)
    assert odds.kelly(0.5, -110) == 0.0


# --- ESPN parsing (real payloads) ---------------------------------------------------------

def test_parse_upcoming_scoreboard_lines():
    ev = espn.parse_events(fixture("scoreboard_upcoming.json"))
    g, lines = ev[0]["game"], ev[0]["lines"]
    assert g["state"] == "pre" and g["home_abbr"] == "UTAH" and g["away_abbr"] == "LAL"
    assert lines["spread_home_close"] == 6.5 and lines["total_close"] == 236.5
    assert lines["ml_away_close"] == -238 and lines["ml_home_open"] == 210


def test_parse_final_summary():
    s = espn.parse_summary(fixture("summary_final.json"))
    assert s["game"]["home_pts"] == 115 and s["game"]["away_pts"] == 110
    by_team = {t["team_id"]: t for t in s["teams"]}
    for tid, t in by_team.items():
        assert sum(p["pts"] for p in s["players"] if p["team_id"] == tid) == t["pts"]
        assert 85 < t["poss"] < 120
    assert s["lines"]["spread_home_open"] == 3.5 and s["lines"]["spread_home_close"] == 4.5
    dnp = [p for p in s["players"] if p["dnp"]]
    assert dnp and all(p["min"] == 0 for p in dnp)


def test_parse_injuries_gets_ids_from_links():
    inj = espn.parse_injuries(fixture("injuries.json"))
    assert len(inj) > 50 and all(i["player_id"].isdigit() for i in inj)
    assert {i["status"] for i in inj} <= {"Out", "Day-To-Day", "Questionable", "Doubtful", "Probable"}


# --- team model -------------------------------------------------------------------------

@pytest.fixture(scope="module")
def league(tmp_path_factory):
    root = str(tmp_path_factory.mktemp("league"))
    synth.make_league(root, days=60)
    return root, store.load_box(root)


def test_team_ratings_recover_true_order(league):
    _, box = league
    r = team.fit(team.add_rest(box.teams), pd.Timestamp("2026-01-01", tz="UTC"))
    net = {t: r.off[t] - r.deff[t] for t in synth.TEAMS}
    assert sorted(net, key=net.get, reverse=True)[:2] == ["1", "2"]
    assert net["1"] - net["6"] > 4
    assert 1 < r.home_edge < 6
    hp, ap, poss = r.expected("1", "6")
    assert hp > ap and 90 < poss < 110


# --- simulation ------------------------------------------------------------------------------

def toy_game(play_prob=1.0):
    def team_(tid, pts):
        players = [PlayerProj(f"{tid}{j}", f"P{tid}{j}", minutes=m, minutes_sd=4,
                              rates={"pts": 0.5 if j == 0 else 0.4, "reb": 0.2, "ast": 0.1, "fg3m": 0.05,
                                     "stl": 0.03, "blk": 0.02, "tov": 0.04},
                              play_prob=play_prob if j == 0 else 1.0, starter=j < 5)
                   for j, m in enumerate([36, 34, 32, 30, 28, 24, 20, 18, 12, 6])]
        return TeamProj(tid, tid, pts, players)
    return GameProj("g1", team_("H", 116), team_("A", 108))


def test_simulation_matches_team_expectations():
    sim = simulate(toy_game(), n=20000, seed=1)
    assert np.mean(sim.home.points) == pytest.approx(116, abs=1.5)
    assert np.mean(sim.away.points) == pytest.approx(108, abs=1.5)
    assert 9 < np.std(sim.home.points) < 16
    assert np.mean(sim.margin) == pytest.approx(8, abs=1.5)


def test_simulation_correlates_teammates_and_game_total():
    sim = simulate(toy_game(), n=20000, seed=2)
    star = sim.player_stat("H0", "pts")
    teammate = sim.player_stat("H1", "pts")
    assert np.corrcoef(star, sim.total)[0, 1] > 0.15            # star scoring moves with the total
    assert np.corrcoef(star, teammate)[0, 1] < 0.1             # teammates compete for shots
    assert np.all(sim.player_stat("H0", "pra") == star + sim.player_stat("H0", "reb") + sim.player_stat("H0", "ast"))


def test_questionable_star_sometimes_sits_and_team_scores_less():
    full = simulate(toy_game(1.0), n=20000, seed=3)
    q = simulate(toy_game(0.5), n=20000, seed=3)
    assert np.mean(q.home.played["H0"]) == pytest.approx(0.5, abs=0.02)
    assert np.mean(q.home.points) < np.mean(full.home.points)
    # without the star, his teammates get more shots
    sat = ~q.home.played["H0"]
    assert np.mean(q.player_stat("H1", "pts")[sat]) > np.mean(q.player_stat("H1", "pts")[~sat])


# --- markets ----------------------------------------------------------------------------------

def test_prop_pushes_when_player_sits():
    sim = simulate(toy_game(0.0), n=2000, seed=4)
    o = Leg("g1", "prop", "over", 10.5, -110, player_id="H0", player="P", stat="pts").outcome(sim)
    assert np.all(o == PUSH)


def test_spread_total_and_moneyline_outcomes_agree():
    sim = simulate(toy_game(), n=5000, seed=5)
    home_ml = Leg("g1", "moneyline", "home", None, None).outcome(sim)
    away_ml = Leg("g1", "moneyline", "away", None, None).outcome(sim)
    assert np.all((home_ml == WIN) != (away_ml == WIN))
    over = Leg("g1", "total", "over", 224, None).outcome(sim)
    under = Leg("g1", "total", "under", 224, None).outcome(sim)
    assert np.all((over == PUSH) == (under == PUSH))
    home_minus = Leg("g1", "spread", "home", -8.5, None).outcome(sim)
    assert np.mean(home_minus == WIN) == pytest.approx(np.mean(sim.margin > 8.5))


def test_my_line_is_the_even_split():
    x = np.random.default_rng(0).poisson(22, 20000)
    line = my_line(x)
    assert line in (21.5, 22.5) and abs(np.mean(x > line) - 0.5) < 0.06


# --- parlays ----------------------------------------------------------------------------------

def test_cross_game_parlay_ev_multiplies_independent_edges():
    sims = {"g1": simulate(toy_game(), n=20000, seed=6), "g2": simulate(toy_game(), n=20000, seed=7)}
    legs = [Leg("g1", "moneyline", "home", None, +120, "B", team="H"),
            Leg("g2", "moneyline", "home", None, +120, "B", team="H")]
    priced = [price(l, sims[l.game_id]) for l in legs]
    found = parlay.build(parlay.candidates(priced, min_edge=0.0), sims)
    x = next(p for p in found if not p.same_game)
    assert x.p_hit == pytest.approx(priced[0].p_win * priced[1].p_win, abs=0.015)
    assert x.ev == pytest.approx(x.p_hit * odds.american_to_decimal(120) ** 2 - 1, abs=0.04)
    assert x.book_price == odds.decimal_to_american(odds.american_to_decimal(120) ** 2)


def test_same_game_parlay_captures_correlation():
    sim = simulate(toy_game(), n=20000, seed=8)
    over = Leg("g1", "total", "over", 224, +100, "B")
    star = Leg("g1", "prop", "over", 17.5, +100, "B", player_id="H0", player="Star", stat="pts")
    pa, pb = price(over, sim), price(star, sim)
    found = parlay.build(parlay.candidates([pa, pb], min_edge=-1, min_prob=0), {"g1": sim})
    x = next(p for p in found if p.same_game)
    assert x.ev is None and x.book_price is None
    assert x.p_hit > pa.p_win * pb.p_win   # positively correlated legs hit together more often


def test_candidates_keep_one_side_per_market():
    sim = simulate(toy_game(), n=4000, seed=9)
    legs = [price(Leg("g1", "total", s, 200, +300, "B"), sim) for s in ("over", "under")]
    assert len(parlay.candidates(legs, min_edge=-1, min_prob=0)) == 1


# --- end to end on the fake league -----------------------------------------------------------------

def test_slate_run_produces_lines_and_prices(league):
    _, box = league
    day = "2025-12-25"
    lines = {"spread_home_close": -2.5, "spread_home_odds_close": -110.0, "spread_away_odds_close": -110.0,
             "total_close": 224.5, "over_odds_close": -110.0, "under_odds_close": -110.0,
             "ml_home_close": -130.0, "ml_away_close": 110.0}
    res = slate.run(box, [synth.upcoming(day, lines=lines)], injuries=[], as_of=pd.Timestamp(day, tz="UTC"),
                    props=False, n=4000, min_edge=-1)
    g = res["lines"][0]["game"]
    assert g["spread_home"] < -2           # best team at home vs worst: well clear of a 2.5 favorite
    assert res["singles"] and any(p.leg.market == "spread" and p.leg.side == "home" for p in res["singles"])
    md = report.slate_md(res)
    assert "My lines" in md and "T1" in md


def test_injured_player_drops_out_of_projection(league):
    _, box = league
    day = pd.Timestamp("2025-12-25", tz="UTC")
    star = synth.player_ids("1")[0]
    p = Projector(box, day, injuries=[{"player_id": star, "status": "Out"}])
    gp = p.game(synth.upcoming("2025-12-25")["game"])
    assert next(x for x in gp.home.players if x.player_id == star).play_prob == 0
    healthy = Projector(box, day).game(synth.upcoming("2025-12-25")["game"])
    sims = simulate(gp, n=4000, seed=1), simulate(healthy, n=4000, seed=1)
    assert np.mean(sims[0].home.points) < np.mean(sims[1].home.points)


def test_backtest_runs_and_summarizes(league):
    _, box = league
    bt = backtest.run(box, "2025-12-01", "2025-12-10", n=1000, min_history_games=50)
    s = backtest.summarize(bt)
    assert s["games"] == 30 and s["spread_mae_model"] > 0 and s["player_games"] > 100
    assert "Backtest" in report.backtest_md(s, "2025-12-01", "2025-12-10")


def test_store_roundtrip(tmp_path):
    synth.make_league(str(tmp_path), days=3)
    box = store.load_box(str(tmp_path))
    assert len(box.games) == 9 and len(box.teams) == 18 and set(box.teams["opp_id"]) == set(synth.TEAMS)


# --- odds api parsing ----------------------------------------------------------------------------

def test_props_parse_and_best_price():
    payload = {"bookmakers": [
        {"key": "dk", "title": "DraftKings", "markets": [{"key": "player_points", "outcomes": [
            {"name": "Over", "description": "Luka Dončić", "price": -115, "point": 30.5},
            {"name": "Under", "description": "Luka Dončić", "price": -105, "point": 30.5}]}]},
        {"key": "fd", "title": "FanDuel", "markets": [{"key": "player_points", "outcomes": [
            {"name": "Over", "description": "Luka Doncic", "price": -108, "point": 30.5}]}]}]}
    legs = oddsapi.parse_props(payload, "g1", {oddsapi.norm_name("Luka Doncic"): "3945274"})
    best = oddsapi.best_prices(legs)
    over = next(l for l in best if l.side == "over")
    assert over.book == "FanDuel" and over.price == -108 and over.stat == "pts" and over.player_id == "3945274"
    assert len(best) == 2


def test_summary_skips_player_rows_without_ids():
    raw = fixture("summary_final.json")
    raw["boxscore"]["players"][0]["statistics"][0]["athletes"].append({"athlete": {"displayName": "TEAM"}, "stats": []})
    s = espn.parse_summary(raw)
    assert all(p["player_id"] for p in s["players"])
