"""Digest display limit / cancel / skip-existing."""

from __future__ import annotations

from backend.app.models import FeedCard
from backend.app.services.digest import digest_batch


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


def test_digest_display_limit_folds_but_persists_all(store, monkeypatch):
    titles = [
        "NVIDIA announces new Blackwell GPU shipment plan",
        "TSMC expands CoWoS capacity for AI accelerators",
        "Micron starts HBM4 mass production ramp",
        "ASML reports EUV tool orders from foundries",
        "Broadcom custom AI ASIC design wins update",
    ]
    for index, title in enumerate(titles):
        store.insert_feed_raw(
            _raw(
                id=f"r{index}",
                title=title,
                url=f"https://example.com/{index}",
                content=f"{title}. Semiconductor industry factual note.",
            )
        )

    def fail_if_called(**kwargs):
        raise AssertionError("digest must not call LLM")

    monkeypatch.setattr(
        "backend.app.services.digest.ai_adapter.complete", fail_if_called
    )
    stats = digest_batch(store, "2026-07-12", display_max=2)
    cards = store.list_feed_cards(batch_date="2026-07-12", days=1)

    assert stats["ok"] == 5
    assert stats["display_max"] == 2
    assert stats["folded"] == 3
    assert len(cards) == 5
    assert sum(card.folded for card in cards) == 3
    assert all(card.summary is None for card in cards)


def test_max_llm_is_display_max_compatibility_alias(store):
    titles = [
        "NVIDIA launches Blackwell GPU systems",
        "Micron expands HBM packaging capacity",
        "TSMC raises CoWoS production target",
    ]
    for index, title in enumerate(titles):
        store.insert_feed_raw(
            _raw(
                id=f"a{index}",
                title=title,
                url=f"https://example.com/a{index}",
            )
        )
    stats = digest_batch(store, "2026-07-12", max_llm=1)
    assert stats["display_max"] == 1
    assert stats["ok"] == 3
    assert stats["folded"] == 2


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
            summary="Historical summary.",
            objects='["NVDA"]',
            dedup_group=None,
            batch_date="2026-07-12",
        )
    )

    def fail_if_called(**kwargs):
        raise AssertionError("digest must not call LLM")

    monkeypatch.setattr(
        "backend.app.services.digest.ai_adapter.complete", fail_if_called
    )
    stats = digest_batch(store, "2026-07-12")
    assert stats["skipped_existing"] >= 1
    assert stats["ok"] == 0


def test_digest_cancel_midway_without_llm(store, monkeypatch):
    titles = [
        "Micron expands HBM capacity for AI servers",
        "TSMC raises CoWoS output for accelerators",
        "ASML reports EUV orders from foundries",
        "NVIDIA launches Blackwell GPU systems",
    ]
    for index, title in enumerate(titles):
        store.insert_feed_raw(
            _raw(
                id=f"c{index}",
                title=title,
                url=f"https://example.com/c{index}",
                objects='["MU"]',
            )
        )
    checks = {"n": 0}

    def should_stop():
        checks["n"] += 1
        return checks["n"] >= 7

    monkeypatch.setattr(
        "backend.app.services.digest.ai_adapter.complete",
        lambda **kwargs: (_ for _ in ()).throw(
            AssertionError("digest must not call LLM")
        ),
    )
    stats = digest_batch(
        store, "2026-07-12", display_max=10, should_stop=should_stop
    )
    assert stats["cancelled"] == 1
    assert stats["ok"] < 4
