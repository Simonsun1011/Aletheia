"""Changefeed list/extract fallback tests (AI mocked)."""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from backend.app.ai.adapter import CompletionResult
from backend.app.main import app
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
    with TestClient(app) as c:
        app.state.store = store
        yield c


def _mock(text: str):
    return lambda **kw: CompletionResult(
        text=text, model="mock", prompt_version="extract_event_v1.md", elapsed_ms=1
    )


def test_extract_draft_not_listed_until_confirm(client, monkeypatch):
    payload = {
        "object": "AMAT",
        "fact_text": "Company raised annual capex guidance.",
        "category": "company",
        "confirmation": "confirmed",
    }
    monkeypatch.setattr(
        "backend.app.services.changefeed.ai_adapter.complete",
        _mock(json.dumps(payload)),
    )
    draft = client.post(
        "/api/changefeed/extract", json={"raw_text": "capex up"}
    ).json()
    assert draft["user_confirmed"] == 0
    assert client.get("/api/changefeed").json() == []
    # v1.7: confirm without scope → 422
    no_scope = client.post(f"/api/changefeed/{draft['id']}/confirm", json={})
    assert no_scope.status_code == 422
    # confirm with mandatory scope + optional user_comment
    ok = client.post(
        f"/api/changefeed/{draft['id']}/confirm",
        json={"scope": "company", "user_comment": "关注下季度指引"},
    )
    assert ok.status_code == 200
    assert ok.json()["scope"] == "company"
    assert ok.json()["user_comment"] == "关注下季度指引"
    listed = client.get("/api/changefeed").json()
    assert any(e["id"] == draft["id"] for e in listed)


def test_adapter_no_hardcoded_secrets():
    from pathlib import Path

    src = Path("backend/app/ai/adapter.py").read_text(encoding="utf-8")
    assert "sk-" not in src
    assert "gpt-4" not in src.lower()
    assert "MODEL_SUMMARY" in src
