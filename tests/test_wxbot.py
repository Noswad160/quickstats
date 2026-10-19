import pytest

from wxbot import config, kalshi, nws, polymarket, pricing, store, weather


# --- pricing -----------------------------------------------------------------

def test_bucket_probabilities_sum_to_one():
    members = [68.2, 70.1, 71.4, 73.0, 69.9]
    buckets = [(None, 65), (66, 67), (68, 69), (70, 71), (72, 73), (74, None)]
    total = sum(pricing.bucket_probability(members, lo, hi) for lo, hi in buckets)
    assert total == pytest.approx(1.0)


def test_bucket_probability_concentrates_with_small_sigma():
    p = pricing.bucket_probability([70.0] * 10, 70, 71, sigma=0.2)
    assert p > 0.99
    assert pricing.bucket_probability([70.0], 72, None, sigma=0.2) < 1e-6


def test_bias_shifts_probability():
    base = pricing.bucket_probability([70.0], 72, None)
    assert pricing.bucket_probability([70.0], 72, None, bias=2.0) > base


def test_edges_after_fee():
    e = pricing.edges(0.60, yes_bid=0.45, yes_ask=0.50, fee=lambda p: 0.02)
    assert e["buy_yes"] == pytest.approx(0.60 - 0.50 - 0.02)
    assert e["buy_no"] == pytest.approx(0.40 - 0.55 - 0.02)


# --- kalshi ------------------------------------------------------------------

def test_kalshi_fee_rounds_up_to_cent():
    assert kalshi.taker_fee(0.50) == pytest.approx(0.02)       # 1.75c -> 2c
    assert kalshi.taker_fee(0.50, contracts=100) == pytest.approx(1.75)
    assert kalshi.taker_fee(0.99) == pytest.approx(0.01)


def test_kalshi_event_date():
    assert kalshi.event_date("KXHIGHNY-26OCT20") == "2026-10-20"
    assert kalshi.event_date("garbage") is None


@pytest.mark.parametrize("market,expected", [
    ({"strike_type": "between", "floor_strike": 70, "cap_strike": 71}, (70, 71)),
    ({"strike_type": "greater", "floor_strike": 75}, (76, None)),
    ({"strike_type": "less", "cap_strike": 64}, (None, 63)),
    ({"strike_type": "custom"}, (None, None)),
])
def test_kalshi_bucket(market, expected):
    assert kalshi.bucket(market) == expected


def test_kalshi_snapshot_prices_in_cents_and_dollars():
    m = {"ticker": "KXHIGHNY-26OCT20-B70.5", "event_ticker": "KXHIGHNY-26OCT20",
         "strike_type": "between", "floor_strike": 70, "cap_strike": 71,
         "yes_bid": 31, "yes_ask_dollars": "0.3400", "last_price": 0, "volume": 1200}
    s = kalshi.to_snapshot(m, "KXHIGHNY", "2026-10-19T12:00:00+00:00")
    assert s["station"] == "NYC" and s["target_date"] == "2026-10-20"
    assert s["yes_bid"] == pytest.approx(0.31) and s["yes_ask"] == pytest.approx(0.34)
    assert (s["lo"], s["hi"]) == (70, 71)


def test_kalshi_empty_book_side_is_missing():
    m = {"ticker": "T", "event_ticker": "KXHIGHNY-26OCT20", "strike_type": "greater",
         "floor_strike": 90, "yes_bid": 0, "yes_ask": 100}
    s = kalshi.to_snapshot(m, "KXHIGHNY", "ts")
    assert s["yes_bid"] is None and s["yes_ask"] is None


# --- polymarket --------------------------------------------------------------

@pytest.mark.parametrize("label,expected", [
    ("74-75°F", (74, 75, "F")),
    ("77°F or higher", (77, None, "F")),
    ("60°F or below", (None, 60, "F")),
    ("12°C", (12, 12, "C")),
    ("-3°C or below", (None, -3, "C")),
    ("something else", (None, None, None)),
])
def test_polymarket_bucket(label, expected):
    assert polymarket.parse_bucket(label) == expected


