"""On-demand ensure_local_market_data behavior."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from backend.app.market.db import connect_market_db
from backend.app.market.ensure import ensure_local_market_data


def test_ensure_skips_network_when_bars_sufficient(tmp_path, monkeypatch):
    db = tmp_path / "m.db"
    conn = connect_market_db(db)
    idx = pd.bdate_range("2024-01-02", periods=80)
    for i, dt in enumerate(idx):
        conn.execute(
            "INSERT INTO prices VALUES (?,?,?,?,?,?,?)",
            ("ZZZZ", dt.strftime("%Y-%m-%d"), 10, 11, 9, 10 + i * 0.01, 1000),
        )
    conn.commit()
    conn.close()

    called = {"fetch": 0}

    def boom(*a, **k):
        called["fetch"] += 1
        raise AssertionError("should not fetch")

    monkeypatch.setattr("jobs.fetch_prices.fetch_ohlcv", boom)
    warnings = ensure_local_market_data(db, "ZZZZ")
    assert called["fetch"] == 0
    # may still compute indicators
    assert isinstance(warnings, list)


def test_ensure_fetches_when_empty(tmp_path, monkeypatch):
    db = tmp_path / "m.db"
    connect_market_db(db).close()

    idx = pd.bdate_range("2024-01-02", periods=100)
    df = pd.DataFrame(
        {
            "open": 10.0,
            "high": 11.0,
            "low": 9.0,
            "close": 10.0,
            "volume": 1000,
        },
        index=idx,
    )

    def fake_fetch(ticker, days=400):
        return df

    monkeypatch.setattr("jobs.fetch_prices.fetch_ohlcv", fake_fetch)
    # MSFT has no sector ETF → only MSFT (+QQQ companion)
    warnings = ensure_local_market_data(db, "MSFT")
    assert any("fetched market data for MSFT" in w for w in warnings)
    conn = connect_market_db(db)
    n = conn.execute(
        "SELECT COUNT(*) c FROM prices WHERE ticker='MSFT'"
    ).fetchone()["c"]
    conn.close()
    assert n == 100
