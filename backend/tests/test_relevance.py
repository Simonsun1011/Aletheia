"""Slice 3b relevance hard-filter tests."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.app.ai.adapter import CompletionResult
from backend.app.feed.config import load_feeds
from backend.app.feed.relevance import load_relevance
from backend.app.main import app
from backend.app.models import WatchlistCreate
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


def _raw(**kwargs):
    base = {
        "id": "r1",
        "fetched_at": "2026-07-11T12:00:00Z",
        "published_at": "2026-07-11T11:00:00Z",
        "source": "PR Newswire Tech",
        "title": "x",
        "url": "https://example.com/x",
        "content": "",
        "objects": "[]",
        "batch_date": "2026-07-11",
        "feed_id": "prnewswire_tech",
    }
    base.update(kwargs)
    return base


def test_irrelevant_goes_to_filtered_no_llm(store, monkeypatch):
    """Primary screen discards noise; default does not fill 查看漏杀 list."""
    store.insert_feed_raw(
        _raw(
            id="noise",
            title="Leadership Expert Shares Values-Based Leadership in Real Estate",
            url="https://example.com/noise",
            content="Morgan Communities discussed daily leadership practices.",
        )
    )
    calls = {"n": 0}

    def mock_complete(**kwargs):
        calls["n"] += 1
        return CompletionResult(
            text="should not run",
            model="mock",
            prompt_version="summarize_card_v1.md",
            elapsed_ms=1,
        )

    monkeypatch.setattr("backend.app.services.digest.ai_adapter.complete", mock_complete)
    stats = digest_batch(store, "2026-07-11")
    assert stats["prescreen_discarded"] == 1
    assert stats["filtered"] == 0
    assert stats["ok"] == 0
    assert calls["n"] == 0
    assert store.list_feed_cards(batch_date="2026-07-11") == []
    assert store.list_filtered_items(batch_date="2026-07-11") == []
    assert store.list_feed_raw("2026-07-11") == []


def test_alias_match_enters_card_with_object(store, monkeypatch):
    store.insert_feed_raw(
        _raw(
            id="amat",
            title="Applied Materials announces new etch tool",
            url="https://example.com/amat",
            content="The company shipped systems to leading foundries.",
        )
    )

    def mock_complete(**kwargs):
        return CompletionResult(
            text="Applied Materials announced a new etch tool for foundries.",
            model="mock",
            prompt_version="summarize_card_v1.md",
            elapsed_ms=1,
        )

    monkeypatch.setattr("backend.app.services.digest.ai_adapter.complete", mock_complete)
    stats = digest_batch(store, "2026-07-11")
    assert stats["ok"] == 1
    assert stats["filtered"] == 0
    cards = store.list_feed_cards(batch_date="2026-07-11")
    assert len(cards) == 1
    assert "AMAT" in (cards[0].objects or "")


def test_alias_in_summary_only_does_not_keep(store):
    """Name-drop in summary must not rescue an irrelevant title."""
    from backend.app.feed.relevance import load_relevance
    from backend.app.models import FeedCard
    from backend.app.services.feed_filter import card_is_relevant

    lex = load_relevance(watchlist_tickers=[])
    card = FeedCard(
        id="01X",
        fetched_at="2026-07-11T12:00:00Z",
        title="AlgoLaser Launches DIY KIT MK3 laser engraver",
        url="https://example.com/x",
        summary="The device will launch on Amazon and other retailers.",
        objects="[]",
        batch_date="2026-07-11",
        source="PR Newswire Tech",
    )
    assert not card_is_relevant(card, lex)


def test_skip_relevance_source_bypasses_filter(store, monkeypatch, tmp_path):
    # Use real feeds.toml ids: yahoo_ticker has skip_relevance=true
    store.insert_feed_raw(
        _raw(
            id="yf",
            title="Totally unrelated leadership real estate press release",
            url="https://example.com/yf",
            content="No semiconductor keywords here at all.",
            feed_id="yahoo_ticker",
            source="Yahoo Finance",
        )
    )
    calls = {"n": 0}

    def mock_complete(**kwargs):
        calls["n"] += 1
        return CompletionResult(
            text="Unrelated item summarized factually.",
            model="mock",
            prompt_version="summarize_card_v1.md",
            elapsed_ms=1,
        )

    monkeypatch.setattr("backend.app.services.digest.ai_adapter.complete", mock_complete)
    feeds = load_feeds()
    assert any(f.id == "yahoo_ticker" and f.skip_relevance for f in feeds)
    stats = digest_batch(store, "2026-07-11")
    assert stats["filtered"] == 0
    assert stats["ok"] == 1
    assert calls["n"] == 1


def test_get_feed_filtered(client, store, monkeypatch):
    """查看漏杀 only lists primary discards when FEED_PRESCREEN_AUDIT=1."""
    monkeypatch.setenv("FEED_PRESCREEN_AUDIT", "1")
    store.insert_feed_raw(
        _raw(
            id="noise2",
            title="HelloNation values-based leadership article",
            url="https://example.com/n2",
            content="Real estate sector daily choices.",
        )
    )

    def mock_complete(**kwargs):
        raise AssertionError("LLM must not be called")

    monkeypatch.setattr("backend.app.services.digest.ai_adapter.complete", mock_complete)
    digest_batch(store, "2026-07-11")

    r = client.get("/api/feed/filtered?date=2026-07-11")
    assert r.status_code == 200
    body = r.json()
    assert body["count"] == 1
    assert "leadership" in body["items"][0]["title"].lower()

    feed = client.get("/api/feed?date=2026-07-11").json()
    assert feed["filtered_count"] == 1
    assert feed["cards"] == []


def test_watchlist_ticker_in_lexicon(store, tmp_path):
    store.add_watchlist(WatchlistCreate(ticker="XYZ", add_reason="test"))
    lex = load_relevance(watchlist_tickers=["XYZ"], path=Path("config/relevance.toml"))
    hit, matched = lex.is_relevant("XYZ expands capacity", "")
    assert hit
    assert "XYZ" in matched
