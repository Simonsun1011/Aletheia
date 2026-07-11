"""Feed API + disabled source + digest resilience."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.app.feed.config import load_feeds
from backend.app.main import app
from backend.app.models import FeedCard
from backend.app.services.digest import digest_batch
from backend.app.stores.sqlite_store import SqliteStore
from backend.app.ai.adapter import CompletionResult


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


def test_disabled_feed_not_in_enabled(tmp_path):
    cfg = tmp_path / "feeds.toml"
    cfg.write_text(
        """
[[feeds]]
id = "on"
name = "On"
type = "rss"
url = "https://example.com/a.xml"
enabled = true

[[feeds]]
id = "off"
name = "Off"
type = "rss"
url = "https://example.com/b.xml"
enabled = false
""",
        encoding="utf-8",
    )
    feeds = load_feeds(cfg)
    assert [f.id for f in feeds if f.enabled] == ["on"]


def test_list_feed_latest_batch(client, store):
    store.upsert_feed_card(
        FeedCard(
            id="01CARD1",
            fetched_at="2026-07-11T20:00:00Z",
            published_at="2026-07-11T18:00:00Z",
            source="Test",
            title="Micron HBM4 production update",
            url="https://example.com/x",
            summary="Micron announced HBM4 production.",
            objects='["MU"]',
            dedup_group="dg1",
            batch_date="2026-07-11",
        )
    )
    r = client.get("/api/feed")
    assert r.status_code == 200
    body = r.json()
    assert body["batch_date"] == "2026-07-11"
    assert len(body["cards"]) == 1
    assert body["cards"][0]["object_list"] == ["MU"]


def test_list_feed_purges_irrelevant_existing_cards(client, store):
    store.upsert_feed_card(
        FeedCard(
            id="01NOISE",
            fetched_at="2026-07-11T20:00:00Z",
            published_at="2026-07-11T18:00:00Z",
            source="PR Newswire Tech",
            title="Leadership Expert Shares Values-Based Leadership in Real Estate",
            url="https://example.com/noise",
            summary="Morgan Communities discussed daily leadership practices.",
            objects="[]",
            dedup_group="dg-noise",
            batch_date="2026-07-11",
        )
    )
    store.upsert_feed_card(
        FeedCard(
            id="01KEEP",
            fetched_at="2026-07-11T20:00:00Z",
            published_at="2026-07-11T18:00:00Z",
            source="PR Newswire Tech",
            title="Applied Materials ships new systems",
            url="https://example.com/amat",
            summary="Applied Materials announced tool shipments.",
            objects="[]",
            dedup_group="dg-amat",
            batch_date="2026-07-11",
        )
    )
    r = client.get("/api/feed?date=2026-07-11")
    assert r.status_code == 200
    body = r.json()
    titles = [c["title"] for c in body["cards"]]
    assert any("Applied Materials" in t for t in titles)
    assert not any("Leadership" in t for t in titles)
    assert body["purged_on_read"] >= 1
    assert store.get_feed_card("01NOISE") is None
    assert len(store.list_filtered_items(batch_date="2026-07-11")) >= 1


def test_digest_one_failure_does_not_block_rest(store, monkeypatch):
    store.insert_feed_raw(
        {
            "id": "r1",
            "fetched_at": "2026-07-11T12:00:00Z",
            "published_at": None,
            "source": "A",
            "title": "AMAT Good story about wafers",
            "url": "https://example.com/1",
            "content": "Applied Materials shipped more wafers.",
            "objects": "[]",
            "batch_date": "2026-07-11",
            "feed_id": "prnewswire_tech",
        }
    )
    store.insert_feed_raw(
        {
            "id": "r2",
            "fetched_at": "2026-07-11T12:00:00Z",
            "published_at": None,
            "source": "B",
            "title": "Micron HBM4 packaging line news",
            "url": "https://example.com/2",
            "content": "New HBM packaging line opened.",
            "objects": "[]",
            "batch_date": "2026-07-11",
            "feed_id": "prnewswire_tech",
        }
    )

    calls = {"n": 0}

    def flaky(**kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("boom")
        return CompletionResult(
            text="Micron opened a new HBM packaging line.",
            model="mock",
            prompt_version="summarize_card_v1.md",
            elapsed_ms=1,
        )

    monkeypatch.setattr("backend.app.services.digest.ai_adapter.complete", flaky)
    stats = digest_batch(store, "2026-07-11")
    assert stats["fail"] >= 1
    assert stats["ok"] >= 1
    assert len(store.list_feed_cards(batch_date="2026-07-11")) >= 1
