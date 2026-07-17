"""Slice 11 audit quickfixes — regression tests for A/B items."""

from __future__ import annotations

import time
from pathlib import Path

from backend.app.ai.adapter import AdapterError
from backend.app.ai.guard import guard, reset_guard_cache
from backend.app.ai.usage import estimate_cost_usd
from backend.app.feed.language import language_allowed
from backend.app.market.db import connect_market_db
from backend.app.models import FeedCard
from backend.app.services import feed_ingest
from backend.app.services.feed_filter import filter_cards
from backend.app.services.feed_ingest import _parse_published
from backend.app.services.settle import current_version


def setup_function():
    reset_guard_cache()


# ── A1 error envelope ──────────────────────────────────────


def test_a1_promote_missing_card_flat_envelope(client):
    r = client.post("/api/feed/01MISSINGCARD00/promote")
    assert r.status_code == 404
    body = r.json()
    assert "detail" not in body or "error" not in (body.get("detail") or {})
    assert body["error"]["code"] == "NOT_FOUND"
    assert "message" in body["error"]


def test_a1_unknown_path_and_405_flat_envelope(client):
    r404 = client.get("/api/no-such-route-ever")
    assert r404.status_code == 404
    b404 = r404.json()
    assert "error" in b404
    assert b404["error"]["code"] == "HTTP_404"

    r405 = client.delete("/api/judgments/01ANYTHING0000")
    assert r405.status_code == 405
    b405 = r405.json()
    assert "error" in b405
    assert b405["error"]["code"] == "APPEND_ONLY_VIOLATION"


# ── A2 TrustedHost + client header ─────────────────────────


def test_a2_write_requires_client_header(store, monkeypatch):
    monkeypatch.setattr("backend.app.main.create_store", lambda: store)
    from fastapi.testclient import TestClient
    from backend.app.main import app

    with TestClient(app, base_url="http://127.0.0.1") as c:
        c.app.state.store = store
        r = c.post("/api/notes", json={"text": "hi"})
        assert r.status_code == 403
        assert r.json()["error"]["code"] == "HTTP_403"


def test_a2_write_with_header_ok(client):
    r = client.post("/api/notes", json={"text": "slice11 a2"})
    assert r.status_code == 201


def test_a2_get_unaffected_without_header(store, monkeypatch):
    monkeypatch.setattr("backend.app.main.create_store", lambda: store)
    from fastapi.testclient import TestClient
    from backend.app.main import app

    with TestClient(app, base_url="http://127.0.0.1") as c:
        c.app.state.store = store
        r = c.get("/api/health")
        assert r.status_code == 200


def test_a2_bad_host_rejected(store, monkeypatch):
    monkeypatch.setattr("backend.app.main.create_store", lambda: store)
    from fastapi.testclient import TestClient
    from backend.app.main import app

    with TestClient(app, base_url="http://evil.example") as c:
        c.app.state.store = store
        r = c.get("/api/health")
        assert r.status_code == 400


# ── A3 / A4 guard ──────────────────────────────────────────


def test_a3_blocks_做多_allows_做多元化():
    assert not guard("建议做多NVDA", ruleset="conclusion").ok
    assert guard("业务做多元化布局", ruleset="conclusion").ok
    assert not guard("我做多AMAT", ruleset="attributed_views").ok
    assert guard(
        "多方论点：市场做多AI资本开支持续性", ruleset="attributed_views"
    ).ok


def test_a4_fullwidth_raw_input_hits_normalize():
    assert not guard("ｓｔｒｏｎｇ　ｂｕｙ").ok


# ── A5 jobs wire ───────────────────────────────────────────


def test_a5_jobs_wire_llm_usage():
    digest_src = Path("jobs/digest.py").read_text(encoding="utf-8")
    refresh_src = Path("jobs/refresh_feed.py").read_text(encoding="utf-8")
    assert "wire_llm_usage" in digest_src
    assert "wire_llm_usage" in refresh_src


# ── A6 price match ─────────────────────────────────────────


def test_a6_estimate_cost_no_substring_neighbor():
    prices = {"gpt-4o-mini": {"input": 1.0, "output": 2.0}}
    assert estimate_cost_usd("gpt-4o", 100, 100, prices=prices) is None
    assert (
        estimate_cost_usd("openai/grok-4.5", 100, 0, prices={"grok-4.5": {"input": 1.0, "output": 1.0}})
        is not None
    )
    assert (
        estimate_cost_usd("grok-4.5", 100, 0, prices={"openai/grok-4.5": {"input": 1.0, "output": 1.0}})
        is not None
    )