def test_polymarket_snapshots():
    event = {
        "id": 123, "title": "Highest temperature in NYC on October 20?", "endDate": "2026-10-21T00:00:00Z",
        "markets": [
            {"question": "Will the highest temperature in NYC be between 74-75°F on October 20?",
             "groupItemTitle": "74-75°F", "clobTokenIds": '["111", "222"]',
             "bestBid": 0.21, "bestAsk": "0.24", "volumeNum": 5000},
            {"groupItemTitle": "77°F or higher", "clobTokenIds": '["333", "444"]', "closed": True},
        ],
    }
    rows = polymarket.to_snapshots(event, "2026-10-19T12:00:00+00:00")
    assert len(rows) == 1
    r = rows[0]
    assert r["market_id"] == "111" and r["station"] == "LGA" and r["target_date"] == "2026-10-20"
    assert (r["lo"], r["hi"], r["yes_bid"], r["yes_ask"]) == (74, 75, 0.21, 0.24)


def test_polymarket_celsius_markets_not_mapped():
    event = {"id": 1, "title": "Highest temperature in Miami on July 4?", "endDate": "2026-07-05",
             "markets": [{"groupItemTitle": "30°C", "clobTokenIds": '["9"]'}]}
    assert polymarket.to_snapshots(event, "ts")[0]["station"] is None


# --- weather -----------------------------------------------------------------

def test_daily_max_uses_local_standard_time():
    # 48 UTC hours starting 2026-10-19T05:00Z == local-standard midnight at UTC-5.
    times = [f"2026-10-{19 + (5 + h) // 24:02d}T{(5 + h) % 24:02d}:00" for h in range(48)]
    m0 = [60.0] * 48
    m0[15] = 72.0          # day 1 peak
    m0[47] = 80.0          # last hour of day 2 (still 2026-10-20 LST)
    m1 = [61.0] * 48
    payload = {"hourly": {"time": times, "temperature_2m": m0, "temperature_2m_member01": m1}}
    out = weather.daily_max_by_member(payload, lst_offset=-5)
    assert out == {"2026-10-19": [72.0, 61.0], "2026-10-20": [80.0, 61.0]}


def test_daily_max_drops_partial_days():
    times = [f"2026-10-19T{h:02d}:00" for h in range(24)]  # UTC day -> splits across two LST days
    payload = {"hourly": {"time": times, "temperature_2m": [50.0] * 24}}
    assert weather.daily_max_by_member(payload, lst_offset=-6) == {}


# --- nws ---------------------------------------------------------------------

CLI_SAMPLE = """
CLIMATE REPORT
NATIONAL WEATHER SERVICE NEW YORK NY
...THE CENTRAL PARK NY CLIMATE SUMMARY FOR OCTOBER 18 2026...

WEATHER ITEM   OBSERVED TIME   RECORD YEAR NORMAL DEPARTURE LAST
                VALUE   (LST)  VALUE       VALUE  FROM      YEAR
...................................................................
TEMPERATURE (F)
 YESTERDAY
  MAXIMUM         68   2:51 PM  85    1908  63      5       71
  MINIMUM         52   6:12 AM  34    1940  49      3       55
"""


def test_parse_cli():
    assert nws.parse_cli(CLI_SAMPLE) == ("2026-10-18", 68)
    assert nws.parse_cli("nothing here") is None


# --- store -------------------------------------------------------------------

