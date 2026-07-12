"""Slice 3c priority scoring + fold."""

from __future__ import annotations

from backend.app.ai.adapter import CompletionResult
from backend.app.feed.priority import score_candidate
from backend.app.feed.triage import triage, triage_configured
from backend.app.services.digest import digest_batch


def _raw(**kwargs):
    base = {
        "id": "r1",
        "fetched_at": "2026-07-12T12:00:00Z",
        "published_at": "2026-07-12T12:00:00Z",
        "source": "Yahoo Finance",
        "title": "NVIDIA announces AI chip shipment update",
        "url": "https://example.com/1",
        "content": "NVIDIA said it shipped additional AI GPUs this quarter.",
        "objects": '["NVDA"]',
        "batch_date": "2026-07-12",
        "feed_id": "yahoo_ticker",
    }
    base.update(kwargs)
    return base


def test_sec_scores_above_wire():
    sec = score_candidate(
        title="Form 8-K: Micron reports material agreement",
        content="SEC filing.",
        source="SEC EDGAR recent",
        feed_ids=["sec_atom"],
        objects=["MU"],
        url_count=1,
        published_at="2026-07-12T12:00:00Z",
        title_hit_tickers=["MU"],
        body_hit_tickers=[],
        theme_hit=False,
        tier_by_ticker={"MU": "focus"},
    )
    wire = score_candidate(
        title="Company Welcomes New EVP of Sales",
        content="Press release about leadership.",
        source="GlobeNewswire",
        feed_ids=["globenewswire"],
        objects=[],
        url_count=1,
        published_at="2026-07-12T12:00:00Z",
        title_hit_tickers=[],
        body_hit_tickers=[],
        theme_hit=False,
        tier_by_ticker={},
    )
    assert sec.score > wire.score
    assert any("SEC" in r or "focus" in r for r in sec.reasons)


def test_triage_stub_default_off():
    assert triage_configured() is False
    assert triage("anything", "lede") == 0


def test_digest_folds_tail_not_blind_drop(store, monkeypatch):
    titles = [
        ("Form 8-K Micron capacity expansion", "SEC EDGAR recent", "sec_atom", '["MU"]'),
        ("NVIDIA AI GPU shipment update", "Yahoo Finance", "yahoo_ticker", '["NVDA"]'),
        ("TSMC CoWoS capacity plan", "Google News", "google_news_ticker", '["TSM"]'),
        ("Random Wire Welcomes New EVP", "GlobeNewswire", "globenewswire", "[]"),
        ("Another Wire Partnership Announcement", "PR Newswire Tech", "prnewswire_tech", "[]"),
    ]
    # Make wire items relevant via theme so they survive filter when not skip
    for i, (title, source, fid, objs) in enumerate(titles):
        content = title
        if "Wire" in source or "PR" in source:
            content = f"{title}. semiconductor AI chip foundry note."
            # need relevance for non-skip sources
        store.insert_feed_raw(
            _raw(
                id=f"p{i}",
                title=title,
                url=f"https://example.com/p{i}",
                source=source,
                feed_id=fid,
                objects=objs,
                content=content,
            )
        )
    # seed watchlist tiers
    from backend.app.models import WatchlistCreate

    store.add_watchlist(WatchlistCreate(ticker="MU", tier="focus", add_reason="test"))
    store.add_watchlist(WatchlistCreate(ticker="NVDA", tier="focus", add_reason="test"))
    store.add_watchlist(WatchlistCreate(ticker="TSM", tier="base", add_reason="test"))

    calls = {"n": 0}

    def mock_complete(**kwargs):
        calls["n"] += 1
        return CompletionResult(
            text='{"summary":"Company announced a semiconductor update.","tags":["compute-chip"],"tag_suggestions":[]}',
            model="mock",
            prompt_version="summarize_card_v2.md",
            elapsed_ms=1,
        )

    monkeypatch.setattr("backend.app.services.digest.ai_adapter.complete", mock_complete)
    stats = digest_batch(store, "2026-07-12", max_llm=2)
    assert calls["n"] == 2
    assert stats["ok"] == 2
    assert stats.get("folded", 0) >= 1
    cards = store.list_feed_cards(batch_date="2026-07-12", days=1)
    folded = [c for c in cards if c.folded]
    summarized = [c for c in cards if not c.folded and c.summary]
    assert len(summarized) == 2
    assert len(folded) >= 1
    # SEC/focus should be in summarized, not only wires
    assert any("8-K" in c.title or "NVIDIA" in c.title for c in summarized)
    assert all(c.priority_score is not None for c in cards)
