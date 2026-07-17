"""Slice 4d — executions fact layer (void / positions / JSONL / 405)."""

from __future__ import annotations

import sqlite3

import pytest
from backend.tests.http_client import make_test_client

from backend.app.main import app
from backend.app.models import ExecutionCreate
from backend.app.stores import jsonl_mirror
from backend.app.stores.sqlite_store import SqliteStore


@pytest.fixture
def store(tmp_path):
    s = SqliteStore(tmp_path / "app.db", tmp_path / "journal")
    s.init_schema()
    yield s
    s.close()


@pytest.fixture
def client(store, monkeypatch):
    monkeypatch.setattr("backend.app.main.create_store", lambda: store)
    with make_test_client() as c:
        app.state.store = store
        yield c


FILL = {
    "ticker": "AMAT",
    "side": "buy",
    "trade_date": "2026-07-11",
    "shares": 10,
    "price": 200.0,
    "fees": 1.5,
    "plan_id": "plan_demo",
    "note": "ladder fill",
}


def test_create_and_list_excludes_voided(client, store):
    r = client.post("/api/executions", json=FILL)
    assert r.status_code == 201, r.text
    eid = r.json()["id"]
    assert r.json()["voided_by"] is None

    listed = client.get("/api/executions?ticker=AMAT").json()
    assert len(listed) == 1
    assert listed[0]["id"] == eid

    voided = client.post(f"/api/executions/{eid}/void", json={})
    assert voided.status_code == 200
    assert voided.json()["voided"]["voided_by"] == eid

    assert client.get("/api/executions?ticker=AMAT").json() == []
    all_rows = client.get("/api/executions?ticker=AMAT&include_voided=true").json()
    assert len(all_rows) == 1
    assert all_rows[0]["voided_by"] == eid


def test_void_with_replacement_atomic(client):
    created = client.post("/api/executions", json=FILL).json()
    eid = created["id"]
    body = {
        "replacement": {
            **FILL,
            "shares": 12,
            "price": 198.5,
            "note": "corrected fill",
        }
    }
    out = client.post(f"/api/executions/{eid}/void", json=body).json()
    assert out["voided"]["voided_by"] == out["replacement"]["id"]
    assert out["replacement"]["shares"] == 12

    active = client.get("/api/executions?ticker=AMAT").json()
    assert len(active) == 1
    assert active[0]["id"] == out["replacement"]["id"]
    assert active[0]["shares"] == 12


def test_void_twice_409(client):
    eid = client.post("/api/executions", json=FILL).json()["id"]
    assert client.post(f"/api/executions/{eid}/void", json={}).status_code == 200
    again = client.post(f"/api/executions/{eid}/void", json={})
    assert again.status_code == 409


def test_put_patch_delete_405(client):
    eid = client.post("/api/executions", json=FILL).json()["id"]
    assert client.put(f"/api/executions/{eid}", json=FILL).status_code == 405
    assert client.patch(f"/api/executions/{eid}", json=FILL).status_code == 405
    assert client.delete(f"/api/executions/{eid}").status_code == 405
    assert (
        client.delete(f"/api/executions/{eid}").json()["error"]["code"]
        == "APPEND_ONLY_VIOLATION"
    )


def test_trigger_blocks_mutate_and_delete(store):
    rec = store.create_execution(ExecutionCreate(**FILL))
    with pytest.raises(sqlite3.IntegrityError):
        store._conn.execute(
            "UPDATE executions SET price = 1 WHERE id = ?", (rec.id,)
        )
        store._conn.commit()
    store._conn.rollback()
    with pytest.raises(sqlite3.IntegrityError):
        store._conn.execute("DELETE FROM executions WHERE id = ?", (rec.id,))
        store._conn.commit()
    store._conn.rollback()


def test_positions_weighted_avg_and_judgment_count(client):
    j = client.post(
        "/api/judgments",
        json={
            "object": "AMAT",
            "jtype": "action",
            "direction": "outperform",
            "horizon_days": 20,
            "confidence": 0.5,
            "text": "窗口内不弱",
            "origin": "console",
        },
    ).json()
    root = j["root_id"]

    client.post(
        "/api/executions",
        json={
            **FILL,
            "shares": 10,
            "price": 100,
            "judgment_root_id": root,
            "fees": 0,
        },
    )
    client.post(
        "/api/executions",
        json={
            **FILL,
            "shares": 10,
            "price": 200,
            "judgment_root_id": root,
            "fees": 0,
        },
    )
    client.post(
        "/api/executions",
        json={
            "ticker": "AMAT",
            "side": "sell",
            "trade_date": "2026-07-12",
            "shares": 5,
            "price": 210,
            "fees": 0,
        },
    )

    positions = client.get("/api/positions").json()
    amat = next(p for p in positions if p["ticker"] == "AMAT")
    assert amat["shares"] == 15
    # buy-weighted avg: (10*100 + 10*200) / 20 = 150
    assert abs(amat["avg_price"] - 150.0) < 1e-6
    assert amat["judgment_linked_count"] == 1


def test_jsonl_mirrors_create_and_void(store):
    before = jsonl_mirror.count_rows(store.journal_dir, "executions")
    rec = store.create_execution(ExecutionCreate(**FILL))
    mid = jsonl_mirror.count_rows(store.journal_dir, "executions")
    assert mid == before + 1
    store.void_execution(rec.id)
    after = jsonl_mirror.count_rows(store.journal_dir, "executions")
    assert after == mid + 1  # void state mirrored
    rows = [
        r
        for r in jsonl_mirror.iter_rows(store.journal_dir)
        if r.get("_table") == "executions" and r.get("id") == rec.id
    ]
    assert any(r.get("voided_by") == rec.id for r in rows)


def test_validation_rejects_nonpositive(client):
    bad = {**FILL, "shares": 0}
    assert client.post("/api/executions", json=bad).status_code == 422
