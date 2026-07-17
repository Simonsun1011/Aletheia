"""market_data.db schema helpers."""

from __future__ import annotations

import sqlite3
from pathlib import Path

MARKET_SCHEMA = """
CREATE TABLE IF NOT EXISTS prices (
    ticker TEXT NOT NULL,
    date TEXT NOT NULL,
    open REAL,
    high REAL,
    low REAL,
    close REAL,
    volume INTEGER,
    PRIMARY KEY (ticker, date)
);

CREATE TABLE IF NOT EXISTS indicators (
    ticker TEXT NOT NULL,
    date TEXT NOT NULL,
    name TEXT NOT NULL,
    value REAL,
    PRIMARY KEY (ticker, date, name)
);
"""


def connect_market_db(path: Path) -> sqlite3.Connection:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=15000")
    conn.executescript(MARKET_SCHEMA)
    conn.commit()
    return conn
