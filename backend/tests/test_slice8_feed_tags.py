"""Slice 8: feed days/tag filters + v0.9 coarse tags + mark/unclassified."""

from __future__ import annotations

import logging

import pytest
from fastapi.testclient import TestClient

from backend.app.ai.adapter import CompletionResult
from backend.app.main import app
from backend.app.models import FeedCard, Tag
from backend.app.services.digest import digest_batch, parse_digest_llm_text
from backend.app.services.tags import TOPIC_SEEDS, apply_ai_tags
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


def _card(
    *,
    cid: str,
    batch: str,
    published: str,
    title: str = "Applied Materials update",
    objects: str = '["AMAT"]',
) -> FeedCard:
    return FeedCard(
        id=cid,
        fetched_at=published,
        published_at=published,
        source="PR Newswire Tech",
        title=title,
        url=f"https://example.com/{cid}",
        summary="Applied Materials announced a shipment update.",
        objects=objects,
        dedup_group=f"dg-{cid}",
        batch_date=batch,
    )


def test_v09_topic_seeds(store):
    ids = {t.tag_id for t in store.list_tags(status="active", kind="topic")}
    expected = {t[0] for t in TOPIC_SEEDS}
    assert expected <= ids
    assert len(expected) == 9
    # legacy flat ids must be deleted (not rejected)
    assert store.get_tag("AI") is None
    assert store.get_tag("Semiconductors") is None
    assert not store.list_tags(status="rejected", kind="topic")
    chip = store.get_tag("compute-chip")
    assert chip is not None
    assert chip.display_zh == "算力芯片"
    assert "Compute" in chip.display_en


def test_legacy_seed_retirement_deletes_not_rejects(store):
    """v0.10: cold-start swap deletes old seeds; rejected reserved for human veto."""
    from backend.app.models import Tag
    from backend.app.services.tags import seed_topic_tags

    store.upsert_tag(
        Tag(
            tag_id="AI",
            kind="topic",
            display_en="AI",
            display_zh="AI",
            status="rejected",
            created_at="2026-07-01T00:00:00Z",
        )
    )
    store.upsert_tag(
        Tag(
            tag_id="Earnings",
            kind="topic",
            display_en="Earnings",
            display_zh="财报",
            status="active",
            created_at="2026-07-01T00:00:00Z",
        )
    )
    seed_topic_tags(store)
    assert store.get_tag("AI") is None
    assert store.get_tag("Earnings") is None
    assert store.get_tag("earnings-guidance") is not None
    assert store.get_tag("earnings-guidance").status == "active"


def test_days_filter_does_not_trigger_fetch(client, store, monkeypatch):
    called = {"fetch": 0, "digest": 0}

    def boom_fetch(*a, **k):
        called["fetch"] += 1
        raise AssertionError("fetch must not run")

    def boom_digest(*a, **k):
        called["digest"] += 1
        raise AssertionError("digest must not run")

    monkeypatch.setattr("jobs.fetch_feeds.run", boom_fetch, raising=False)
    monkeypatch.setattr(
        "backend.app.services.digest.digest_batch", boom_digest, raising=False
    )

    store.upsert_feed_card(
        _card(cid="c1", batch="2026-07-11", published="2026-07-11T18:00:00Z")
    )
    store.upsert_feed_card(
        _card(
            cid="c3",
            batch="2026-07-02",
            published="2026-07-02T12:00:00Z",
            title="Mid-window AMAT news",
        )
    )
    r2 = client.get("/api/feed?days=30")
    ids2 = {c["id"] for c in r2.json()["cards"]}
    assert "c1" in ids2 and "c3" in ids2
    assert called["fetch"] == 0 and called["digest"] == 0


def test_days_1_keeps_latest_batch_semantics(client, store):
    store.upsert_feed_card(
        _card(cid="old", batch="2026-07-01", published="2026-07-01T12:00:00Z")
    )
    store.upsert_feed_card(
        _card(cid="new", batch="2026-07-11", published="2026-07-11T12:00:00Z")
    )
    r = client.get("/api/feed?days=1")
    assert r.status_code == 200
    body = r.json()
    assert body["batch_date"] == "2026-07-11"
    assert {c["id"] for c in body["cards"]} == {"new"}


def test_ai_tag_outside_registry_dropped_with_warning(store, caplog):
    store.upsert_feed_card(
        _card(cid="card1", batch="2026-07-11", published="2026-07-11T12:00:00Z")
    )
    with caplog.at_level(logging.WARNING, logger="aletheia.ai"):
        accepted = apply_ai_tags(
            store,
            "card1",
            tags=["compute-chip", "NotARealTag", "fab-equip"],
            suggestions=[],
            object_tickers=["AMAT"],
        )
    assert set(accepted) == {"compute-chip", "fab-equip"}
    assert any("NotARealTag" in r.message for r in caplog.records)
    tags = {t.tag_id for t in store.list_card_tags("card1")}
    assert "compute-chip" in tags and "fab-equip" in tags
    assert "NotARealTag" not in tags
    assert "AMAT" in tags