def test_store_roundtrip_latest():
    conn = store.connect(":memory:")
    base = {"venue": "kalshi", "market_id": "M1", "station": "NYC", "target_date": "2026-10-20",
            "unit": "F", "lo": 70, "hi": 71, "raw": {"a": 1}}
    store.insert_snapshots(conn, [{**base, "ts": "2026-10-19T10:00:00", "yes_ask": 0.30},
                                  {**base, "ts": "2026-10-19T11:00:00", "yes_ask": 0.35}])
    latest = store.latest_snapshots(conn)
    assert len(latest) == 1 and latest[0]["yes_ask"] == 0.35

    store.insert_forecasts(conn, "t1", "NYC", "gfs025", {"2026-10-20": [60.0, 61.0]})
    store.insert_forecasts(conn, "t2", "NYC", "gfs025", {"2026-10-20": [70.0, 71.0]})
    store.insert_forecasts(conn, "t1", "NYC", "ecmwf_ifs025", {"2026-10-20": [72.0]})
    assert sorted(store.latest_members(conn, "NYC", "2026-10-20")) == [70.0, 71.0, 72.0]


def test_every_kalshi_series_maps_to_a_station():
    for series, key in config.KALSHI_SERIES_TO_STATION.items():
        assert config.STATIONS[key].kalshi_series == series


# --- run files ---------------------------------------------------------------

def test_runlog_roundtrip(tmp_path):
    from wxbot import runlog
    sink = runlog.JsonlSink(str(tmp_path), "2026-10-19T12:00:00+00:00")
    sink.snapshots([{"ts": "2026-10-19T12:00:00+00:00", "venue": "kalshi", "market_id": "M1",
                     "station": "NYC", "target_date": "2026-10-20", "unit": "F", "lo": 70, "hi": 71,
                     "yes_bid": 0.1, "yes_ask": 0.14, "raw": {"big": "payload"}}])
    sink.forecasts("NYC", "gfs025", {"2026-10-20": [70.123, 71.0]})
    sink.observation("NYC", "2026-10-18", 68, "nws_cli")
    assert sink.close().endswith("runs/2026/10/19/120000.jsonl.gz")

    conn = store.connect(":memory:")
    assert runlog.load(conn, str(tmp_path)) == 1
    assert runlog.load(conn, str(tmp_path)) == 0  # incremental
    snap = store.latest_snapshots(conn)[0]
    assert snap["yes_ask"] == 0.14 and snap["raw"] is None
    assert store.latest_members(conn, "NYC", "2026-10-20") == [70.12, 71.0]
    assert conn.execute("SELECT tmax_f FROM observations").fetchone()[0] == 68


def test_recenter_keeps_spread():
    out = pricing.recenter([60.0, 62.0, 64.0], 66.0)
    assert out == [64.0, 66.0, 68.0]
    assert pricing.recenter([60.0], None) == [60.0]


def test_nws_forecast_highs():
    grid = {"properties": {"maxTemperature": {"uom": "wmoUnit:degC", "values": [
        {"validTime": "2026-10-19T12:00:00+00:00/PT13H", "value": 20.0},
        {"validTime": "2026-10-20T12:00:00+00:00/PT13H", "value": None},
    ]}}}
    assert nws.forecast_highs(grid, -5) == {"2026-10-19": 68.0}


def test_find_edges_skips_today_and_requires_nws():
    from datetime import datetime, timedelta, timezone
    from wxbot.__main__ import find_edges
    conn = store.connect(":memory:")
    today = (datetime.now(timezone.utc) - timedelta(hours=5)).date()
    tomorrow = (today + timedelta(days=1)).isoformat()
    rows = [{"ts": "t", "venue": "kalshi", "market_id": f"M{d}", "station": "NYC", "target_date": d,
             "unit": "F", "lo": 70, "hi": 71, "yes_bid": 0.01, "yes_ask": 0.02}
            for d in (today.isoformat(), tomorrow)]
    store.insert_snapshots(conn, rows)
    for d in (today.isoformat(), tomorrow):
        store.insert_forecasts(conn, "t", "NYC", "gfs025", {d: [60.0, 62.0]})
    assert find_edges(conn, 0.0, 2.0) == []          # no NWS high yet
    store.insert_forecasts(conn, "t", "NYC", "nws", {tomorrow: [70.5]})
    found = find_edges(conn, 0.0, 2.0)
    assert [r[3]["target_date"] for r in found] == [tomorrow]
    assert found[0][1] == "buy_yes" and found[0][4] == 70.5
