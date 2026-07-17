"""Feed refresh background + status polling."""

from __future__ import annotations

import time
from pathlib import Path

import pytest
from backend.tests.http_client import make_test_client

from backend.app.main import app
from backend.app.services import feed_ingest
from backend.app.stores.sqlite_store import SqliteStore


@pytest.fixture
def store(tmp_path):
    s = SqliteStore(tmp_path / "app.db", tmp_path / "journal")
    s.init_schema()
    yield s
    s.close()


@pytest.fixture
def client(store, monkeypatch, tmp_path):
    monkeypatch.setattr("backend.app.main.create_store", lambda: store)

    # Background job must use same tmp db
    def kick(**kwargs):
        return feed_ingest.start_refresh_background(
            db_path=tmp_path / "app.db",
            journal_dir=tmp_path / "journal",
            batch_date=kwargs.get("batch_date"),
            skip_fetch=kwargs.get("skip_fetch", False),
        )

    monkeypatch.setattr(
        "backend.app.routers.feed.start_refresh_background",
        lambda **kw: kick(
            batch_date=kw.get("batch_date"),
            skip_fetch=kw.get("skip_fetch", False),
        ),
    )

    with make_test_client() as c:
        app.state.store = store
        yield c


def test_refresh_status_idle(client):
    # reset module state
    feed_ingest._set_state(
        running=False,
        phase=None,
        error=None,
        result=None,
        message=None,
    )
    r = client.get("/api/feed/refresh/status")
    assert r.status_code == 200
    assert r.json()["running"] is False


def test_refresh_background_completes(client, monkeypatch, tmp_path):
    feed_ingest._set_state(
        running=False,
        phase=None,
        error=None,
        result=None,
        message=None,
    )

    def fake_run(store, batch_date, *, skip_fetch):
        feed_ingest._set_state(
            running=True,
            phase="digest",
            message="mock digest",
            batch_date=batch_date or "2026-07-12",
        )
        time.sleep(0.15)
        result = {
            "batch_date": batch_date or "2026-07-12",
            "fetch": {"raw": 1},
            "digest": {"ok": 1, "filtered": 0},
            "cards": 1,
        }
        feed_ingest._set_state(
            running=False,
            phase="done",
            result=result,
            message="done",
            error=None,
        )
        return result

    monkeypatch.setattr(feed_ingest, "_run_refresh", fake_run)

    r = client.post("/api/feed/refresh")
    assert r.status_code == 200
    body = r.json()
    assert body.get("accepted") is True or body.get("running") is True

    # poll until done (no hard ceiling in product; test uses short bound)
    deadline = time.time() + 3
    last = None
    while time.time() < deadline:
        last = client.get("/api/feed/refresh/status").json()
        if not last["running"] and last.get("phase") == "done":
            break
        time.sleep(0.05)
    assert last is not None
    assert last["running"] is False
    assert last["phase"] == "done"
    assert last["result"]["cards"] == 1
