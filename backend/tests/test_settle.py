"""Synthetic price settle tests — data-model.md §4."""

from __future__ import annotations

import sqlite3
from datetime import date
from pathlib import Path

import pytest

from backend.app.market.db import connect_market_db
from backend.app.models import JudgmentChain, JudgmentEntry
from backend.app.services.settle import settle_chain, window_return, load_closes


def _seed_prices(conn: sqlite3.Connection, ticker: str, start: date, closes: list[float]):
    d = start
    from datetime import timedelta

    for c in closes:
        while d.weekday() >= 5:
            d += timedelta(days=1)
        conn.execute(
            "INSERT INTO prices (ticker, date, open, high, low, close, volume) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (ticker, d.isoformat(), c, c, c, c, 1_000_000),
        )
        d += timedelta(days=1)
        while d.weekday() >= 5:
            d += timedelta(days=1)
    conn.commit()


def _chain(
    *,
    object: str = "AMAT",
    created_at: str = "2024-01-02T15:00:00Z",
    horizon_days: int = 40,
    direction: str = "outperform",
) -> JudgmentChain:
    e = JudgmentEntry(
        id="01TESTROOT0000000000000000",
        root_id="01TESTROOT0000000000000000",
        kind="original",
        created_at=created_at,
        object=object,
        jtype="action",
        direction=direction,  # type: ignore[arg-type]
        horizon_days=horizon_days,
        confidence=0.6,
        text="synthetic",
        expires_on="2024-03-01",
        status="open",
    )
    return JudgmentChain(root_id=e.root_id, object=object, status="open", entries=[e])


def test_window_return_40_trading_days(tmp_path: Path):
    db = tmp_path / "m.db"
    conn = connect_market_db(db)
    # 50 trading days of flat then step
    closes = [100.0] + [100.0] * 39 + [110.0] + [110.0] * 10
    _seed_prices(conn, "AMAT", date(2024, 1, 2), closes)
    df = load_closes(conn, "AMAT")
    conn.close()
    wr = window_return(df, start_on=date(2024, 1, 2), horizon_days=40)
    assert wr is not None
    assert wr.trading_days == 40
    assert wr.ret == pytest.approx(0.10)


def test_settle_dual_excess_with_sector(tmp_path: Path, monkeypatch):
    db = tmp_path / "m.db"
    conn = connect_market_db(db)
    # object +10%, QQQ +5%, SOXX +2% over 40 sessions
    n = 41
    _seed_prices(conn, "AMAT", date(2024, 1, 2), [100.0] * (n - 1) + [110.0])
    _seed_prices(conn, "QQQ", date(2024, 1, 2), [200.0] * (n - 1) + [210.0])
    _seed_prices(conn, "SOXX", date(2024, 1, 2), [50.0] * (n - 1) + [51.0])
    conn.close()

    # Force sector map for AMAT→SOXX (real config already maps; assert anyway)
    result = settle_chain(_chain(horizon_days=40), db)
    assert result["object_return"] == pytest.approx(0.10)
    assert result["qqq_return"] == pytest.approx(0.05)
    assert result["sector_etf"] == "SOXX"
    assert result["sector_return"] == pytest.approx(0.02)
    assert result["excess_vs_qqq"] == pytest.approx(0.05)
    assert result["excess_vs_sector"] == pytest.approx(0.08)
    # no evaluative keys
    blob = str(result.keys())
    for bad in ("正确", "错误", "好", "差", "hit", "correct", "wrong"):
        assert bad not in blob


def test_settle_no_sector_mapping_null(tmp_path: Path, monkeypatch):
    db = tmp_path / "m.db"
    conn = connect_market_db(db)
    n = 41
    _seed_prices(conn, "MSFT", date(2024, 1, 2), [100.0] * (n - 1) + [120.0])
    _seed_prices(conn, "QQQ", date(2024, 1, 2), [200.0] * (n - 1) + [210.0])
    conn.close()

    result = settle_chain(_chain(object="MSFT", horizon_days=40), db)
    assert result["sector_etf"] is None
    assert result["sector_return"] is None
    assert result["excess_vs_sector"] is None
    assert result["object_return"] == pytest.approx(0.20)
    assert result["excess_vs_qqq"] == pytest.approx(0.15)
