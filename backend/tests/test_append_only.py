"""Append-only discipline tests (slice-01) — highest priority."""

from __future__ import annotations

import sqlite3

import pytest

from backend.app.models import JudgmentCreate

VALID = {
    "object": "AMAT",
    "jtype": "action",
    "direction": "outperform",
    "horizon_days": 40,
    "confidence": 0.6,
    "text": "原话",
}


def test_put_patch_delete_judgments_405(client):
    created = client.post("/api/judgments", json=VALID).json()
    rid = created["root_id"]

    for method, kwargs in (
        ("put", {"json": {"text": "x"}}),
        ("patch", {"json": {"text": "x"}}),
        ("delete", {}),
    ):
        r = getattr(client, method)(f"/api/judgments/{rid}", **kwargs)
        assert r.status_code == 405, method
        assert r.json()["error"]["code"] == "APPEND_ONLY_VIOLATION"


def test_put_patch_delete_notes_405(client):
    note = client.post("/api/notes", json={"text": "随感一句"}).json()
    nid = note["id"]
    for method, kwargs in (
        ("put", {"json": {"text": "x"}}),
        ("patch", {"json": {"text": "x"}}),
        ("delete", {}),
    ):
        r = getattr(client, method)(f"/api/notes/{nid}", **kwargs)
        assert r.status_code == 405, method
        assert r.json()["error"]["code"] == "APPEND_ONLY_VIOLATION"


def test_sqlite_update_trigger_aborts(store):
    entry = store.create_judgment(JudgmentCreate(**VALID))
    with pytest.raises(sqlite3.IntegrityError):
        store._conn.execute(
            "UPDATE judgment_entries SET text = ? WHERE id = ?",
            ("被篡改", entry.id),
        )
        store._conn.commit()


def test_sqlite_delete_trigger_aborts(store):
    entry = store.create_judgment(JudgmentCreate(**VALID))
    with pytest.raises(sqlite3.IntegrityError):
        store._conn.execute(
            "DELETE FROM judgment_entries WHERE id = ?", (entry.id,)
        )
        store._conn.commit()
