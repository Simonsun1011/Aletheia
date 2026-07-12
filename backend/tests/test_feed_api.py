"""Feed API + disabled source + digest resilience."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.app.ai.adapter import CompletionResult
from backend.app.feed.config import load_feeds
from backend.app.main import app
from backend.app.models import FeedCard
from backend.app.services.digest import digest_batch
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


def test_digest_persists_all_cards_without_completion(store, monkeypatch):
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

    def fail_tag_call(**kwargs):
        calls["n"] += 1
        assert kwargs["purpose"] != "summary"
        raise RuntimeError("tag model unavailable")

    monkeypatch.setattr(
        "backend.app.services.digest.ai_adapter.complete", fail_tag_call
    )
    stats = digest_batch(store, "2026-07-11")
    cards = store.list_feed_cards(batch_date="2026-07-11")
    assert calls["n"] == 2
    assert stats["fail"] == 0
    assert stats["ok"] == 2
    assert len(cards) == 2
    assert all(card.summary is None for card in cards)


def _lazy_card(store, *, card_id="lazy", excerpt="Micron opened an HBM line."):
    store.upsert_feed_card(
        FeedCard(
            id=card_id,
            fetched_at="2026-07-11T20:00:00Z",
            source="Test",
            title="Micron opens HBM production line",
            url=f"https://example.com/{card_id}",
            excerpt=excerpt,
            summary=None,
            objects='["MU"]',
            batch_date="2026-07-11",
        )
    )


def test_lazy_summary_and_translation_are_cached(client, store, monkeypatch):
    _lazy_card(store)
    calls = []

    def complete(**kwargs):
        calls.append(kwargs)
        text = (
            "美光开设了 HBM 生产线。"
            if kwargs["prompt_file"] == "translate_summary_v1.md"
            else "Micron opened an HBM production line."
        )
        return CompletionResult(
            text=text,
            model="mock",
            prompt_version=kwargs["prompt_file"],
            elapsed_ms=1,
        )

    monkeypatch.setattr("backend.app.services.feed_summary.ai_adapter.complete", complete)
    first = client.post("/api/feed/lazy/summary")
    second = client.post("/api/feed/lazy/summary")
    assert first.status_code == second.status_code == 200
    assert first.json()["cached"] is False
    assert second.json()["cached"] is True
    assert len([c for c in calls if c["purpose"] == "summary"]) == 1

    translated = client.post("/api/feed/lazy/summary/translate?lang=zh")
    translated_again = client.post("/api/feed/lazy/summary/translate?lang=zh")
    assert translated.status_code == translated_again.status_code == 200
    assert translated_again.json()["cached"] is True
    assert len(calls) == 2


def test_lazy_summary_guard_and_missing_excerpt(client, store, monkeypatch):
    _lazy_card(store, card_id="bad")
    monkeypatch.setattr(
        "backend.app.services.feed_summary.ai_adapter.complete",
        lambda **kwargs: CompletionResult(
            text="因此建议买入。",
            model="mock",
            prompt_version="summarize_card_v2.md",
            elapsed_ms=1,
        ),
    )
    blocked = client.post("/api/feed/bad/summary")
    assert blocked.status_code == 422
    assert blocked.json()["error"]["code"] == "AI_GUARD_VIOLATION"

    _lazy_card(store, card_id="empty", excerpt="")
    empty = client.post("/api/feed/empty/summary")
    assert empty.status_code == 422
    assert empty.json()["error"]["code"] == "EXCERPT_REQUIRED"
    untranslated = client.post("/api/feed/empty/summary/translate?lang=zh")
    assert untranslated.status_code == 409
    assert untranslated.json()["error"]["code"] == "SUMMARY_REQUIRED"


def test_mark_only_without_summary_and_comment_gate(client, store):
    _lazy_card(store, card_id="mark-only")
    marked = client.post("/api/feed/mark-only/mark", json={"marked": True})
    assert marked.status_code == 200
    assert marked.json()["marked"] is True
    comment = client.post(
        "/api/feed/mark-only/mark",
        json={"user_comment": "先记一下", "source_lang": "zh"},
    )
    assert comment.status_code == 409
    assert comment.json()["error"]["code"] == "SUMMARY_REQUIRED"
