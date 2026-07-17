"""Promote card → event draft → confirm."""

from __future__ import annotations

import json

import pytest
from backend.tests.http_client import make_test_client

from backend.app.ai.adapter import CompletionResult
from backend.app.main import app
from backend.app.models import FeedCard
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


def _card(store):
    c = FeedCard(
        id="01PROMOTECARD",
        fetched_at="2026-07-11T20:00:00Z",
        published_at="2026-07-11T18:00:00Z",
        source="PR",
        title="AMAT announces new etch tool",
        url="https://example.com/amat",
        summary="Applied Materials announced a new etch tool for advanced nodes.",
        objects='["AMAT"]',
        dedup_group="dg",
        batch_date="2026-07-11",
    )
    store.upsert_feed_card(c)
    return c


def test_promote_then_confirm(client, store, monkeypatch):
    _card(store)
    payload = {
        "object": "AMAT",
        "event_date": "2026-07-11",
        "category": "company",
        "source_url": "https://example.com/amat",
        "fact_text": "Applied Materials announced a new etch tool.",
        "impact_path": "May relate to advanced-node equipment demand.",
        "confirmation": "confirmed",
    }
    monkeypatch.setattr(
        "backend.app.services.changefeed.ai_adapter.complete",
        lambda **kw: CompletionResult(
            text=json.dumps(payload),
            model="mock",
            prompt_version="promote_event_v1.md",
            elapsed_ms=1,
        ),
    )
    r = client.post("/api/feed/01PROMOTECARD/promote")
    assert r.status_code == 201
    draft = r.json()
    assert draft["user_confirmed"] == 0
    assert draft["fact_text"] == (
        "Applied Materials announced a new etch tool for advanced nodes."
    )
    assert client.get("/api/changefeed").json() == []

    conf = client.post(
        f"/api/changefeed/{draft['id']}/confirm", json={"scope": "company"}
    )
    assert conf.status_code == 200
    assert conf.json()["scope"] == "company"
    listed = client.get("/api/changefeed?object=AMAT").json()
    assert any(e["id"] == draft["id"] for e in listed)


def test_promote_guard_violation(client, store, monkeypatch):
    _card(store)
    bad = {
        "object": "AMAT",
        "impact_path": "因此建议买入，目标价250",
        "confirmation": "speculative",
        "category": "company",
    }
    monkeypatch.setattr(
        "backend.app.services.changefeed.ai_adapter.complete",
        lambda **kw: CompletionResult(
            text=json.dumps(bad),
            model="mock",
            prompt_version="promote_event_v1.md",
            elapsed_ms=1,
        ),
    )
    r = client.post("/api/feed/01PROMOTECARD/promote")
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "AI_GUARD_VIOLATION"


def test_promote_requires_summary(client, store):
    card = _card(store)
    store.cache_feed_summary(card.id, "", "2026-07-11T20:01:00Z")
    r = client.post("/api/feed/01PROMOTECARD/promote")
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "SUMMARY_REQUIRED"
