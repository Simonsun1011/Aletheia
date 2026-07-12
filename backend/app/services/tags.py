"""Tag registry: seed topics, validate AI tags, company auto-register."""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Optional

from backend.app.models import Tag
from backend.app.stores.base import AppStore

log = logging.getLogger("aletheia.ai")

# Slice 8 topic seeds v0.9 (coarse layer for filtering). Replaces flat 18-way taxonomy.
# (tag_id, display_en, display_zh)
TOPIC_SEEDS: list[tuple[str, str, str]] = [
    ("compute-chip", "Compute Chips", "算力芯片"),
    ("memory-packaging", "Memory & Advanced Packaging", "存储·先进封装"),
    ("fab-equip", "Fab & Equipment", "制造·设备"),
    ("datacenter-power", "Data Center & Power", "数据中心·电力"),
    ("software-app", "Software & Applications", "软件·应用"),
    ("macro", "Macro", "宏观"),
    ("policy-export", "Policy & Export Controls", "政策·出口管制"),
    ("earnings-guidance", "Earnings & Guidance", "财报·指引"),
    ("low-signal-pr", "Low-signal PR", "低信号·公关"),
]

# Legacy flat taxonomy (Slice 8 pre-v0.9). Retire by DELETE — never status=rejected
# (v0.10: rejected is reserved for human veto only).
LEGACY_TOPIC_IDS: frozenset[str] = frozenset(
    {
        "AI",
        "Semiconductors",
        "Earnings",
        "Guidance",
        "Capex",
        "DataCenter",
        "M&A",
        "Regulation",
        "ExportControls",
        "China",
        "Legal",
        "Product",
        "Analyst",
        "Macro",
        "Rates",
        "Supply-Chain",
        "Buyback",
        "Partnership",
    }
)


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def seed_topic_tags(store: AppStore) -> int:
    """Idempotent: insert/refresh v0.9 coarse topics; DELETE legacy flat seeds.

    v0.10: never mark retired seeds as rejected — that status is human-veto only.
    """
    n = 0
    keep = {tag_id for tag_id, _, _ in TOPIC_SEEDS}
    for tag_id, en, zh in TOPIC_SEEDS:
        existing = store.get_tag(tag_id)
        if existing is None:
            store.upsert_tag(
                Tag(
                    tag_id=tag_id,
                    kind="topic",
                    display_en=en,
                    display_zh=zh,
                    status="active",
                    created_at=_now(),
                )
            )
            n += 1
        elif (
            existing.status != "active"
            or existing.display_en != en
            or existing.display_zh != zh
        ):
            store.upsert_tag(
                Tag(
                    tag_id=tag_id,
                    kind="topic",
                    display_en=en,
                    display_zh=zh,
                    status="active",
                    created_at=existing.created_at,
                )
            )
            n += 1

    for legacy_id in LEGACY_TOPIC_IDS:
        if legacy_id in keep:
            continue
        existing = store.get_tag(legacy_id)
        if existing is not None and existing.kind == "topic":
            store.delete_tag(legacy_id)
            n += 1
    return n


def ensure_company_tag(store: AppStore, ticker: str) -> Tag:
    """Watchlist / relevance objects → company tag (active).

    Re-activates archived company tags when the ticker returns to watchlist.
    """
    tid = (ticker or "").strip().upper()
    if not tid:
        raise ValueError("empty ticker")
    existing = store.get_tag(tid)
    if existing is not None:
        if existing.status != "active" or existing.kind != "company":
            return store.upsert_tag(
                Tag(
                    tag_id=tid,
                    kind="company",
                    display_en=existing.display_en or tid,
                    display_zh=existing.display_zh or tid,
                    status="active",
                    created_at=existing.created_at,
                )
            )
        return existing
    tag = Tag(
        tag_id=tid,
        kind="company",
        display_en=tid,
        display_zh=tid,
        status="active",
        created_at=_now(),
    )
    return store.upsert_tag(tag)


def archive_company_tag(store: AppStore, ticker: str) -> Optional[Tag]:
    """Watchlist archive → company tag status=archived (keep card_tags history)."""
    tid = (ticker or "").strip().upper()
    if not tid:
        return None
    existing = store.get_tag(tid)
    if existing is None:
        return None
    if existing.kind != "company":
        return existing
    if existing.status == "archived":
        return existing
    return store.set_tag_status(tid, "archived")


