"""SQLite storage. Raw API payloads are kept so parsers can be fixed and re-run later."""
import json
import os
import sqlite3
from datetime import datetime, timezone

SCHEMA = """
CREATE TABLE IF NOT EXISTS market_snapshots (
    ts           TEXT NOT NULL,     -- UTC ISO time of the snapshot
    venue        TEXT NOT NULL,     -- 'kalshi' | 'polymarket'
    market_id    TEXT NOT NULL,     -- Kalshi ticker / Polymarket YES token id
    event_id     TEXT,
    title        TEXT,
    station      TEXT,              -- key into config.STATIONS, NULL if unmapped
    target_date  TEXT,              -- local climate date the market resolves on (YYYY-MM-DD)
    unit         TEXT,              -- 'F' | 'C'
    lo           INTEGER,           -- inclusive lower bound of reported value, NULL = -inf
    hi           INTEGER,           -- inclusive upper bound of reported value, NULL = +inf
    yes_bid      REAL,              -- dollars (0..1)
    yes_ask      REAL,
    last_price   REAL,
    volume       REAL,
    close_time   TEXT,
    raw          TEXT
);
CREATE INDEX IF NOT EXISTS ix_snap_market ON market_snapshots(venue, market_id, ts);
CREATE INDEX IF NOT EXISTS ix_snap_station ON market_snapshots(station, target_date);

CREATE TABLE IF NOT EXISTS forecasts (
    ts           TEXT NOT NULL,     -- UTC time we fetched it
    station      TEXT NOT NULL,
    target_date  TEXT NOT NULL,     -- local-standard-time climate date
    model        TEXT NOT NULL,
    member       INTEGER NOT NULL,
    tmax_f       REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_fc ON forecasts(station, target_date, ts);

CREATE TABLE IF NOT EXISTS observations (
    station      TEXT NOT NULL,
    obs_date     TEXT NOT NULL,
    tmax_f       INTEGER NOT NULL,
    source       TEXT NOT NULL,     -- e.g. 'nws_cli'
    fetched_ts   TEXT NOT NULL,
    raw          TEXT,
    PRIMARY KEY (station, obs_date, source)
);
"""


def utcnow() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def connect(path: str) -> sqlite3.Connection:
    if path != ":memory:":
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


SNAPSHOT_COLS = ("ts", "venue", "market_id", "event_id", "title", "station", "target_date", "unit",
                 "lo", "hi", "yes_bid", "yes_ask", "last_price", "volume", "close_time", "raw")


def insert_snapshots(conn: sqlite3.Connection, rows: list[dict]) -> int:
    if not rows:
        return 0
    data = []
    for r in rows:
        r = dict(r)
        if not isinstance(r.get("raw"), (str, type(None))):
            r["raw"] = json.dumps(r["raw"], separators=(",", ":"))
        data.append(tuple(r.get(c) for c in SNAPSHOT_COLS))
    conn.executemany(
        f"INSERT INTO market_snapshots ({','.join(SNAPSHOT_COLS)}) VALUES ({','.join('?' * len(SNAPSHOT_COLS))})",
        data)
    conn.commit()
    return len(data)


def insert_forecasts(conn: sqlite3.Connection, ts: str, station: str, model: str,
                     by_date: dict[str, list[float]]) -> int:
    data = [(ts, station, d, model, i, t) for d, members in by_date.items() for i, t in enumerate(members)]
    conn.executemany("INSERT INTO forecasts VALUES (?,?,?,?,?,?)", data)
    conn.commit()
    return len(data)


def upsert_observation(conn: sqlite3.Connection, station: str, obs_date: str, tmax_f: int,
                       source: str, raw: str | None = None) -> None:
    conn.execute("INSERT OR REPLACE INTO observations VALUES (?,?,?,?,?,?)",
                 (station, obs_date, tmax_f, source, utcnow(), raw))
    conn.commit()


def latest_snapshots(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    """Most recent snapshot of every market that maps to a station and date."""
    return conn.execute("""
        SELECT * FROM (
            SELECT *, ROW_NUMBER() OVER (PARTITION BY venue, market_id ORDER BY ts DESC, rowid DESC) AS rn
            FROM market_snapshots WHERE station IS NOT NULL AND target_date IS NOT NULL)
        WHERE rn = 1
        ORDER BY station, target_date, lo
    """).fetchall()


def latest_members(conn: sqlite3.Connection, station: str, target_date: str,
                   exclude: tuple[str, ...] = ("nws",)) -> list[float]:
    """Ensemble members from the latest fetch of each model for a station/date."""
    return [t for model, members in latest_forecasts(conn, station, target_date).items()
            if model not in exclude for t in members]


def latest_forecasts(conn: sqlite3.Connection, station: str, target_date: str) -> dict[str, list[float]]:
    """{model: members} from the latest fetch of each model for a station/date."""
    rows = conn.execute("""
        SELECT f.model, f.tmax_f FROM forecasts f
        JOIN (SELECT model, MAX(ts) AS ts FROM forecasts
              WHERE station = ? AND target_date = ? GROUP BY model) m
          ON f.model = m.model AND f.ts = m.ts
        WHERE f.station = ? AND f.target_date = ?
        ORDER BY f.model, f.member
    """, (station, target_date, station, target_date)).fetchall()
    out: dict[str, list[float]] = {}
    for r in rows:
        out.setdefault(r["model"], []).append(r["tmax_f"])
    return out
