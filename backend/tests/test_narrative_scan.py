"""Slice 4b narrative scan + attributed_views integration."""

from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient

from backend.app.ai.adapter import CompletionResult
from backend.app.main import app
from backend.app.services.narrative_scan import NarrativeScanError, run_narrative_scan
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


GOOD_JSON = """
{
  "dominant_narrative": "市场在讨论 AI 资本开支节奏",
  "bull_points": [
    {"attributed_to": "摩根士丹利", "point": "多方论点：市场看多AI资本开支持续性", "source_url": "https://example.com/bull", "date": "2026-07-08"}
  ],
  "bear_points": [
    {"attributed_to": "某空头基金", "point": "空方论点：空头认为估值透支需求", "source_url": "https://example.com/bear", "date": "2026-07-09"}
  ],
  "recent_events": [
    {"date": "2026-07-10", "fact": "某云厂重申年度capex指引", "source_url": "https://example.com/e"}
  ]
}
"""


def test_scan_missing_source_url_soft_empty(store):
    bad = """
    {
      "dominant_narrative": "x",
      "bull_points": [{"attributed_to": "多头", "point": "多方论点：看多开支", "source_url": ""}],
      "bear_points": [],
      "recent_events": []
    }
    """

    def fn(**kwargs):
        return CompletionResult(
            text=bad, model="mock-search", prompt_version="narrative_scan_v1.md", elapsed_ms=1
        )

    row, _, notice = run_narrative_scan(store, "NVDA", force=True, search_fn=fn)
    assert notice == "暂无新叙事"
    assert row.payload.dominant_narrative == "暂无新叙事"
    assert row.payload.bull_points == []


def test_scan_missing_attribution_soft_empty(store):
    """v1.8 A1/C2: missing attributed_to → calm empty, not a scary 422."""
    bad = """
    {
      "dominant_narrative": "x",
      "bull_points": [{"attributed_to": "", "point": "多方论点：看多开支", "source_url": "https://example.com/x"}],
      "bear_points": [],
      "recent_events": []
    }
    """

    def fn(**kwargs):
        return CompletionResult(
            text=bad, model="mock-search", prompt_version="narrative_scan_v1.md", elapsed_ms=1
        )

    row, _, notice = run_narrative_scan(store, "NVDA", force=True, search_fn=fn)
    assert notice == "暂无新叙事"
    assert row.payload.bull_points == []


def test_scan_guard_建议买入_soft_empty_keeps_cache(store):
    """Guard hit on refresh: keep today's good cache; notice=暂无新叙事."""
    good_fn = lambda **kw: CompletionResult(
        text=GOOD_JSON,
        model="mock-search",
        prompt_version="narrative_scan_v1.md",
        elapsed_ms=1,
    )
    good, _, _ = run_narrative_scan(store, "NVDA", force=True, search_fn=good_fn)

    poisoned = """
    {
      "dominant_narrative": "x",
      "bull_points": [
        {"attributed_to": "某券商", "point": "多方论点：建议买入NVDA", "source_url": "https://example.com/x", "date": "2026-07-10"}
      ],
      "bear_points": [],
      "recent_events": []
    }
    """

    def bad_fn(**kwargs):
        return CompletionResult(
            text=poisoned,
            model="mock-search",
            prompt_version="narrative_scan_v1.md",
            elapsed_ms=1,
        )

    row, _, notice = run_narrative_scan(store, "NVDA", force=True, search_fn=bad_fn)
    assert notice == "暂无新叙事"
    assert row.id == good.id
    assert row.payload.bull_points  # previous good content retained



def test_scan_allows_目标价_in_attributed_point_and_recent_event(store):
    """v1.8: 目标价 is conditional — OK in attributed bull point and in facts;
    only 建议买卖/应该 are unconditional on dominant/recent_events."""
    ok_json = """
    {
      "dominant_narrative": "市场讨论资本开支节奏",
      "bull_points": [
        {"attributed_to": "Stifel", "point": "多方论点：分析师上调目标价并维持买入评级", "source_url": "https://example.com/b", "date": "2026-07-10"}
      ],
      "bear_points": [],
      "recent_events": [
        {"date": "2026-07-11", "fact": "Susquehanna将AMAT目标价上调至900美元", "source_url": "https://example.com/e"}
      ]
    }
    """

    def fn(**kwargs):
        return CompletionResult(
            text=ok_json,
            model="mock-search",
            prompt_version="narrative_scan_v1.md",
            elapsed_ms=1,
        )

    row, _, _ = run_narrative_scan(store, "AMAT", force=True, search_fn=fn)
    assert row.payload.bull_points[0].attributed_to == "Stifel"
    assert "目标价" in row.payload.recent_events[0].fact


