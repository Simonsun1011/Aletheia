"""Review/due/calibration orchestration (api-contract.md §7)."""

from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Optional

from backend.app.models import JudgmentChain
from backend.app.services.settle import (
    STAT_WARNING,
    confidence_bucket,
    current_version,
    direction_hit,
    settle_chain,
)
from backend.app.stores.base import AppStore


def _today_utc() -> date:
    return datetime.now(timezone.utc).date()


def list_due_chains(store: AppStore, *, today: Optional[date] = None) -> list[JudgmentChain]:
    """Open chains whose current-version expires_on is on or before today (UTC)."""
    day = today or _today_utc()
    day_s = day.isoformat()
    due: list[JudgmentChain] = []
    for chain in store.list_chains(status="open"):
        cur = current_version(chain)
        if not cur.expires_on:
            continue
        if cur.expires_on[:10] <= day_s:
            due.append(chain)
    return due


def calibration(
    store: AppStore,
    market_db: Path,
    *,
    jtype: Optional[str] = None,
) -> dict[str, Any]:
    """
    Hit rate + confidence buckets for closed (reviewed) chains.
    Numbers only; warning string when N<20. No evaluative field names.
    """
    chains = store.list_chains(status="closed", jtype=jtype)
    hits = 0
    scored = 0
    buckets: dict[str, dict[str, int]] = {}

    for chain in chains:
        cur = current_version(chain)
        if jtype and cur.jtype != jtype:
            continue
        settle = settle_chain(chain, market_db)
        hit = direction_hit(cur.direction, settle)
        if hit is None:
            continue
        scored += 1
        if hit:
            hits += 1
        b = confidence_bucket(cur.confidence)
        if b:
            row = buckets.setdefault(b, {"n": 0, "hits": 0})
            row["n"] += 1
            if hit:
                row["hits"] += 1

    n = scored
    hit_rate = (hits / n) if n > 0 else None
    conf_buckets = []
    for key in sorted(buckets.keys()):
        row = buckets[key]
        bn = row["n"]
        conf_buckets.append(
            {
                "bucket": key,
                "n": bn,
                "hit_rate": (row["hits"] / bn) if bn > 0 else None,
            }
        )

    out: dict[str, Any] = {
        "jtype": jtype,
        "n": n,
        "hits": hits,
        "hit_rate": hit_rate,
        "confidence_buckets": conf_buckets,
    }
    if n < 20:
        out["warning"] = STAT_WARNING
    return out
