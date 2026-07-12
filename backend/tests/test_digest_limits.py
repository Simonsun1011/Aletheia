"""Digest cap / cancel / skip-existing."""

from __future__ import annotations

from backend.app.ai.adapter import CompletionResult
from backend.app.services.digest import digest_batch
from backend.app.models import FeedCard


def _raw(**kwargs):
    base = {
        "id": "r1",
        "fetched_at": "2026-07-12T00:00:00Z",
        "published_at": "2026-07-12T00:00:00Z",
        "source": "Yahoo Finance",
        "title": "NVIDIA AI chip update",
        "url": "https://example.com/1",
        "content": "NVIDIA announces GPU shipment for AI data centers.",
        "objects": '["NVDA"]',
        "batch_date": "2026-07-12",
        "feed_id": "yahoo_ticker",
    }
    base.update(kwargs)
    return base


def test_digest_respects_max_llm(store, monkeypatch):
    titles = [
        "NVIDIA announces new Blackwell GPU shipment plan",
        "TSMC expands CoWoS capacity for AI accelerators",
        "Micron starts HBM4 mass production ramp",
        "ASML reports EUV tool orders from foundries",
        "Broadcom custom AI ASIC design wins update",
    ]
    for i, title in enumerate(titles):
        store.insert_feed_raw(
            _raw(
                id=f"r{i}",
                title=title,
                url=f"https://example.com/{i}",
                content=f"{title}. Semiconductor industry factual note.",
            )
        )
    calls = {"n": 0}

    def mock_complete(**kwargs):
        calls["n"] += 1
        return CompletionResult(
            text='{"summary":"Company announced a semiconductor capacity update.","tags":["compute-chip"],"tag_suggestions":[]}',
            model="mock",
            prompt_version="summarize_card_v2.md",
            elapsed_ms=1,
        )

    monkeypatch.setattr("backend.app.services.digest.ai_adapter.complete", mock_complete)
    stats = digest_batch(store, "2026-07-12", max_llm=2)
    assert calls["n"] == 2
    assert stats["ok"] == 2
    assert stats["capped"] >= 1


def test_digest_skips_existing_card(store, monkeypatch):
    store.insert_feed_raw(
        _raw(id="r0", title="Same story", url="https://example.com/same")
    )
    store.upsert_feed_card(
        FeedCard(
            id="existing",
            fetched_at="2026-07-12T00:00:00Z",
            published_at="2026-07-12T00:00:00Z",
            source="Yahoo Finance",
            title="Same story",
            url="https://example.com/same",
            summary="Already summarized.",
            objects='["NVDA"]',
            dedup_group=None,
            batch_date="2026-07-12",
        )
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

    monkeypatch.setattr("backend.app.services.digest.ai_adapter.complete", mock_complete)
    stats = digest_batch(store, "2026-07-12", max_llm=10)
    assert calls["n"] == 0
    assert stats["skipped_existing"] >= 1


def test_digest_cancel_midway(store, monkeypatch):
    titles = [
        "Micron expands HBM capacity for AI servers",
        "Samsung unveils new HBM roadmap for 2027",
        "SK Hynix qualifies HBM3E at major GPU vendor",
        "Intel foundry packaging alliance update",
    ]
    for i, title in enumerate(titles):
        store.insert_feed_raw(
            _raw(
                id=f"c{i}",
                title=title,
                url=f"https://example.com/c{i}",
                content=f"{title}. Memory packaging industry note.",
                objects='["MU"]',
            )
        )
    flag = {"stop": False}
    calls = {"n": 0}

    def mock_complete(**kwargs):
        calls["n"] += 1
        if calls["n"] >= 1:
            flag["stop"] = True
        return CompletionResult(
            text='{"summary":"Memory maker expands HBM capacity.","tags":["memory-packaging"],"tag_suggestions":[]}',
            model="mock",
            prompt_version="summarize_card_v2.md",
            elapsed_ms=1,
        )

    monkeypatch.setattr("backend.app.services.digest.ai_adapter.complete", mock_complete)
    stats = digest_batch(
        store, "2026-07-12", max_llm=10, should_stop=lambda: flag["stop"]
    )
    assert stats["cancelled"] == 1
    assert calls["n"] == 1
    assert stats["ok"] == 1
