"""SQLite store for pipeline state, so every step can resume where it stopped."""

import sqlite3
from datetime import datetime, timezone

from scanner import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS leis (
    isin        TEXT PRIMARY KEY,
    lei         TEXT,            -- NULL = looked up, none found
    looked_up   TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS reports (
    ticker      TEXT PRIMARY KEY,
    name        TEXT,
    isin        TEXT,
    lei         TEXT,
    status      TEXT NOT NULL,   -- downloaded | failed
    reason      TEXT,            -- why it failed (or note)
    period_end  TEXT,            -- financial year end of the report used
    source      TEXT,            -- e.g. filings.xbrl.org
    filing_id   TEXT,            -- source's own id (fxo_id)
    package_url TEXT,
    path        TEXT,            -- local file
    bytes       INTEGER,
    updated     TEXT NOT NULL
);
"""


def connect() -> sqlite3.Connection:
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(config.DATA_DIR / "scanner.db")
    con.row_factory = sqlite3.Row
    con.executescript(SCHEMA)
    return con


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