# Slice 8b: one-time default watchlist when empty (matches former frontend DEFAULT_TICKERS).
DEFAULT_WATCHLIST_SEED: list[tuple[str, str]] = [
    ("NVDA", "slice8b default seed: Nvidia · GPU/CUDA"),
    ("AVGO", "slice8b default seed: Broadcom · 定制ASIC/网络"),
    ("AMD", "slice8b default seed: AMD · GPU/CPU"),
    ("MSFT", "slice8b default seed: Microsoft · 云/AI平台"),
    ("GOOGL", "slice8b default seed: Alphabet · 云/模型"),
    ("TSM", "slice8b default seed: TSMC · 晶圆代工（上游）"),
    ("ASML", "slice8b default seed: ASML · 光刻（上游）"),
    ("AMAT", "slice8b default seed: Applied Materials · 设备（上游）"),
    ("LRCX", "slice8b default seed: Lam Research · 刻蚀沉积（上游）"),
    ("MU", "slice8b default seed: Micron · HBM/存储（上游）"),
]


def seed_default_watchlist_if_empty(store: AppStore) -> int:
    """Idempotent: if no watchlist rows at all, insert DEFAULT_WATCHLIST_SEED.

    Counts any status (incl. archived) so a wiped-active list after user archives
    everything does NOT re-seed. Only true first-run empty DB seeds.
    """
    # Peek via store SQL is sqlite-specific; use list + archived check through raw?
    # AppStore has no count_all; list_watchlist only returns active+shadow.
    # Use get_tag / add only when both active and shadow empty AND no archived —
    # detect via attempting list and a dedicated store method if needed.
    wl = store.list_watchlist()
    if wl.active or wl.shadow:
        return 0
    # If store exposes any archived rows via sqlite, skip seed.
    has_any = getattr(store, "watchlist_has_any_row", None)
    if callable(has_any) and has_any():
        return 0
    from backend.app.models import WatchlistCreate

    n = 0
    for ticker, reason in DEFAULT_WATCHLIST_SEED:
        store.add_watchlist(
            WatchlistCreate(ticker=ticker, add_reason=reason, tier="base")
        )
        n += 1
    return n


def sync_watchlist_company_tags(store: AppStore) -> int:
    """Register all active/shadow watchlist tickers as company tags (active)."""
    wl = store.list_watchlist()
    n = 0
    for item in wl.active + wl.shadow:
        before = store.get_tag(item.ticker.upper())
        ensure_company_tag(store, item.ticker)
        if before is None or before.status != "active":
            n += 1
    return n


def active_topic_ids(store: AppStore) -> list[str]:
    return [
        t.tag_id
        for t in store.list_tags(status="active", kind="topic")
    ]


def active_topics_prompt_lines(store: AppStore) -> str:
    rows = store.list_tags(status="active", kind="topic")
    if not rows:
        return "(none)"
    return "\n".join(
        f"- `{t.tag_id}` · {t.display_zh} · {t.display_en}" for t in rows
    )


def normalize_suggestion_id(raw: str) -> Optional[str]:
    """Turn free-text suggestion into a stable tag_id; None if unusable."""
    s = (raw or "").strip()
    if not s or len(s) > 64:
        return None
    # Prefer Pascal/kebab already; collapse spaces
    s = re.sub(r"\s+", "-", s)
    if not re.fullmatch(r"[A-Za-z0-9&\-]{1,64}", s):
        return None
    return s


def apply_ai_tags(
    store: AppStore,
    card_id: str,
    *,
    tags: list[str],
    suggestions: list[str],
    object_tickers: list[str],
) -> list[str]:
    """Link valid topic tags + company tags; stash suggestions as proposed.

    Invalid registry tags are dropped with WARNING (card still saved).
    Returns accepted topic tag_ids linked.
    """
    allowed = set(active_topic_ids(store))
    accepted: list[str] = []
    for raw in tags[:3]:
        tid = (raw or "").strip()
        if not tid:
            continue
        if tid not in allowed:
            log.warning(
                "AI tag not in active registry — dropped tag=%s card=%s",
                tid,
                card_id,
            )
            continue
        store.link_card_tag(card_id, tid)
        accepted.append(tid)

    for sug in suggestions:
        sid = normalize_suggestion_id(sug)
        if sid is None:
            continue
        if store.get_tag(sid) is not None:
            continue
        store.upsert_tag(
            Tag(
                tag_id=sid,
                kind="topic",
                display_en=sid,
                display_zh=sid,
                status="proposed",
                created_at=_now(),
            )
        )

    for t in object_tickers:
        try:
            ensure_company_tag(store, t)
            store.link_card_tag(card_id, t.strip().upper())
        except ValueError:
            continue

    return accepted
