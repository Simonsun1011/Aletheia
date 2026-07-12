"""Slice 4c / v1.8 A4 — llm_usage via Store, pricing, budget gate, GET /usage."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from ulid import ULID

from backend.app.ai import adapter as ai_adapter
from backend.app.ai import usage as llm_usage
from backend.app.ai.adapter import CompletionResult
from backend.app.models import FeedCard
from backend.app.services import digest as digest_mod


@pytest.fixture
def usage_wired(store, monkeypatch):
    """Inject Store into usage + adapter hooks (mirrors main lifespan)."""
    monkeypatch.delenv("MONTHLY_LLM_BUDGET_USD", raising=False)
    llm_usage.set_store(store)
    ai_adapter.configure_usage_hooks(
        record_usage=llm_usage.record_usage,
        budget_status=llm_usage.budget_status,
        assert_batch_budget_allows=llm_usage.assert_batch_budget_allows,
    )
    yield store
    ai_adapter.reset_usage_hooks()
    llm_usage.clear_store()


def _seed_cost(store, *, cost: float = 1.0, created_at: str = "2026-07-11T00:00:00Z"):
    store.insert_llm_usage(
        {
            "id": str(ULID()),
            "created_at": created_at,
            "model": "m",
            "purpose": "summary",
            "prompt_version": "x.md",
            "tokens_in": 1,
            "tokens_out": 1,
            "elapsed_ms": 1,
            "est_cost_usd": cost,
        }
    )


def test_record_usage_increments_and_fields(usage_wired, tmp_path, monkeypatch):
    prices = tmp_path / "prices.toml"
    prices.write_text(
        '[prices."mock-model"]\n'
        "input_usd_per_mtok = 1.0\n"
        "output_usd_per_mtok = 2.0\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(llm_usage, "prices_path", lambda: prices)

    before = llm_usage.aggregate_usage("month")["calls"]
    row = llm_usage.record_usage(
        model="mock-model",
        purpose="summary",
        prompt_version="summarize_card_v1.md",
        tokens_in=1000,
        tokens_out=500,
        elapsed_ms=12.3,
    )
    assert row["id"]
    assert row["created_at"]
    assert row["model"] == "mock-model"
    assert row["purpose"] == "summary"
    assert row["prompt_version"] == "summarize_card_v1.md"
    assert row["tokens_in"] == 1000
    assert row["tokens_out"] == 500
    assert row["elapsed_ms"] == 12
    assert abs(row["est_cost_usd"] - 0.002) < 1e-9

    after = llm_usage.aggregate_usage("month")
    assert after["calls"] == before + 1
    assert after["tokens_in"] == 1000
    assert after["tokens_out"] == 500
    assert abs(after["est_cost_usd"] - 0.002) < 1e-9


def test_missing_price_null_cost(usage_wired):
    row = llm_usage.record_usage(
        model="totally-unknown-model-xyz",
        purpose="other",
        prompt_version="x.md",
        tokens_in=100,
        tokens_out=50,
        elapsed_ms=1,
    )
    assert row["est_cost_usd"] is None


def test_adapter_records_on_success(usage_wired, monkeypatch, tmp_path):
    monkeypatch.setenv("MODEL_SUMMARY", "mock-model")
    prices = tmp_path / "prices.toml"
    prices.write_text(
        '[prices."mock-model"]\n'
        "input_usd_per_mtok = 1.0\n"
        "output_usd_per_mtok = 1.0\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(llm_usage, "prices_path", lambda: prices)

    class FakeResp:
        choices = [SimpleNamespace(message=SimpleNamespace(content="ok summary"))]
        usage = SimpleNamespace(prompt_tokens=10, completion_tokens=20)

    import litellm

    monkeypatch.setattr(litellm, "completion", lambda **kw: FakeResp())
    before = llm_usage.aggregate_usage("month")["calls"]
    result = ai_adapter.complete(
        prompt_file="summarize_card_v1.md",
        user_content="hello",
        purpose="summary",
        budget_mode="batch",
    )
    assert result.text == "ok summary"
    assert llm_usage.aggregate_usage("month")["calls"] == before + 1


def test_digest_tag_call_respects_batch_budget_and_keeps_card(
    usage_wired, monkeypatch
):
    store = usage_wired
    monkeypatch.setenv("MONTHLY_LLM_BUDGET_USD", "0.001")
    _seed_cost(store, cost=1.0)

    called = {"n": 0}

    def raise_budget(**kw):
        called["n"] += 1
        assert kw["purpose"] != "summary"
        assert kw["budget_mode"] == "batch"
        llm_usage.assert_batch_budget_allows()
        raise AssertionError("unreachable")

    store.insert_feed_raw(
        {
            "id": "r1",
            "fetched_at": "2026-07-11T12:00:00Z",
            "published_at": "2026-07-11T11:00:00Z",
            "source": "PR Newswire Tech",
            "title": "NVIDIA announces new GPU platform",
            "url": "https://example.com/1",
            "content": "NVIDIA Corporation unveiled a new chip.",
            "objects": '["NVDA"]',
            "batch_date": "2026-07-11",
            "feed_id": "prnewswire_tech",
        }
    )
    stats = digest_mod.digest_batch(
        store, "2026-07-11", complete_fn=raise_budget
    )
    assert stats["fail"] == 0
    assert stats["ok"] == 1
    assert called["n"] == 1
    cards = store.list_feed_cards(batch_date="2026-07-11")
    assert len(cards) == 1
    assert cards[0].summary is None


def test_interactive_budget_warning_on_promote(client, store, monkeypatch):
    # client lifespan already wired set_store(store) + hooks
    monkeypatch.setenv("MONTHLY_LLM_BUDGET_USD", "0.01")
    _seed_cost(store, cost=1.0)

    card = FeedCard(
        id="01USAGEPROMOTE",
        fetched_at="2026-07-11T20:00:00Z",
        published_at="2026-07-11T18:00:00Z",
        source="PR",
        title="AMAT tool",
        url="https://example.com/amat",
        summary="Applied Materials announced a tool.",
        objects='["AMAT"]',
        dedup_group="dg",
        batch_date="2026-07-11",
    )
    store.upsert_feed_card(card)
    payload = {
        "object": "AMAT",
        "event_date": "2026-07-11",
        "category": "company",
        "source_url": "https://example.com/amat",
        "fact_text": "Applied Materials announced a tool.",
        "confirmation": "confirmed",
    }
    import json

    def fake_complete(**kw):
        assert kw.get("budget_mode") == "interactive"
        over, msg = llm_usage.budget_status()
        assert over
        return CompletionResult(
            text=json.dumps(payload),
            model="mock",
            prompt_version="promote_event_v1.md",
            elapsed_ms=1,
            budget_warning=msg,
        )

    monkeypatch.setattr(
        "backend.app.services.changefeed.ai_adapter.complete", fake_complete
    )
    r = client.post("/api/feed/01USAGEPROMOTE/promote")
    assert r.status_code == 201
    body = r.json()
    assert "warning" in body
    assert "预算" in body["warning"] or "budget" in body["warning"].lower()


def test_get_usage_matches_rows(client, store, tmp_path, monkeypatch):
    prices = tmp_path / "prices.toml"
    prices.write_text(
        '[prices."m"]\n'
        "input_usd_per_mtok = 1.0\n"
        "output_usd_per_mtok = 1.0\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(llm_usage, "prices_path", lambda: prices)

    llm_usage.record_usage(
        model="m",
        purpose="summary",
        prompt_version="a.md",
        tokens_in=100,
        tokens_out=50,
        elapsed_ms=5,
    )
    llm_usage.record_usage(
        model="m",
        purpose="promote",
        prompt_version="b.md",
        tokens_in=200,
        tokens_out=100,
        elapsed_ms=6,
    )
    r = client.get("/api/usage?period=month")
    assert r.status_code == 200
    data = r.json()
    assert data["calls"] == 2
    assert data["tokens_in"] == 300
    assert data["tokens_out"] == 150
    assert abs(data["est_cost_usd"] - 0.00045) < 1e-9
    purposes = {x["key"]: x for x in data["by_purpose"]}
    assert purposes["summary"]["calls"] == 1
    assert purposes["promote"]["calls"] == 1
    assert len(data["recent"]) == 2


def test_usage_no_direct_sqlite_connect():
    """A4: usage.py must not open its own SQLite connection or CREATE TABLE."""
    from pathlib import Path

    src = Path("backend/app/ai/usage.py").read_text(encoding="utf-8")
    assert "sqlite3" not in src
    assert "CREATE TABLE" not in src
    assert "set_store" in src


def test_adapter_no_store_import():
    """A4: adapter must not import AppStore / SqliteStore / hold persistence."""
    from pathlib import Path

    src = Path("backend/app/ai/adapter.py").read_text(encoding="utf-8")
    assert "AppStore" not in src
    assert "SqliteStore" not in src
    assert "insert_llm_usage" not in src
    assert "configure_usage_hooks" in src