def test_scan_cache_skips_llm(store):
    calls = {"n": 0}

    def fn(**kwargs):
        calls["n"] += 1
        return CompletionResult(
            text=GOOD_JSON,
            model="mock-search",
            prompt_version="narrative_scan_v1.md",
            elapsed_ms=1,
        )

    a, _, _ = run_narrative_scan(store, "NVDA", force=True, search_fn=fn)
    b, _, _ = run_narrative_scan(store, "NVDA", force=False, search_fn=fn)
    assert calls["n"] == 1
    assert a.id == b.id


def test_scan_empty_arrays_notice(store):
    empty = """
    {
      "dominant_narrative": "",
      "bull_points": [],
      "bear_points": [],
      "recent_events": []
    }
    """

    def fn(**kwargs):
        return CompletionResult(
            text=empty,
            model="mock-search",
            prompt_version="narrative_scan_v1.md",
            elapsed_ms=1,
        )

    row, _, notice = run_narrative_scan(store, "AMAT", force=True, search_fn=fn)
    assert notice == "暂无新叙事"
    assert row.payload.dominant_narrative == "暂无新叙事"


def test_scan_drops_events_older_than_30d(store):
    payload = """
    {
      "dominant_narrative": "开支叙事延续",
      "bull_points": [
        {"attributed_to": "多头", "point": "多方论点：看多开支", "source_url": "https://example.com/b", "date": "2026-07-01"}
      ],
      "bear_points": [],
      "recent_events": [
        {"date": "2025-01-01", "fact": "过旧事件应被丢弃", "source_url": "https://example.com/old"},
        {"date": "2026-07-10", "fact": "近因事件保留", "source_url": "https://example.com/new"}
      ]
    }
    """

    def fn(**kwargs):
        assert "last_earnings_date" in kwargs.get("user_content", "")
        return CompletionResult(
            text=payload,
            model="mock-search",
            prompt_version="narrative_scan_v1.md",
            elapsed_ms=1,
        )

    row, _, notice = run_narrative_scan(
        store, "AMAT", force=True, search_fn=fn, last_earnings_date="2026-05-15"
    )
    assert notice is None
    assert len(row.payload.recent_events) == 1
    assert row.payload.recent_events[0].fact == "近因事件保留"
    assert row.payload.bull_points[0].date == "2026-07-01"


def test_search_model_not_configured(client, monkeypatch):
    monkeypatch.delenv("MODEL_SEARCH", raising=False)
    # ensure not set
    os.environ.pop("MODEL_SEARCH", None)
    r = client.post("/api/console/NVDA/narrative-scan?force=true")
    assert r.status_code == 503
    assert r.json()["error"]["code"] == "SEARCH_MODEL_NOT_CONFIGURED"


def test_scan_http_and_judgment_links_scan_id(client, store, monkeypatch):
    monkeypatch.setenv("MODEL_SEARCH", "openai/mock-search")

    def fn(**kwargs):
        return CompletionResult(
            text=GOOD_JSON,
            model="mock-search",
            prompt_version="narrative_scan_v1.md",
            elapsed_ms=1,
        )

    monkeypatch.setattr(
        "backend.app.services.narrative_scan.ai_adapter.call_with_search", fn
    )
    r = client.post("/api/console/NVDA/narrative-scan?force=true")
    assert r.status_code == 200, r.text
    scan_id = r.json()["id"]

    j = client.post(
        "/api/judgments",
        json={
            "object": "NVDA",
            "jtype": "action",
            "direction": "outperform",
            "horizon_days": 20,
            "confidence": 0.5,
            "text": "这是过度反应，两周内修复",
            "supporting": f"scan_id={scan_id}",
        },
    )
    assert j.status_code == 201
    assert scan_id in j.json()["supporting"]
