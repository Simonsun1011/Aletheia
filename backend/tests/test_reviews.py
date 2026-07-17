"""API tests for /reviews (due / settle / calibration)."""

from __future__ import annotations

import sqlite3
from datetime import date, datetime, timedelta, timezone

import pytest

from backend.app.market.db import connect_market_db
from backend.app.services.settle import STAT_WARNING


def _seed_prices(conn: sqlite3.Connection, ticker: str, start: date, closes: list[float]):
    d = start
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


VALID = {
    "object": "AMAT",
    "jtype": "action",
    "direction": "outperform",
    "horizon_days": 40,
    "confidence": 0.7,
    "text": "相对SOXX不弱",
}


def _backdate_expires(store, root_id: str, expires_on: str, created_at: str):
    """Test helper: rewrite created_at/expires_on via raw SQL (triggers block UPDATE).

    Triggers forbid UPDATE — drop triggers in test DB only, patch, restore.
    """
    store._conn.execute("DROP TRIGGER IF EXISTS judgment_entries_no_update")
    store._conn.execute("DROP TRIGGER IF EXISTS judgment_entries_no_delete")
    store._conn.execute(
        "UPDATE judgment_entries SET created_at=?, expires_on=? WHERE id=?",
        (created_at, expires_on, root_id),
    )
    store._conn.commit()
    # re-apply triggers from schema
    from backend.app.stores.sqlite_store import TRIGGER_SQL

    store._conn.executescript(TRIGGER_SQL)
    store._conn.commit()


@pytest.fixture
def market_db(tmp_path, monkeypatch):
    db = tmp_path / "market.db"
    conn = connect_market_db(db)
    n = 41
    _seed_prices(conn, "AMAT", date(2024, 1, 2), [100.0] * (n - 1) + [110.0])
    _seed_prices(conn, "QQQ", date(2024, 1, 2), [200.0] * (n - 1) + [210.0])
    _seed_prices(conn, "SOXX", date(2024, 1, 2), [50.0] * (n - 1) + [51.0])
    conn.close()
    monkeypatch.setenv("ALETHEIA_MARKET_DB", str(db))
    # clear settings cache if any — get_settings reads env each call
    return db


def test_due_lists_expired_open_not_closed(client, store, market_db):
    open_j = client.post("/api/judgments", json=VALID).json()
    closed_j = client.post(
        "/api/judgments",
        json={**VALID, "text": "另一条"},
    ).json()
    past = (datetime.now(timezone.utc).date() - timedelta(days=5)).isoformat()
    created = "2024-01-02T15:00:00Z"
    _backdate_expires(store, open_j["root_id"], past, created)
    _backdate_expires(store, closed_j["root_id"], past, created)

    client.post(
        f"/api/judgments/{closed_j['root_id']}/entries",
        json={"kind": "review", "text": "已复盘：数字已见"},
    )

    due = client.get("/api/reviews/due").json()
    ids = {c["root_id"] for c in due}
    assert open_j["root_id"] in ids
    assert closed_j["root_id"] not in ids
    assert all(c["status"] == "open" for c in due)


def test_settle_numbers_no_evaluative_fields(client, store, market_db):
    created = client.post("/api/judgments", json=VALID).json()
    _backdate_expires(
        store,
        created["root_id"],
        "2024-03-01",
        "2024-01-02T15:00:00Z",
    )
    r = client.post(f"/api/reviews/{created['root_id']}/settle")
    assert r.status_code == 200
    body = r.json()
    assert body["object_return"] == pytest.approx(0.10)
    assert body["qqq_return"] == pytest.approx(0.05)
    assert body["excess_vs_qqq"] == pytest.approx(0.05)
    assert body["sector_etf"] == "SOXX"
    assert body["review_text"] is None
    blob = str(body)
    for bad in ("正确", "错误", "好", "差", "建议"):
        assert bad not in blob
    # field names must not be evaluative
    for key in body.keys():
        assert key not in ("correct", "wrong", "good", "bad", "hit")


def test_calibration_n_lt_20_warning_and_n0(client, store, market_db):
    empty = client.get("/api/reviews/calibration").json()
    assert empty["n"] == 0
    assert empty["hit_rate"] is None
    assert empty["warning"] == STAT_WARNING

    created = client.post("/api/judgments", json=VALID).json()
    _backdate_expires(
        store, created["root_id"], "2024-03-01", "2024-01-02T15:00:00Z"
    )
    client.post(
        f"/api/judgments/{created['root_id']}/entries",
        json={"kind": "review", "text": "复盘结论文字由人写"},
    )
    cal = client.get("/api/reviews/calibration?jtype=action").json()
    assert cal["n"] == 1
    assert cal["hits"] == 1  # excess_vs_qqq > 0 → outperform hit
    assert cal["hit_rate"] == pytest.approx(1.0)
    assert cal["warning"] == STAT_WARNING


def test_snapshot_upsert_and_auto_bind(client, store, tmp_path):
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    store.upsert_snapshot(
        today,
        "ticker:AMAT",
        {"schema_version": 1, "ticker": "AMAT", "as_of": today},
    )
    assert store.get_snapshot(today, "ticker:AMAT")["ticker"] == "AMAT"
    created = client.post("/api/judgments", json=VALID).json()
    assert created["snapshot_date"] == today
