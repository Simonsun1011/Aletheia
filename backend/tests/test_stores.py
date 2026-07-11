"""Store / JSONL / rebuild acceptance tests (slice-01)."""

from __future__ import annotations

from backend.app.models import JudgmentCreate, NoteCreate
from backend.app.stores import jsonl_mirror
from backend.app.stores.rebuild import rebuild
from backend.app.stores.sqlite_store import SqliteStore

VALID = JudgmentCreate(
    object="AMAT",
    jtype="action",
    direction="outperform",
    horizon_days=40,
    confidence=0.6,
    text="原话锁定",
)


def test_jsonl_grows_and_matches_db(store):
    before = jsonl_mirror.count_rows(store.journal_dir, "judgment_entries")
    entry = store.create_judgment(VALID)
    after = jsonl_mirror.count_rows(store.journal_dir, "judgment_entries")
    assert after == before + 1

    rows = [
        r
        for r in jsonl_mirror.iter_rows(store.journal_dir)
        if r.get("_table") == "judgment_entries" and r.get("id") == entry.id
    ]
    assert len(rows) == 1
    assert rows[0]["text"] == entry.text
    assert rows[0]["root_id"] == entry.root_id


def test_rebuild_from_jsonl(tmp_path):
    db = tmp_path / "app.db"
    journal = tmp_path / "journal"
    store = SqliteStore(db, journal)
    store.init_schema()
    store.create_judgment(VALID)
    store.create_note(NoteCreate(text="随感", object="AMAT"))
    store.create_judgment(
        JudgmentCreate(
            object="MRVL",
            jtype="fact",
            text="某事是否属实的判断",
        )
    )
    j_n = jsonl_mirror.count_rows(journal, "judgment_entries")
    n_n = jsonl_mirror.count_rows(journal, "quick_notes")
    store.close()

    db.unlink()
    assert not db.exists()

    counts = rebuild(db, journal)
    assert counts["judgment_entries"] == j_n
    assert counts["quick_notes"] == n_n

    rebuilt = SqliteStore(db, journal)
    rebuilt.init_schema()  # IF NOT EXISTS — tables already there
    chains = rebuilt.list_chains()
    notes = rebuilt.list_notes()
    assert sum(len(c.entries) for c in chains) == j_n
    assert len(notes) == n_n
    rebuilt.close()


def test_watchlist_requires_reason_and_archive_hides_from_active(client):
    r = client.post("/api/watchlist", json={"ticker": "AMAT"})
    assert r.status_code == 422

    ok = client.post(
        "/api/watchlist",
        json={"ticker": "AMAT", "add_reason": "AI上游设备核心"},
    )
    assert ok.status_code == 201
    assert ok.json()["tier"] == "base"

    listed = client.get("/api/watchlist").json()
    assert any(i["ticker"] == "AMAT" for i in listed["active"])

    arch = client.post(
        "/api/watchlist/AMAT/archive",
        json={"archive_reason": "仓位已满，暂停跟踪"},
    )
    assert arch.status_code == 200

    listed2 = client.get("/api/watchlist").json()
    assert not any(i["ticker"] == "AMAT" for i in listed2["active"])


def test_watchlist_tier_default_and_update(client):
    created = client.post(
        "/api/watchlist",
        json={"ticker": "NVDA", "add_reason": "算力核心", "tier": "focus"},
    )
    assert created.status_code == 201
    assert created.json()["tier"] == "focus"

    client.post(
        "/api/watchlist",
        json={"ticker": "MSFT", "add_reason": "云与AI", "tier": "base"},
    )

    focus_only = client.get("/api/watchlist?tier=focus").json()
    assert any(i["ticker"] == "NVDA" for i in focus_only["active"])
    assert not any(i["ticker"] == "MSFT" for i in focus_only["active"])

    updated = client.post(
        "/api/watchlist/NVDA/tier",
        json={"tier": "muted"},
    )
    assert updated.status_code == 200
    assert updated.json()["tier"] == "muted"

    muted = client.get("/api/watchlist?tier=muted").json()
    assert any(i["ticker"] == "NVDA" for i in muted["active"])


def test_watchlist_tier_unknown_ticker_404(client):
    r = client.post("/api/watchlist/ZZZZ/tier", json={"tier": "focus"})
    assert r.status_code == 404


def test_watchlist_invalid_tier_422(client):
    client.post(
        "/api/watchlist",
        json={"ticker": "AMAT", "add_reason": "x"},
    )
    r = client.post("/api/watchlist/AMAT/tier", json={"tier": "hot"})
    assert r.status_code == 422
