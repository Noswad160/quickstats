"""Append-only run files: one gzipped JSONL file per collection run.

Used where a long-lived SQLite file is impractical (e.g. GitHub Actions committing to
a data branch): each run adds a small new file, and `load` rebuilds SQLite from them.
"""
import gzip
import json
import os
from datetime import datetime, timedelta, timezone

from . import store

STATE_FILE = "state.json"


class JsonlSink:
    def __init__(self, root: str, ts: str):
        self.root, self.ts = root, ts
        self.lines: list[dict] = []

    def snapshots(self, rows: list[dict]) -> int:
        for r in rows:
            r = {k: v for k, v in r.items() if k != "raw"}  # keep run files small
            self.lines.append({"t": "snap", **r})
        return len(rows)

    def forecasts(self, station: str, model: str, by_date: dict[str, list[float]]) -> int:
        for d, members in by_date.items():
            self.lines.append({"t": "fc", "ts": self.ts, "station": station, "target_date": d,
                               "model": model, "members": [round(m, 2) for m in members]})
        return sum(len(m) for m in by_date.values())

    def observation(self, station: str, obs_date: str, tmax_f: int, source: str) -> None:
        self.lines.append({"t": "obs", "station": station, "obs_date": obs_date,
                           "tmax_f": tmax_f, "source": source})

    def close(self) -> str | None:
        if not self.lines:
            return None
        dt = datetime.fromisoformat(self.ts)
        base = os.path.join(self.root, "runs", dt.strftime("%Y/%m/%d"), dt.strftime("%H%M%S"))
        os.makedirs(os.path.dirname(base), exist_ok=True)
        path, n = base + ".jsonl.gz", 0
        while os.path.exists(path):  # never overwrite an earlier run from the same second
            n += 1
            path = f"{base}-{n}.jsonl.gz"
        with gzip.open(path, "wt", encoding="utf-8") as f:
            for line in self.lines:
                f.write(json.dumps(line, separators=(",", ":")) + "\n")
        return path


class SqliteSink:
    def __init__(self, conn, ts: str):
        self.conn, self.ts = conn, ts

    def snapshots(self, rows):
        return store.insert_snapshots(self.conn, rows)

    def forecasts(self, station, model, by_date):
        return store.insert_forecasts(self.conn, self.ts, station, model, by_date)

    def observation(self, station, obs_date, tmax_f, source):
        store.upsert_observation(self.conn, station, obs_date, tmax_f, source)

    def close(self):
        return None


def read_state(root: str) -> dict:
    try:
        with open(os.path.join(root, STATE_FILE)) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def write_state(root: str, state: dict) -> None:
    os.makedirs(root, exist_ok=True)
    with open(os.path.join(root, STATE_FILE), "w") as f:
        json.dump(state, f, indent=1, sort_keys=True)


def run_files(root: str, since_days: float | None = None) -> list[str]:
    runs = os.path.join(root, "runs")
    cutoff = None
    if since_days is not None:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=since_days)).strftime("%Y/%m/%d")
    out = []
    for dirpath, _, files in os.walk(runs):
        day = os.path.relpath(dirpath, runs)
        if cutoff and day.count("/") == 2 and day < cutoff:
            continue
        out.extend(os.path.join(dirpath, f) for f in files if f.endswith(".jsonl.gz"))
    return sorted(out)


def load(conn, root: str, since_days: float | None = None) -> int:
    """Import run files into SQLite, skipping files already loaded."""
    conn.execute("CREATE TABLE IF NOT EXISTS loaded_files (path TEXT PRIMARY KEY)")
    done = {r[0] for r in conn.execute("SELECT path FROM loaded_files")}
    n = 0
    for path in run_files(root, since_days):
        rel = os.path.relpath(path, root)
        if rel in done:
            continue
        snaps, fcs = [], []
        with gzip.open(path, "rt", encoding="utf-8") as f:
            for line in f:
                rec = json.loads(line)
                kind = rec.pop("t")
                if kind == "snap":
                    snaps.append(rec)
                elif kind == "fc":
                    fcs.extend((rec["ts"], rec["station"], rec["target_date"], rec["model"], i, m)
                               for i, m in enumerate(rec["members"]))
                elif kind == "obs":
                    store.upsert_observation(conn, rec["station"], rec["obs_date"], rec["tmax_f"], rec["source"])
        store.insert_snapshots(conn, snaps)
        conn.executemany("INSERT INTO forecasts VALUES (?,?,?,?,?,?)", fcs)
        conn.execute("INSERT INTO loaded_files VALUES (?)", (rel,))
        conn.commit()
        n += 1
    return n
