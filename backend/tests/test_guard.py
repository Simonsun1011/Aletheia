"""AI guard tests — conclusion blacklist + summary iron law."""

from __future__ import annotations

from pathlib import Path

from backend.app.ai.guard import guard, reset_guard_cache


def setup_function():
    reset_guard_cache()


def test_blocks_建议买入():
    assert not guard("我们认为建议买入该股").ok


def test_blocks_目标价():
    assert not guard("目标价250美元").ok


def test_blocks_strong_buy():
    assert not guard("Analyst issued a Strong Buy rating").ok


def test_allows_factual_summary():
    r = guard("公司公布上季度营收同比增长12%，资本开支指引维持不变。")
    assert r.ok


def test_blocks_fullwidth_strong_buy():
    # A4: pass raw fullwidth — guard must NFKC-normalize internally
    assert not guard("ｓｔｒｏｎｇ　ｂｕｙ").ok


def test_iron_law_blocks_利好存储():
    r = guard("美光宣布HBM4提前量产，利好存储板块", ruleset="summary")
    assert not r.ok
    assert r.ruleset == "summary"


def test_iron_law_allows_hbm4_fact():
    r = guard("美光宣布HBM4提前量产", ruleset="summary")
    assert r.ok


def test_iron_law_does_not_apply_to_user_text_path():
    r = guard("利好存储板块", ruleset="conclusion")
    assert r.ok


def test_attributed_views_allows_多方论点看多():
    r = guard("多方论点：市场看多AI资本开支持续性", ruleset="attributed_views")
    assert r.ok, r.matched


def test_attributed_views_blocks_我看多():
    r = guard("我看多AMAT", ruleset="attributed_views")
    assert not r.ok


def test_attributed_views_always_blocks_建议买入():
    r = guard("多方论点：建议买入该股", ruleset="attributed_views")
    assert not r.ok


def test_attributed_views_blocks_裸目标价():
    r = guard("目标价250美元", ruleset="attributed_views")
    assert not r.ok


def test_attributed_views_allows_归因目标价():
    r = guard(
        "多方论点：分析师上调目标价并维持看多评级",
        ruleset="attributed_views",
    )
    assert r.ok, r.matched


def test_english_buy_sell_not_substring_of_russell():
    """Russell 含字母序列 sell，不得误杀（须词边界）。"""
    r = guard(
        "尽管估值高企且Russell指数调整引发短期抛售。",
        ruleset="attributed_views",
    )
    assert r.ok
    # 无归因主语的裸 sell 仍拦
    assert not guard("We should sell AMAT now", ruleset="attributed_views").ok


def test_summary_allows_buy_points_jargon():
    """Chart-term 'buy points' in factual echo must not trip conclusion buy rule."""
    r = guard(
        "Nvidia and Micron traded near buy points as Dow futures slipped.",
        ruleset="summary",
    )
    assert r.ok, r.matched


def test_summary_still_blocks_recommend_buy():
    assert not guard("Investors should buy NVDA here.", ruleset="summary").ok


def test_attributed_views_exemptions_only_from_config():
    """No exemption strings hard-coded in guard.py."""
    src = Path("backend/app/ai/guard.py").read_text(encoding="utf-8")
    assert "多方论点" not in src
    assert "空方论点" not in src
    assert "attribution_allows" in Path("config/guard_blocklist.toml").read_text(
        encoding="utf-8"
    )
