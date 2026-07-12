"""Slice 3c: per-ticker tier=base + relevance blocklist + prescreen-first."""

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
from jobs.fetch_feeds import tickers_for_tier


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


def test_per_ticker_feeds_use_base_tier():
    feeds = {f.id: f for f in load_feeds()}
    assert feeds["yahoo_ticker"].tier == "base"
    assert feeds["yahoo_ticker"].skip_relevance is True
    assert feeds["google_news_ticker"].tier == "base"
    assert feeds["google_news_ticker"].skip_relevance is True
    assert "AI+OR+earnings" in feeds["google_news_ticker"].url or "earnings" in feeds[
        "google_news_ticker"
    ].url


def test_tickers_for_base_includes_base_and_focus(store):
    store.add_watchlist(
        WatchlistCreate(ticker="NVDA", add_reason="focus", tier="focus")
    )
    store.add_watchlist(
        WatchlistCreate(ticker="AMAT", add_reason="base", tier="base")
    )
    store.add_watchlist(
        WatchlistCreate(ticker="MUTE", add_reason="muted", tier="muted")
    )
    got = set(tickers_for_tier(store, "base"))
    assert "NVDA" in got and "AMAT" in got
    assert "MUTE" not in got


def test_blocklist_filters_law_firm_pr(store, monkeypatch):
    """Primary screen discards blocklist hits; default = count only, no 漏杀 list."""
    store.insert_feed_raw(
        {
            "id": "law1",
            "fetched_at": "2026-07-12T12:00:00Z",
            "published_at": "2026-07-12T11:00:00Z",
            "source": "PR Newswire Tech",
            "title": "Rosen Law Firm Reminds Investors of Class Action Against NVDA",
            "url": "https://example.com/law",
            "content": "Shareholder alert: investors who purchased NVDA shares...",
            "objects": "[]",
            "batch_date": "2026-07-12",
            "feed_id": "prnewswire_tech",
        }
    )
    calls = {"n": 0}

    def mock_complete(**kwargs):
        calls["n"] += 1
        return CompletionResult(
            text="should not run",
            model="mock",
            prompt_version="summarize_card_v2.md",
            elapsed_ms=1,
        )

    monkeypatch.setattr(
        "backend.app.services.digest.ai_adapter.complete", mock_complete
    )
    stats = digest_batch(store, "2026-07-12")
    assert stats["prescreen_discarded"] >= 1
    assert stats["filtered"] == 0
    assert stats["ok"] == 0
    assert calls["n"] == 0
    assert store.list_feed_cards(batch_date="2026-07-12") == []
    assert store.list_filtered_items(batch_date="2026-07-12") == []
    assert store.list_feed_raw("2026-07-12") == []


def test_blocklist_beats_positive_alias(store):
    lex = load_relevance(watchlist_tickers=["NVDA"])
    hit, _ = lex.is_relevant(
        "Pomerantz Law Firm Announces Class Action Against NVIDIA",
        "investigation initiated on behalf of shareholders",
    )
    assert hit is False
    assert lex.is_blocked(
        "Pomerantz Law Firm Announces Class Action Against NVIDIA",
        "investigation initiated",
    )


def test_blocklist_visible_via_feed_filtered(client, store, monkeypatch):
    """Only with FEED_PRESCREEN_AUDIT=1 do primary discards enter 查看漏杀."""
    monkeypatch.setenv("FEED_PRESCREEN_AUDIT", "1")
    store.insert_feed_raw(
        {
            "id": "law2",
            "fetched_at": "2026-07-12T12:00:00Z",
            "published_at": None,
            "source": "GlobeNewswire",
            "title": "Bragar Eagel shareholder alert for AMAT purchasers",
            "url": "https://example.com/be",
            "content": "lead plaintiff deadline approaches",
            "objects": "[]",
            "batch_date": "2026-07-12",
            "feed_id": "globenewswire",
        }
    )
    monkeypatch.setattr(
        "backend.app.services.digest.ai_adapter.complete",
        lambda **k: CompletionResult(
            text="x", model="m", prompt_version="v", elapsed_ms=1
        ),
    )
    digest_batch(store, "2026-07-12")
    r = client.get("/api/feed/filtered?date=2026-07-12")
    assert r.status_code == 200
    titles = [i["title"] for i in r.json()["items"]]
    assert any("Bragar Eagel" in t for t in titles)


def test_prescreen_before_dedup_and_raw_discarded(store, monkeypatch):
    """Irrelevant noise is discarded before merge; feed_raw cleared after digest."""
    for i in range(20):
        store.insert_feed_raw(
            {
                "id": f"noise{i}",
                "fetched_at": "2026-07-12T12:00:00Z",
                "published_at": None,
                "source": "PR Newswire Tech",
                "title": f"Leadership Expert Shares Values in Real Estate #{i}",
                "url": f"https://example.com/noise{i}",
                "content": "Morgan Communities discussed daily leadership practices.",
                "objects": "[]",
                "batch_date": "2026-07-12",
                "feed_id": "prnewswire_tech",
            }
        )
    store.insert_feed_raw(
        {
            "id": "keep1",
            "fetched_at": "2026-07-12T12:00:00Z",
            "published_at": None,
            "source": "PR Newswire Tech",
            "title": "Applied Materials announces new etch tool",
            "url": "https://example.com/amat",
            "content": "The company shipped systems to leading foundries.",
            "objects": "[]",
            "batch_date": "2026-07-12",
            "feed_id": "prnewswire_tech",
        }
    )
    merge_calls = {"n": 0}
    real_merge = __import__(
        "backend.app.feed.dedup", fromlist=["merge_items"]
    ).merge_items

    def wrap_merge(items):
        merge_calls["n"] += 1
        merge_calls["size"] = len(items)
        return real_merge(items)

    monkeypatch.setattr("backend.app.services.digest.merge_items", wrap_merge)
    monkeypatch.setattr(
        "backend.app.services.digest.ai_adapter.complete",
        lambda **k: CompletionResult(
            text="Applied Materials announced a new etch tool for foundries.",
            model="mock",
            prompt_version="summarize_card_v2.md",
            elapsed_ms=1,
        ),
    )
    stats = digest_batch(store, "2026-07-12")
    assert stats["raw"] == 21
    assert stats["prescreen_discarded"] == 20
    assert stats["survivors"] == 1
    assert stats["ok"] == 1
    assert merge_calls["n"] == 1
    assert merge_calls["size"] == 1
    assert store.list_feed_raw("2026-07-12") == []
    assert store.list_filtered_items(batch_date="2026-07-12") == []
