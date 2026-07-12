"""Cloud mirror + Firestore store scaffold tests."""

from __future__ import annotations

import pytest

from backend.app.config import Settings
from backend.app.models import JudgmentCreate
from backend.app.stores.cloud_mirror import (
    FirestoreCloudMirror,
    NullCloudMirror,
)
from backend.app.stores.factory import create_app_store, create_cloud_mirror
from backend.app.stores.firestore_store import (
    FirestoreStore,
    StoreNotConfiguredError,
)
from backend.app.stores.sqlite_store import SqliteStore


def _settings(tmp_path, **over) -> Settings:
    base = dict(
        app_db_path=tmp_path / "app.db",
        journal_dir=tmp_path / "journal",
        cors_origins=["http://127.0.0.1:3000"],
        log_level="WARNING",
        log_dir=tmp_path / "logs",
        market_db_path=tmp_path / "market.db",
        store_backend="sqlite",
        cloud_mirror="off",
        firebase_project_id=None,
        google_application_credentials=None,
    )
    base.update(over)
    return Settings(**base)


def test_null_mirror_status_and_push():
    m = NullCloudMirror()
    st = m.status()
    assert st.backend == "off"
    assert st.enabled is False
    assert m.push("judgment_entries", {"id": "x"}) is False


def test_firestore_mirror_stub_unconfigured():
    m = FirestoreCloudMirror(project_id=None, credentials_path=None)
    st = m.status()
    assert st.backend == "firestore"
    assert st.enabled is True
    assert st.configured is False
    assert m.push("judgment_entries", {"id": "x"}) is False


def test_firestore_mirror_stub_configured_still_noop():
    m = FirestoreCloudMirror(
        project_id="demo-project",
        credentials_path="/tmp/fake.json",
    )
    st = m.status()
    assert st.configured is True
    # SDK not wired → still False
    assert m.push("judgment_entries", {"id": "x"}) is False


def test_factory_default_sqlite(tmp_path):
    s = _settings(tmp_path)
    store = create_app_store(s)
    assert isinstance(store, SqliteStore)
    assert isinstance(store._cloud_mirror, NullCloudMirror)


def test_factory_mirror_firestore_env(tmp_path):
    s = _settings(tmp_path, cloud_mirror="firestore", firebase_project_id="p")
    m = create_cloud_mirror(s)
    assert isinstance(m, FirestoreCloudMirror)
    assert m.status().configured is False  # no credentials path


def test_sqlite_calls_mirror_after_create(tmp_path):
    pushes: list[tuple[str, str]] = []

    class RecordingMirror(NullCloudMirror):
        def push(self, table, row):
            pushes.append((table, row.get("id", "")))
            return True

        def status(self):
            return super().status()

    store = SqliteStore(
        tmp_path / "a.db", tmp_path / "j", cloud_mirror=RecordingMirror()
    )
    store.init_schema()
    store.create_judgment(
        JudgmentCreate(
            object="AMAT",
            jtype="fact",
            text="mirror hook smoke",
        )
    )
    assert pushes and pushes[0][0] == "judgment_entries"


def test_firestore_store_stub_raises():
    s = FirestoreStore(project_id="x", credentials_path="/tmp/x.json")
    s.init_schema()  # ok
    with pytest.raises(StoreNotConfiguredError):
        s.list_chains()


def test_cloud_status_api(client):
    r = client.get("/api/cloud/status")
    assert r.status_code == 200
    body = r.json()
    assert body["store_backend"] == "sqlite"
    assert body["cloud_mirror"]["backend"] == "off"
    assert "credentials_path_set" in body
    # no secret leakage
    blob = str(body)
    assert "sk-" not in blob
    assert ".json" not in blob or body["credentials_path_set"] is False
