"""Slice 10: reliability + observability tests.

Covers:
  - /api/health is async and returns {ok: True} unconditionally
  - /api/status endpoint shape
  - /api/diagnostics/export returns a zip containing status.json
  - refresh_status includes run_id after start_refresh_background
  - per-request SqliteStore.for_request() opens independent connection
"""

from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path

import pytest
from backend.tests.http_client import make_test_client

from backend.app.main import app
from backend.app.services import feed_ingest
from backend.app.stores.sqlite_store import SqliteStore


# ── fixtures ───────────────────────────────────────────────────────────────


@pytest.fixture
def store(tmp_path: Path):
    s = SqliteStore(tmp_path / "app.db", tmp_path / "journal")
    s.init_schema()
    yield s
    s.close()


@pytest.fixture
def client(store: SqliteStore):
    with make_test_client() as c:
        app.state.store = store
        yield c


# ── A1: /api/health ─────────────────────────────────────────────────────────


def test_health_returns_ok(client: TestClient):
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json() == {"ok": True}


def test_health_is_async():
    """Verify /api/health route function is a coroutine (async def)."""
    import asyncio
    import inspect

    from backend.app.main import health

    assert inspect.iscoroutinefunction(health), "/api/health must be async def"


# ── B3: /api/status ─────────────────────────────────────────────────────────


def test_status_endpoint_shape(client: TestClient):
    r = client.get("/api/status")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert "db_ok" in body
    assert "journal_mode" in body
    assert "wal" in body
    assert "refresh" in body
    assert "llm_configured" in body
    assert "search_model_configured" in body
    assert "version" in body


def test_status_db_ok_true(client: TestClient):
    r = client.get("/api/status")
    assert r.json()["db_ok"] is True


def test_status_wal_enabled(client: TestClient):
    r = client.get("/api/status")
    body = r.json()
    assert body["journal_mode"] == "wal"
    assert body["wal"] is True


# ── B5: /api/diagnostics/export ─────────────────────────────────────────────


def test_diagnostics_export_returns_zip(client: TestClient):
    r = client.get("/api/diagnostics/export")
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/zip"
    cd = r.headers.get("content-disposition", "")
    assert ".zip" in cd


def test_diagnostics_export_contains_status_json(client: TestClient):
    r = client.get("/api/diagnostics/export")
    buf = io.BytesIO(r.content)
    with zipfile.ZipFile(buf) as zf:
        names = zf.namelist()
        assert "status.json" in names, f"status.json missing from zip: {names}"
        status_data = json.loads(zf.read("status.json"))
        assert status_data["ok"] is True
        assert "refresh" in status_data
        assert "exported_at" in status_data


def test_diagnostics_export_no_env_file(client: TestClient, tmp_path: Path):
    """Zip must never contain a .env file."""
    r = client.get("/api/diagnostics/export")
    buf = io.BytesIO(r.content)
    with zipfile.ZipFile(buf) as zf:
        for name in zf.namelist():
            assert ".env" not in name, f"Found suspicious file in export: {name}"


# ── B1+B2: run_id in refresh_status ─────────────────────────────────────────


def test_refresh_status_has_run_id_after_start(tmp_path: Path, monkeypatch):
    """start_refresh_background must set run_id in state."""
    # Reset state
    feed_ingest._set_state(
        running=False,
        phase=None,
        error=None,
        result=None,
        message=None,
        run_id=None,
    )

    # Patch _run_refresh so worker exits immediately without DB
    def fake_run(store, batch_date, *, skip_fetch):
        return {"batch_date": batch_date, "cards": 0}

    monkeypatch.setattr(feed_ingest, "_run_refresh", fake_run)

    db_path = tmp_path / "app.db"
    journal_dir = tmp_path / "journal"
    # Create schema so worker won't fail
    s = SqliteStore(db_path, journal_dir)
    s.init_schema()
    s.close()

    out = feed_ingest.start_refresh_background(
        db_path=db_path,
        journal_dir=journal_dir,
        batch_date="2026-07-12",
        skip_fetch=True,
    )

    assert out.get("accepted") is True
    assert out.get("run_id") is not None
    assert len(out["run_id"]) > 0

    status = feed_ingest.refresh_status()
    assert status.get("run_id") is not None
    # last_progress_at alias
    assert "last_progress_at" in status
    assert status["last_progress_at"] == status.get("heartbeat_at")


# ── A2: SqliteStore.for_request() ───────────────────────────────────────────


def test_for_request_opens_independent_connection(tmp_path: Path):
    """for_request() must open a new connection, not reuse the lifespan conn."""
    db_path = tmp_path / "app.db"
    journal_dir = tmp_path / "journal"
    primary = SqliteStore(db_path, journal_dir)
    primary.init_schema()

    secondary = SqliteStore.for_request(db_path, journal_dir)
    try:
        assert secondary._conn is not primary._conn, "Connections must be distinct"
        # Both should be able to read schema
        row = secondary._conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='feed_cards'"
        ).fetchone()
        assert row is not None, "feed_cards table not visible from secondary connection"
    finally:
        secondary.close()
        primary.close()


def test_for_request_wal_pragma(tmp_path: Path):
    db_path = tmp_path / "app.db"
    journal_dir = tmp_path / "journal"
    primary = SqliteStore(db_path, journal_dir)
    primary.init_schema()
    primary.close()

    secondary = SqliteStore.for_request(db_path, journal_dir)
    try:
        row = secondary._conn.execute("PRAGMA journal_mode").fetchone()
        assert row[0] == "wal"
    finally:
        secondary.close()


# ── B4: exception handlers include request_id ───────────────────────────────


def test_validation_error_includes_request_id(client: TestClient):
    """422 validation errors should carry a request_id field."""
    # POST a malformed body to a typed endpoint
    r = client.post("/api/watchlist", json={"bad_field": "x"})
    assert r.status_code == 422
    body = r.json()
    assert "request_id" in body.get("error", {}), (
        f"request_id missing from 422 body: {body}"
    )