# ── B1 language gate ───────────────────────────────────────


def test_b1_english_homographs_not_other():
    ok, lang = language_allowed(
        "Nvidia rises as much as 5% as demand grows",
        "Shares jumped as much as 5 percent as AI demand grows.",
    )
    assert ok and lang == "en"

    ok2, lang2 = language_allowed(
        "Chipmakers die hard as LA fabs expand capacity",
        "Analysts say die sizes shrink as con revenue grows.",
    )
    assert ok2 and lang2 == "en"

    # Weak markers only (Las/MIT/est.) must not trip "strong" — tech-wire core vocab
    ok3, lang3 = language_allowed(
        "CES 2027 in Las Vegas: MIT researchers est. AI demand to double",
        "",
    )
    assert ok3 and lang3 == "en"

    # nouveau: EN loanword + NVIDIA open-source GPU driver name — must stay weak
    ok4, lang4 = language_allowed(
        "Nouveau driver update",
        "NVIDIA est. to ship new GPUs; demo at Las Vegas next month.",
    )
    assert ok4 and lang4 == "en"


def test_b1_french_spanish_still_rejected():
    ok, lang = language_allowed(
        "EXTRAIT DE LA CONFÉRENCE INTERNATIONALE DE L'ASSOCIATION ALZHEIMER 2026",
        "Une nouvelle étude présentée à la Conférence internationale.",
    )
    assert not ok and lang == "other"

    ok2, lang2 = language_allowed(
        "DEL CONGRESO INTERNACIONAL DE LA ALZHEIMER'S ASSOCIATION 2026",
        "En el Congreso Internacional se presentó una nueva investigación.",
    )
    assert not ok2 and lang2 == "other"


def test_b1_english_card_not_purged_on_read(store):
    card = FeedCard(
        id="01ENGLISHKEEP01",
        fetched_at="2026-07-12T00:00:00Z",
        published_at="2026-07-12T00:00:00Z",
        source="Yahoo Finance",
        title="Nvidia rises as much as 5% as demand grows",
        url="https://example.com/nvda-as",
        summary="Nvidia shares rose as much as 5% as AI demand grows.",
        objects='["NVDA"]',
        batch_date="2026-07-12",
    )
    store.upsert_feed_card(card)
    kept, purged = filter_cards(store, [card], purge=True)
    assert purged == 0
    assert any(c.id == card.id for c in kept)
    assert store.get_feed_card(card.id) is not None


# ── B2 ISO publish time ────────────────────────────────────


def test_b2_iso_published_converts_to_utc():
    class E(dict):
        pass

    entry = E(published="2026-07-11T09:30:00-04:00")
    assert _parse_published(entry) == "2026-07-11T13:30:00Z"


# ── B3 promote AdapterError ────────────────────────────────


def test_b3_promote_adapter_error_503(client, store, monkeypatch):
    c = FeedCard(
        id="01PROMOTEFAIL01",
        fetched_at="2026-07-11T20:00:00Z",
        published_at="2026-07-11T18:00:00Z",
        source="PR",
        title="AMAT tool",
        url="https://example.com/a",
        summary="Applied Materials announced a tool.",
        objects='["AMAT"]',
        dedup_group="dg",
        batch_date="2026-07-11",
    )
    store.upsert_feed_card(c)

    def boom(**kw):
        raise AdapterError("upstream timeout")

    monkeypatch.setattr(
        "backend.app.services.changefeed.ai_adapter.complete", boom
    )
    r = client.post("/api/feed/01PROMOTEFAIL01/promote")
    assert r.status_code == 503
    assert r.json()["error"]["code"] == "AI_ERROR"


# ── B4 current_version same-second ─────────────────────────


