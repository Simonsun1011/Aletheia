"""Cheap deterministic priority score before LLM budget (Slice 3c / DESIGN §3.0.1)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from backend.app.config import REPO_ROOT

try:
    import tomllib
except ModuleNotFoundError:
    import tomli as tomllib  # type: ignore

_DEFAULT = REPO_ROOT / "config" / "priority.toml"

# feed_id / source name → authority bucket
_SEC_MARKERS = ("sec", "edgar", "8-k", "8k")
_TICKER_FEED_IDS = {"yahoo_ticker", "google_news_ticker"}
_WIRE_MARKERS = ("pr newswire", "globenewswire", "prnewswire", "globe newswire")


@dataclass
class PriorityWeights:
    source_sec: float = 40
    source_ticker_news: float = 25
    source_wire: float = 5
    source_other: float = 8
    hit_title_ticker: float = 30
    hit_theme: float = 12
    hit_body_ticker: float = 6
    tier_focus: float = 15
    tier_base: float = 5
    tier_other: float = 0
    event_boost: float = 18
    event_penalty: float = -22
    cluster_per_extra: float = 8
    cluster_cap: float = 24
    fresh_full_hours: float = 24
    fresh_max: float = 10
    event_boost_terms: list[str] = field(default_factory=list)
    event_penalty_terms: list[str] = field(default_factory=list)


@dataclass
class PriorityResult:
    score: float
    reasons: list[str]


def load_priority_weights(path: Optional[Path] = None) -> PriorityWeights:
    p = Path(path) if path else _DEFAULT
    if not p.is_file():
        return PriorityWeights()
    data = tomllib.loads(p.read_text(encoding="utf-8"))
    w = data.get("weights") or {}
    boost = list((data.get("event_boost_terms") or {}).get("terms") or [])
    penalty = list((data.get("event_penalty_terms") or {}).get("terms") or [])
    return PriorityWeights(
        source_sec=float(w.get("source_sec", 40)),
        source_ticker_news=float(w.get("source_ticker_news", 25)),
        source_wire=float(w.get("source_wire", 5)),
        source_other=float(w.get("source_other", 8)),
        hit_title_ticker=float(w.get("hit_title_ticker", 30)),
        hit_theme=float(w.get("hit_theme", 12)),
        hit_body_ticker=float(w.get("hit_body_ticker", 6)),
        tier_focus=float(w.get("tier_focus", 15)),
        tier_base=float(w.get("tier_base", 5)),
        tier_other=float(w.get("tier_other", 0)),
        event_boost=float(w.get("event_boost", 18)),
        event_penalty=float(w.get("event_penalty", -22)),
        cluster_per_extra=float(w.get("cluster_per_extra", 8)),
        cluster_cap=float(w.get("cluster_cap", 24)),
        fresh_full_hours=float(w.get("fresh_full_hours", 24)),
        fresh_max=float(w.get("fresh_max", 10)),
        event_boost_terms=boost,
        event_penalty_terms=penalty,
    )


def _source_bucket(source: str, feed_ids: list[str]) -> str:
    src = (source or "").lower()
    fids = {f.lower() for f in feed_ids}
    if any(m in src for m in _SEC_MARKERS) or any(
        "sec" in f for f in fids
    ):
        return "sec"
    if fids & _TICKER_FEED_IDS or "yahoo" in src or "google news" in src:
        return "ticker"
    if any(m in src for m in _WIRE_MARKERS):
        return "wire"
    return "other"


def score_candidate(
    *,
    title: str,
    content: str,
    source: str,
    feed_ids: list[str],
    objects: list[str],
    url_count: int,
    published_at: Optional[str],
    title_hit_tickers: list[str],
    body_hit_tickers: list[str],
    theme_hit: bool,
    tier_by_ticker: dict[str, str],
    weights: Optional[PriorityWeights] = None,
    now: Optional[datetime] = None,
) -> PriorityResult:
    """Deterministic priority score + human-readable reasons (no LLM)."""
    w = weights or load_priority_weights()
    score = 0.0
    reasons: list[str] = []

    bucket = _source_bucket(source, feed_ids)
    if bucket == "sec":
        score += w.source_sec
        reasons.append("SEC/监管原文")
    elif bucket == "ticker":
        score += w.source_ticker_news
        reasons.append("按标的新闻源")
    elif bucket == "wire":
        score += w.source_wire
        reasons.append("通稿源")
    else:
        score += w.source_other

    if title_hit_tickers:
        score += w.hit_title_ticker
        reasons.append(f"标题命中标的({','.join(title_hit_tickers[:3])})")
    elif theme_hit:
        score += w.hit_theme
        reasons.append("主题词命中")
    elif body_hit_tickers:
        score += w.hit_body_ticker
        reasons.append("正文捎带标的")

    tiers = []
    for t in objects or []:
        tiers.append((tier_by_ticker.get(str(t).upper()) or "base").lower())
    if "focus" in tiers:
        score += w.tier_focus
        reasons.append("focus标的")
    elif "base" in tiers:
        score += w.tier_base
        reasons.append("base标的")

    hay = f"{title or ''}\n{(content or '')[:800]}".lower()
    if any(term.lower() in hay for term in w.event_boost_terms):
        score += w.event_boost
        reasons.append("事件型关键词")
    if any(term.lower() in hay for term in w.event_penalty_terms):
        score += w.event_penalty
        reasons.append("低信号/诉讼词减分")

    extra = max(0, int(url_count) - 1)
    if extra:
        add = min(w.cluster_cap, extra * w.cluster_per_extra)
        score += add
        reasons.append(f"{url_count}源印证")

    # freshness
    ref = now or datetime.now(timezone.utc)
    ts = _parse_ts(published_at)
    if ts is not None:
        hours = max(0.0, (ref - ts).total_seconds() / 3600.0)
        if hours <= w.fresh_full_hours:
            score += w.fresh_max
            reasons.append("24h内")
        else:
            # decay to 0 over next 3 days
            decay = max(0.0, 1.0 - (hours - w.fresh_full_hours) / 72.0)
            add = w.fresh_max * decay
            if add >= 1:
                score += add

    # stable round for display
    score = round(score, 2)
    return PriorityResult(score=score, reasons=reasons)


def _parse_ts(raw: Optional[str]) -> Optional[datetime]:
    if not raw:
        return None
    s = str(raw).strip()
    try:
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except ValueError:
        return None


def reasons_label(reasons: list[str], *, limit: int = 3) -> str:
    return " · ".join(reasons[:limit]) if reasons else ""


def weights_as_dict(w: PriorityWeights) -> dict[str, Any]:
    return {
        "source_sec": w.source_sec,
        "source_ticker_news": w.source_ticker_news,
        "source_wire": w.source_wire,
        "hit_title_ticker": w.hit_title_ticker,
        "hit_theme": w.hit_theme,
        "tier_focus": w.tier_focus,
        "tier_base": w.tier_base,
        "event_boost": w.event_boost,
        "event_penalty": w.event_penalty,
        "cluster_per_extra": w.cluster_per_extra,
        "fresh_max": w.fresh_max,
    }
