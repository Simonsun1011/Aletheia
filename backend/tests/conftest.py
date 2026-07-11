"""Shared pytest fixtures — isolated temp DB + journal per test."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from backend.app.main import app
from backend.app.stores.sqlite_store import SqliteStore


@pytest.fixture
def store(tmp_path):
    db = tmp_path / "app.db"
    journal = tmp_path / "journal"
    s = SqliteStore(db, journal)
    s.init_schema()
    yield s
    s.close()


@pytest.fixture
def client(store, monkeypatch):
    monkeypatch.setattr("backend.app.main.create_store", lambda: store)
    with TestClient(app) as c:
        app.state.store = store
        yield c
