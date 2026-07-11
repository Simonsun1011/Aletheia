"""Snapshot API + fetch idempotency tests (slice-02)."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from backend.app.main import app
from backend.app.market.db import connect_market_db
from backend.app.market.indicators import compute_indicator_frame, period_return
from backend.app.market.sector_map import load_sector_etf
from jobs.fetch_prices import count_prices, upsert_prices
from jobs.compute_indicators import compute_for_ticker


def _write_synth(conn, ticker: str, n: int = 260, seed: int = 1, start: str = "2024-01-02"):
    rng = __import__("numpy").random.default_rng(seed)
    rets = rng.normal(0.0004, 0.012, size=n)
    close = 50 * __import__("numpy").cumprod(1 + rets)
    high = close * 1.01
    low = close * 0.99
    open_ = close
    volume = rng.integers(100000, 500000, size=n)
    idx = pd.bdate_range(start, periods=n)
    df = pd.DataFrame(
        {"open": open_, "high": high, "low": low, "close": close, "volume": volume},
        index=idx,
    )
    upsert_prices(conn, ticker, df)
    return df


@pytest.fixture
def market_db(tmp_path, monkeypatch):
    db = tmp_path / "market_data.db"
    monkeypatch.setenv("ALETHEIA_MARKET_DB", str(db))
    # reload settings used by router
    from backend.app import config

    monkeypatch.setattr(
        config,
        "get_settings",
        lambda: config.Settings(
            app_db_path=tmp_path / "app.db",
            journal_dir=tmp_path / "journal",
            cors_origins=["http://localhost:3000"],
            log_level="WARNING",
            log_dir=tmp_path / "logs",
            market_db_path=db,
        ),
    )
    # tickers router calls get_settings from config module
    import backend.app.routers.tickers as tickers_mod

    monkeypatch.setattr(tickers_mod, "get_settings", config.get_settings)
    return db


@pytest.fixture
def client(store, market_db, monkeypatch):
    monkeypatch.setattr("backend.app.main.create_store", lambda: store)
    with TestClient(app) as c:
        app.state.store = store
        yield c


def test_fetch_upsert_idempotent(tmp_path):
    db = tmp_path / "m.db"
    conn = connect_market_db(db)
    df = _write_synth(conn, "AMAT", n=30)
    n1 = count_prices(conn, "AMAT")
    upsert_prices(conn, "AMAT", df)  # second run same data
    n2 = count_prices(conn, "AMAT")
    assert n1 == n2 == 30
    conn.close()


def test_snapshot_full_schema(client, market_db):
    conn = connect_market_db(market_db)
    _write_synth(conn, "AMAT", n=260, seed=2)
    _write_synth(conn, "QQQ", n=260, seed=3)
    _write_synth(conn, "SOXX", n=260, seed=4)
    compute_for_ticker(conn, "AMAT")
    conn.close()

    r = client.get("/api/tickers/AMAT/snapshot")
    assert r.status_code == 200
    body = r.json()
    assert body["symbol"] == "AMAT"
    assert body["as_of"]
    assert body["price"]["last"] is not None
    assert body["anchors"]["sma50"] is not None
    assert body["anchors"]["sma200"] is not None
    assert body["risk"]["atr14"] is not None
    assert body["relative"]["sector_etf"] == "SOXX"
    assert body["relative"]["vs_qqq_20d"] is not None
    assert body["relative"]["vs_sector_20d"] is not None


def test_snapshot_sma200_null_with_warning(client, market_db):
    conn = connect_market_db(market_db)
    # Only 80 bars — SMA50 ok-ish, SMA200 must be null
    _write_synth(conn, "AMAT", n=80, seed=5)
    _write_synth(conn, "QQQ", n=80, seed=6)
    compute_for_ticker(conn, "AMAT")
    conn.close()

    r = client.get("/api/tickers/AMAT/snapshot")
    assert r.status_code == 200
    body = r.json()
    assert body["anchors"]["sma200"] is None
    assert any("sma200" in w for w in body["warnings"])


def test_snapshot_unknown_ticker_404(client, market_db):
    r = client.get("/api/tickers/NOSUCH/snapshot")
    assert r.status_code == 404


def test_msft_sector_etf_null(client, market_db):
    assert load_sector_etf("MSFT") is None
    assert load_sector_etf("AMAT") == "SOXX"

    conn = connect_market_db(market_db)
    _write_synth(conn, "MSFT", n=260, seed=7)
    _write_synth(conn, "QQQ", n=260, seed=8)
    compute_for_ticker(conn, "MSFT")
    conn.close()

    r = client.get("/api/tickers/MSFT/snapshot")
    assert r.status_code == 200
    body = r.json()
    assert body["relative"]["sector_etf"] is None
    assert body["relative"]["vs_sector_20d"] is None
    assert body["relative"]["vs_sector_60d"] is None
    assert body["relative"]["vs_qqq_20d"] is not None
