"""SQLite storage for KhetSaathi: a TTL cache, source health with a circuit breaker, and an advice log.

The database file lives at data/khetsaathi.db (git-ignored). Set KHETSAATHI_DB to use another path.
Every function opens its own short connection, so the app is safe under concurrent requests.
"""

import json
import os
import sqlite3
import time
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

DB_PATH = Path(os.getenv("KHETSAATHI_DB", Path(__file__).resolve().parent / "data" / "khetsaathi.db"))

# After this many failures in a row, a source is paused for BREAKER_OPEN_SECONDS.
BREAKER_FAILURES = 2
BREAKER_OPEN_SECONDS = 600

SCHEMA = """
CREATE TABLE IF NOT EXISTS cache (
    key TEXT PRIMARY KEY,
    payload TEXT NOT NULL,
    stored_at REAL NOT NULL,
    expires_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS source_health (
    source TEXT PRIMARY KEY,
    last_ok_at TEXT,
    last_error TEXT,
    last_error_at TEXT,
    consecutive_failures INTEGER NOT NULL DEFAULT 0,
    open_until REAL NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS mandi_rows (
    state TEXT NOT NULL,
    district TEXT NOT NULL,
    market TEXT NOT NULL,
    commodity TEXT NOT NULL,
    variety TEXT,
    grade TEXT,
    arrival_date TEXT,
    min_price TEXT,
    max_price TEXT,
    modal_price TEXT,
    synced_at REAL NOT NULL,
    PRIMARY KEY (state, district, market, commodity, variety, grade)
);
CREATE INDEX IF NOT EXISTS mandi_by_commodity ON mandi_rows (commodity, state, district);
CREATE TABLE IF NOT EXISTS advice_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    place TEXT,
    crop TEXT,
    question TEXT,
    advice TEXT,
    warnings TEXT,
    tools_used TEXT,
    latency_ms INTEGER
);
"""


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


# ---- TTL cache ----

def cache_get(key: str) -> tuple[dict, float, bool] | None:
    """Return (payload, stored_at, is_fresh) for a key, or None if it was never stored."""
    with closing(_connect()) as conn:
        row = conn.execute(
            "SELECT payload, stored_at, expires_at FROM cache WHERE key = ?", (key,)
        ).fetchone()
    if row is None:
        return None
    return json.loads(row["payload"]), row["stored_at"], time.time() < row["expires_at"]


def cache_put(key: str, payload: dict, ttl_seconds: int) -> None:
    now = time.time()
    with closing(_connect()) as conn, conn:
        conn.execute(
            "INSERT OR REPLACE INTO cache (key, payload, stored_at, expires_at) VALUES (?, ?, ?, ?)",
            (key, json.dumps(payload, ensure_ascii=False), now, now + ttl_seconds),
        )


def cache_stats() -> dict:
    with closing(_connect()) as conn:
        total = conn.execute("SELECT COUNT(*) FROM cache").fetchone()[0]
        fresh = conn.execute(
            "SELECT COUNT(*) FROM cache WHERE expires_at > ?", (time.time(),)
        ).fetchone()[0]
    return {"entries": total, "fresh_entries": fresh}


# ---- Source health and circuit breaker ----

def breaker_open(source: str) -> bool:
    """True while a source is paused after repeated failures."""
    with closing(_connect()) as conn:
        row = conn.execute("SELECT open_until FROM source_health WHERE source = ?", (source,)).fetchone()
    return row is not None and time.time() < row["open_until"]


def record_success(source: str) -> None:
    with closing(_connect()) as conn, conn:
        conn.execute(
            """INSERT INTO source_health (source, last_ok_at, consecutive_failures, open_until)
               VALUES (?, ?, 0, 0)
               ON CONFLICT(source) DO UPDATE SET
                 last_ok_at = excluded.last_ok_at, consecutive_failures = 0, open_until = 0""",
            (source, _now_iso()),
        )