def test_b4_current_version_same_second_prefers_newer_id():
    from backend.app.models import JudgmentChain, JudgmentEntry

    ts = "2026-07-11T12:00:00Z"
    older = JudgmentEntry(
        id="01JAAAAAAAOLDER0",
        root_id="01JROOT00000001",
        kind="original",
        created_at=ts,
        object="AMAT",
        jtype="action",
        direction="outperform",
        horizon_days=40,
        confidence=0.5,
        text="v1",
        status="open",
    )
    newer = JudgmentEntry(
        id="01JZZZZZZNEWER0",
        root_id="01JROOT00000001",
        kind="revision",
        created_at=ts,
        object="AMAT",
        jtype="action",
        direction="underperform",
        horizon_days=20,
        confidence=0.7,
        text="v2",
        status="open",
    )
    chain = JudgmentChain(
        root_id="01JROOT00000001",
        object="AMAT",
        status="open",
        entries=[older, newer],
    )
    cur = current_version(chain)
    assert cur.id == newer.id
    assert cur.direction == "underperform"
    assert cur.horizon_days == 20


# ── B5 trade_date normalize ────────────────────────────────


def test_b5_trade_date_zero_padded(client):
    r = client.post(
        "/api/executions",
        json={
            "ticker": "AMAT",
            "side": "buy",
            "trade_date": "2026-7-1",
            "shares": 10,
            "price": 100,
        },
    )
    assert r.status_code == 201
    assert r.json()["trade_date"] == "2026-07-01"


# ── B6 market db WAL ───────────────────────────────────────


def test_b6_market_db_wal(tmp_path):
    conn = connect_market_db(tmp_path / "m.db")
    mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
    conn.close()
    assert str(mode).lower() == "wal"


# ── B7 snapshot ensure warnings ────────────────────────────


def test_b7_snapshot_surfaces_ensure_warnings(client, monkeypatch, tmp_path):
    from backend.app import config
    import backend.app.routers.tickers as tickers_mod

    mdb = tmp_path / "market.db"
    conn = connect_market_db(mdb)
    # minimal bars so snapshot can build
    for i in range(5):
        conn.execute(
            "INSERT INTO prices VALUES (?,?,?,?,?,?,?)",
            ("AMAT", f"2026-01-{i+1:02d}", 1, 1, 1, 100.0 + i, 1000),
        )
    conn.commit()
    conn.close()

    monkeypatch.setattr(
        config,
        "get_settings",
        lambda: config.Settings(
            app_db_path=tmp_path / "app.db",
            journal_dir=tmp_path / "journal",
            cors_origins=["http://localhost:3000"],
            log_level="WARNING",
            log_dir=tmp_path / "logs",
            market_db_path=mdb,
        ),
    )
    monkeypatch.setattr(tickers_mod, "get_settings", config.get_settings)
    monkeypatch.setattr(
        "backend.app.routers.tickers.ensure_local_market_data",
        lambda *a, **k: ["fetch failed for QQQ: boom"],
    )

    r = client.get("/api/tickers/AMAT/snapshot")
    assert r.status_code == 200
    assert any("fetch failed" in w for w in r.json()["warnings"])


# ── B8 refresh worker pre-fail releases lock ───────────────


def test_b8_init_schema_failure_sets_error_and_releases_lock(tmp_path, monkeypatch):
    feed_ingest._set_state(
        running=False,
        phase=None,
        error=None,
        result=None,
        message=None,
    )
    # ensure lock free
    if feed_ingest._refresh_lock.locked():
        feed_ingest._refresh_lock.release()

    class BoomStore:
        def __init__(self, *a, **k):
            pass

        def init_schema(self):
            raise RuntimeError("schema boom")

        def close(self):
            pass

    monkeypatch.setattr(
        "backend.app.stores.sqlite_store.SqliteStore", BoomStore
    )
    out = feed_ingest.start_refresh_background(
        db_path=tmp_path / "app.db",
        journal_dir=tmp_path / "journal",
    )
    assert out["accepted"] is True
    deadline = time.time() + 3
    while time.time() < deadline:
        st = feed_ingest.refresh_status()
        if st.get("phase") == "error" and not st.get("running"):
            break
        time.sleep(0.05)
    st = feed_ingest.refresh_status()
    assert st["phase"] == "error"
    assert st["running"] is False
    assert "schema boom" in (st.get("error") or "")

    # lock released → can kick again
    out2 = feed_ingest.start_refresh_background(
        db_path=tmp_path / "app.db",
        journal_dir=tmp_path / "journal",
    )
    assert out2["accepted"] is True
    # let worker finish
    time.sleep(0.2)
    if feed_ingest._refresh_lock.locked():
        # wait for second worker
        deadline = time.time() + 2
        while feed_ingest._refresh_lock.locked() and time.time() < deadline:
            time.sleep(0.05)