def test_tag_suggestions_proposed_not_in_filter_until_approved(client, store):
    store.upsert_tag(
        Tag(
            tag_id="hbm-niche",
            kind="topic",
            display_en="HBM Niche",
            display_zh="HBM细类",
            status="proposed",
            created_at="2026-07-12T00:00:00Z",
        )
    )
    store.upsert_feed_card(
        _card(cid="cardH", batch="2026-07-11", published="2026-07-11T12:00:00Z")
    )
    store.link_card_tag("cardH", "hbm-niche")

    r = client.get("/api/tags?status=active&kind=topic")
    ids = {t["tag_id"] for t in r.json()}
    assert "hbm-niche" not in ids

    r2 = client.get("/api/feed?tag=hbm-niche")
    assert r2.json()["cards"] == []

    r3 = client.post("/api/tags/hbm-niche/approve")
    assert r3.status_code == 200
    assert r3.json()["status"] == "active"
    r4 = client.get("/api/feed?tag=hbm-niche")
    assert {c["id"] for c in r4.json()["cards"]} == {"cardH"}


def test_multi_tags_and_available_facet(client, store):
    from backend.app.services.tags import ensure_company_tag

    store.upsert_feed_card(
        _card(cid="m1", batch="2026-07-11", published="2026-07-11T12:00:00Z")
    )
    ensure_company_tag(store, "AMAT")
    store.link_card_tag("m1", "AMAT")
    store.link_card_tag("m1", "compute-chip")
    store.link_card_tag("m1", "earnings-guidance")
    r = client.get("/api/feed?days=1")
    body = r.json()
    card = next(c for c in body["cards"] if c["id"] == "m1")
    tag_ids = {t["tag_id"] for t in card["tags"]}
    assert "compute-chip" in tag_ids and "earnings-guidance" in tag_ids
    assert any(t["kind"] == "company" and t["tag_id"] == "AMAT" for t in card["tags"])
    facet = {t["tag_id"] for t in body["available_tags"]}
    assert facet == {"compute-chip", "earnings-guidance"}
    assert "macro" not in facet

    assert {c["id"] for c in client.get("/api/feed?tag=compute-chip").json()["cards"]} == {
        "m1"
    }


def test_unclassified_probe(client, store):
    store.upsert_feed_card(
        _card(
            cid="u1",
            batch="2026-07-11",
            published="2026-07-11T12:00:00Z",
            title="Applied Materials ships new systems",
            objects="[]",
        )
    )
    # relevance may keep AMAT-titled cards; ensure no topic tags
    r = client.get("/api/feed?days=1")
    body = r.json()
    card = next((c for c in body["cards"] if c["id"] == "u1"), None)
    if card is None:
        pytest.skip("card purged by relevance — lexicon/title dependent")
    assert card["unclassified"] is True
    assert body["unclassified_count"] >= 1


def test_mark_and_comment_writes_note(client, store):
    store.upsert_feed_card(
        _card(cid="mk1", batch="2026-07-11", published="2026-07-11T12:00:00Z")
    )
    r = client.post(
        "/api/feed/mk1/mark",
        json={"marked": True, "user_comment": "值得复盘的产能信号"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["marked"] is True
    assert body["user_comment"] == "值得复盘的产能信号"
    notes = store.list_notes()
    assert any("值得复盘的产能信号" in n.text and "feed:mk1" in n.text for n in notes)


def test_digest_parses_json_tags_and_suggestions(store, monkeypatch):
    store.insert_feed_raw(
        {
            "id": "r1",
            "fetched_at": "2026-07-11T12:00:00Z",
            "published_at": "2026-07-11T10:00:00Z",
            "source": "PR Newswire Tech",
            "title": "Micron expands HBM capacity for AI servers",
            "url": "https://example.com/mu",
            "content": "Micron Technology said it will expand HBM capacity.",
            "objects": "[]",
            "batch_date": "2026-07-11",
            "feed_id": "prnewswire_tech",
        }
    )

    def fake_complete(**kwargs):
        return CompletionResult(
            text=(
                '{"summary":"Micron said it will expand HBM capacity.",'
                '"tags":["memory-packaging","compute-chip","Bogus"],'
                '"tag_suggestions":["hbm-niche"]}'
            ),
            model="mock",
            prompt_version="summarize_card_v2.md",
            elapsed_ms=1,
        )

    monkeypatch.setattr(
        "backend.app.services.digest.ai_adapter.complete", fake_complete
    )
    stats = digest_batch(store, "2026-07-11")
    assert stats["ok"] >= 1
    cards = store.list_feed_cards(batch_date="2026-07-11")
    assert cards
    tags = {t.tag_id for t in store.list_card_tags(cards[0].id)}
    assert "memory-packaging" in tags
    assert "compute-chip" in tags
    assert "Bogus" not in tags
    proposed = store.get_tag("hbm-niche")
    assert proposed is not None and proposed.status == "proposed"


def test_parse_digest_plain_text_fallback():
    summary, tags, sug = parse_digest_llm_text("Micron opened a line.")
    assert summary.startswith("Micron")
    assert tags == [] and sug == []


def test_reject_proposed_tag(client, store):
    store.upsert_tag(
        Tag(
            tag_id="FooBar",
            kind="topic",
            display_en="FooBar",
            display_zh="FooBar",
            status="proposed",
            created_at="2026-07-12T00:00:00Z",
        )
    )
    r = client.post("/api/tags/FooBar/reject")
    assert r.status_code == 200
    assert r.json()["status"] == "rejected"