def record_failure(source: str, error: str) -> None:
    now = time.time()
    with closing(_connect()) as conn, conn:
        conn.execute(
            """INSERT INTO source_health (source, last_error, last_error_at, consecutive_failures, open_until)
               VALUES (?, ?, ?, 1, 0)
               ON CONFLICT(source) DO UPDATE SET
                 last_error = excluded.last_error,
                 last_error_at = excluded.last_error_at,
                 consecutive_failures = source_health.consecutive_failures + 1,
                 open_until = CASE
                   WHEN source_health.consecutive_failures + 1 >= ? THEN ? ELSE source_health.open_until END""",
            (source, error, _now_iso(), BREAKER_FAILURES, now + BREAKER_OPEN_SECONDS),
        )


def health_snapshot() -> list[dict]:
    now = time.time()
    with closing(_connect()) as conn:
        rows = conn.execute("SELECT * FROM source_health ORDER BY source").fetchall()
    return [
        {
            "source": row["source"],
            "last_ok_at": row["last_ok_at"],
            "last_error": row["last_error"],
            "last_error_at": row["last_error_at"],
            "consecutive_failures": row["consecutive_failures"],
            "paused": now < row["open_until"],
        }
        for row in rows
    ]


# ---- Advice log ----

def log_advice(place: str, crop: str, question: str, advice: str, warnings: list[str],
               tools_used: list[str], latency_ms: int) -> None:
    with closing(_connect()) as conn, conn:
        conn.execute(
            """INSERT INTO advice_log
               (created_at, place, crop, question, advice, warnings, tools_used, latency_ms)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (_now_iso(), place, crop, question, advice, json.dumps(warnings, ensure_ascii=False),
             json.dumps(tools_used), latency_ms),
        )


def advice_stats() -> dict:
    with closing(_connect()) as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS n, AVG(latency_ms) AS avg_ms FROM advice_log"
        ).fetchone()
    return {"answers_served": row["n"], "average_latency_ms": round(row["avg_ms"] or 0)}


# ---- Market rows synced from the government dataset ----

def save_mandi_rows(rows: list[dict]) -> int:
    """Store rows from a sync. Rows are replaced by key, so a re-sync updates prices in place."""
    now = time.time()
    with closing(_connect()) as conn, conn:
        conn.executemany(
            """INSERT OR REPLACE INTO mandi_rows
               (state, district, market, commodity, variety, grade, arrival_date,
                min_price, max_price, modal_price, synced_at)
               VALUES (:state, :district, :market, :commodity, :variety, :grade, :arrival_date,
                       :min_price, :max_price, :modal_price, :synced_at)""",
            [{**row, "synced_at": now} for row in rows],
        )
    return len(rows)


def mandi_rows_for(state: str, district: str, commodity: str) -> list[dict]:
    with closing(_connect()) as conn:
        rows = conn.execute(
            """SELECT * FROM mandi_rows WHERE lower(state) = lower(?) AND lower(district) = lower(?)
               AND lower(commodity) = lower(?) ORDER BY market, variety""",
            (state, district, commodity),
        ).fetchall()
    return [dict(row) for row in rows]


def mandi_rows_for_state_districts(state: str) -> list[str]:
    """Districts in a state that have market data locally, for helpful messages."""
    with closing(_connect()) as conn:
        rows = conn.execute(
            "SELECT DISTINCT district FROM mandi_rows WHERE lower(state) = lower(?) ORDER BY district",
            (state,),
        ).fetchall()
    return [row["district"] for row in rows]


def mandi_last_synced() -> float | None:
    with closing(_connect()) as conn:
        row = conn.execute("SELECT MAX(synced_at) AS last FROM mandi_rows").fetchone()
    return row["last"]


def mandi_commodities() -> list[str]:
    with closing(_connect()) as conn:
        rows = conn.execute("SELECT DISTINCT commodity FROM mandi_rows ORDER BY commodity").fetchall()
    return [row["commodity"] for row in rows]
