"""Call log in SQLite."""
import json
import os
import sqlite3
from datetime import datetime, timezone

SCHEMA = """
CREATE TABLE IF NOT EXISTS calls (
    call_sid     TEXT PRIMARY KEY,
    caller       TEXT,
    started      TEXT NOT NULL,   -- UTC ISO
    seconds      REAL,
    mode         TEXT,            -- spam | legit | screening (caller left during screening)
    persona      TEXT,
    reason       TEXT,            -- why the screener decided
    message      TEXT,            -- summary texted to the owner, for real callers
    transcript   TEXT             -- JSON list of {t, role, text}, if transcripts are saved
);
"""


def connect(path: str) -> sqlite3.Connection:
    if path != ":memory:":
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


def save_call(conn, *, call_sid: str, caller: str, started: float, seconds: float, mode: str,
              persona: str, reason: str, message: str | None, transcript: list | None) -> None:
    conn.execute("INSERT OR REPLACE INTO calls VALUES (?,?,?,?,?,?,?,?,?)", (
        call_sid, caller, datetime.fromtimestamp(started, timezone.utc).isoformat(timespec="seconds"),
        round(seconds, 1), mode, persona, reason, message,
        None if transcript is None else json.dumps(transcript)))
    conn.commit()


def minutes_today(conn) -> float:
    today = datetime.now(timezone.utc).date().isoformat()
    row = conn.execute("SELECT COALESCE(SUM(seconds), 0) FROM calls WHERE started >= ?", (today,)).fetchone()
    return row[0] / 60


def recent_calls(conn, limit: int = 50) -> list[dict]:
    rows = conn.execute("SELECT * FROM calls ORDER BY started DESC LIMIT ?", (limit,)).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["transcript"] = json.loads(d["transcript"]) if d["transcript"] else None
        out.append(d)
    return out
