"""Shared pytest fixtures — isolated temp DB + journal per test."""

from __future__ import annotations

import os
import tempfile

# D2: keep logging out of the repo working tree during the full suite
os.environ.setdefault(
    "ALETHEIA_LOG_DIR",
    tempfile.mkdtemp(prefix="aletheia-test-logs-"),
)

import pytest

from backend.app.main import app
from backend.app.stores.sqlite_store import SqliteStore
from backend.tests.http_client import make_test_client


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
    with make_test_client() as c:
        app.state.store = store
        yield c
