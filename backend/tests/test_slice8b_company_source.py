"""Slice 8b: watchlist is the single company-source authority."""

from __future__ import annotations

import pytest
from backend.tests.http_client import make_test_client

from backend.app.main import app
from backend.app.models import Tag, WatchlistArchive, WatchlistCreate
from backend.app.services.tags import (
    DEFAULT_WATCHLIST_SEED,
    archive_company_tag,
    ensure_company_tag,
    seed_default_watchlist_if_empty,
)
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


def test_get_watchlist_seeds_defaults_when_empty(client, store):
    assert store.list_watchlist().active == []
    r = client.get("/api/watchlist")
    assert r.status_code == 200
    body = r.json()
    tickers = {x["ticker"] for x in body["active"]}
    assert tickers == {t for t, _ in DEFAULT_WATCHLIST_SEED}
    # second call does not duplicate
    r2 = client.get("/api/watchlist")
    assert len(r2.json()["active"]) == len(DEFAULT_WATCHLIST_SEED)


def test_seed_idempotent_after_full_archive(store):
    seed_default_watchlist_if_empty(store)
    for t, _ in DEFAULT_WATCHLIST_SEED:
        store.archive_watchlist(
            t, WatchlistArchive(archive_reason="clear for test")
        )
    assert store.list_watchlist().active == []
    assert store.watchlist_has_any_row() is True
    n = seed_default_watchlist_if_empty(store)
    assert n == 0
    assert store.list_watchlist().active == []


def test_add_creates_company_tag(client, store):
    r = client.post(
        "/api/watchlist",
        json={"ticker": "SPCX", "add_reason": "test add", "tier": "focus"},
    )
    assert r.status_code == 201
    tag = store.get_tag("SPCX")
    assert tag is not None
    assert tag.kind == "company"
    assert tag.status == "active"


def test_archive_sets_company_tag_archived_keeps_card_tags(client, store):
    client.post(
        "/api/watchlist",
        json={"ticker": "SPCX", "add_reason": "add", "tier": "base"},
    )
    # attach a fake card_tag link
    from backend.app.models import FeedCard

    store.upsert_feed_card(
        FeedCard(
            id="card-spcx",
            fetched_at="2026-07-12T00:00:00Z",
            published_at="2026-07-12T00:00:00Z",
            source="t",
            title="SPCX news",
            url="https://example.com/spcx",
            summary="fact",
            objects='["SPCX"]',
            dedup_group="dg",
            batch_date="2026-07-12",
        )
    )
    store.link_card_tag("card-spcx", "SPCX")

    r = client.post(
        "/api/watchlist/SPCX/archive",
        json={"archive_reason": "no longer tracking"},
    )
    assert r.status_code == 200
    assert r.json()["status"] == "archived"
    assert store.get_tag("SPCX").status == "archived"
    # history retained
    assert any(t.tag_id == "SPCX" for t in store.list_card_tags("card-spcx"))
    # not in active watchlist / active company filter set
    wl = client.get("/api/watchlist").json()
    assert "SPCX" not in {x["ticker"] for x in wl["active"]}
    active_co = client.get("/api/tags?status=active&kind=company").json()
    assert "SPCX" not in {t["tag_id"] for t in active_co}


def test_company_tags_superset_includes_shadow(store):
    store.add_watchlist(
        WatchlistCreate(ticker="AAA", add_reason="active", tier="base")
    )
    # insert shadow directly
    store._conn.execute(
        """
        INSERT INTO watchlist (ticker, added_at, add_reason, status, tier)
        VALUES ('BBB', '2026-07-12T00:00:00Z', 'shadow', 'shadow', 'base')
        """
    )
    store._conn.commit()
    ensure_company_tag(store, "BBB")
    wl = store.list_watchlist()
    active_syms = {i.ticker for i in wl.active}
    assert active_syms == {"AAA"}
    tags = {t.tag_id for t in store.list_tags(status="active", kind="company")}
    assert "AAA" in tags and "BBB" in tags
    assert tags >= active_syms


def test_readd_archived_reactivates_company_tag(client, store):
    client.post(
        "/api/watchlist",
        json={"ticker": "ZZZZ", "add_reason": "first", "tier": "base"},
    )
    client.post(
        "/api/watchlist/ZZZZ/archive",
        json={"archive_reason": "gone"},
    )
    assert store.get_tag("ZZZZ").status == "archived"
    r = client.post(
        "/api/watchlist",
        json={"ticker": "ZZZZ", "add_reason": "back", "tier": "base"},
    )
    assert r.status_code == 201
    assert r.json()["status"] == "active"
    assert store.get_tag("ZZZZ").status == "active"


def test_archive_company_tag_helper(store):
    ensure_company_tag(store, "HELP")
    t = archive_company_tag(store, "HELP")
    assert t is not None and t.status == "archived"
