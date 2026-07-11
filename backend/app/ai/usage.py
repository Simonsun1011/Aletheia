"""LLM usage pricing, budget gate, and Store-backed persistence — Slice 4c / v1.8 A4.

Persistence goes through AppStore (injected). This module never imports a concrete
store class and never opens its own SQLite connection. DDL lives only in SCHEMA_SQL.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, Optional

from ulid import ULID

from backend.app.config import REPO_ROOT

try:
    import tomllib
except ModuleNotFoundError:
    import tomli as tomllib  # type: ignore

if TYPE_CHECKING:
    from backend.app.stores.base import AppStore

log = logging.getLogger("aletheia.ai")

Purpose = Literal["summary", "promote", "scan", "other"]
BudgetMode = Literal["batch", "interactive"]

_store: Optional["AppStore"] = None


class BudgetExceededError(Exception):
    """Batch LLM skipped because monthly budget is exhausted."""

    code = "LLM_BUDGET_EXCEEDED"


def set_store(store: "AppStore") -> None:
    """Inject AppStore at app startup (or test setup). Interface only — no impl import."""
    global _store
    _store = store


def clear_store() -> None:
    global _store
    _store = None


def _require_store() -> "AppStore":
    if _store is None:
        raise RuntimeError(
            "llm usage store not configured; call set_store() at app startup"
        )
    return _store


def prices_path() -> Path:
    return REPO_ROOT / "config" / "llm_prices.toml"


def load_prices(path: Optional[Path] = None) -> dict[str, dict[str, float]]:
    p = path or prices_path()
    if not p.exists():
        return {}
    data = tomllib.loads(p.read_text(encoding="utf-8"))
    raw = data.get("prices") or {}
    out: dict[str, dict[str, float]] = {}
    for model, row in raw.items():
        if isinstance(row, dict):
            out[str(model)] = {
                "input": float(row.get("input_usd_per_mtok") or 0),
                "output": float(row.get("output_usd_per_mtok") or 0),
            }
    return out


def estimate_cost_usd(
    model: str,
    tokens_in: Optional[int],
    tokens_out: Optional[int],
    *,
    prices: Optional[dict[str, dict[str, float]]] = None,
) -> Optional[float]:
    prices = prices if prices is not None else load_prices()
    row = prices.get(model)
    if row is None:
        for k, v in prices.items():
            if model.endswith(k) or k.endswith(model) or model in k:
                row = v
                break
    if row is None:
        return None
    if tokens_in is None and tokens_out is None:
        return None
    tin = float(tokens_in or 0)
    tout = float(tokens_out or 0)
    return (tin * row["input"] + tout * row["output"]) / 1_000_000.0


def monthly_budget_usd() -> Optional[float]:
    raw = (os.getenv("MONTHLY_LLM_BUDGET_USD") or "").strip()
    if not raw:
        return None
    try:
        return float(raw)
    except ValueError:
        return None


def _month_start_iso() -> str:
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-01T00:00:00Z")


def month_to_date_cost_usd() -> float:
    """Sum known costs this UTC month; null costs count as 0."""
    return _require_store().sum_llm_cost_since(_month_start_iso())


def budget_status() -> tuple[bool, Optional[str]]:
    """
    Returns (over_budget, warning_message).
    over_budget True when MONTHLY_LLM_BUDGET_USD set and MTD cost >= budget.
    """
    budget = monthly_budget_usd()
    if budget is None:
        return False, None
    mtd = month_to_date_cost_usd()
    if mtd >= budget:
        msg = (
            f"本月 LLM 预估成本 ${mtd:.4f} 已达/超过预算 "
            f"${budget:.2f}（MONTHLY_LLM_BUDGET_USD）"
        )
        return True, msg
    return False, None


def assert_batch_budget_allows() -> None:
    over, msg = budget_status()
    if over:
        log.error("llm budget exceeded — batch LLM skipped: %s", msg)
        raise BudgetExceededError(msg or "LLM budget exceeded")


def record_usage(
    *,
    model: str,
    purpose: Purpose,
    prompt_version: str,
    tokens_in: Optional[int],
    tokens_out: Optional[int],
    elapsed_ms: float,
) -> dict[str, Any]:
    cost = estimate_cost_usd(model, tokens_in, tokens_out)
    row = {
        "id": str(ULID()),
        "created_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "model": model,
        "purpose": purpose,
        "prompt_version": prompt_version,
        "tokens_in": tokens_in,
        "tokens_out": tokens_out,
        "elapsed_ms": int(round(elapsed_ms)),
        "est_cost_usd": cost,
    }
    _require_store().insert_llm_usage(row)
    log.info(
        "llm_usage id=%s purpose=%s model=%s tokens_in=%s tokens_out=%s cost=%s",
        row["id"],
        purpose,
        model,
        tokens_in,
        tokens_out,
        cost,
    )
    return row


def aggregate_usage(period: Literal["day", "month"] = "month") -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    if period == "day":
        start = now.strftime("%Y-%m-%dT00:00:00Z")
    else:
        start = _month_start_iso()

    detail = _require_store().list_llm_usage_since(start)

    by_model: dict[str, dict[str, Any]] = {}
    by_purpose: dict[str, dict[str, Any]] = {}
    by_day: dict[str, dict[str, Any]] = {}
    total_in = total_out = 0
    total_cost = 0.0
    cost_known = False

    for r in detail:
        tin = int(r["tokens_in"] or 0)
        tout = int(r["tokens_out"] or 0)
        total_in += tin
        total_out += tout
        c = r["est_cost_usd"]
        if c is not None:
            total_cost += float(c)
            cost_known = True

        m = r["model"] or "?"
        by_model.setdefault(
            m,
            {
                "tokens_in": 0,
                "tokens_out": 0,
                "est_cost_usd": 0.0,
                "calls": 0,
                "cost_known": False,
            },
        )
        by_model[m]["tokens_in"] += tin
        by_model[m]["tokens_out"] += tout
        by_model[m]["calls"] += 1
        if c is not None:
            by_model[m]["est_cost_usd"] += float(c)
            by_model[m]["cost_known"] = True

        p = r["purpose"] or "other"
        by_purpose.setdefault(
            p,
            {
                "tokens_in": 0,
                "tokens_out": 0,
                "est_cost_usd": 0.0,
                "calls": 0,
                "cost_known": False,
            },
        )
        by_purpose[p]["tokens_in"] += tin
        by_purpose[p]["tokens_out"] += tout
        by_purpose[p]["calls"] += 1
        if c is not None:
            by_purpose[p]["est_cost_usd"] += float(c)
            by_purpose[p]["cost_known"] = True

        day = (r["created_at"] or "")[:10]
        by_day.setdefault(
            day,
            {
                "tokens_in": 0,
                "tokens_out": 0,
                "est_cost_usd": 0.0,
                "calls": 0,
                "cost_known": False,
            },
        )
        by_day[day]["tokens_in"] += tin
        by_day[day]["tokens_out"] += tout
        by_day[day]["calls"] += 1
        if c is not None:
            by_day[day]["est_cost_usd"] += float(c)
            by_day[day]["cost_known"] = True

    def _finish(d: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
        out = []
        for k, v in sorted(d.items()):
            item = {"key": k, **v}
            if not v.get("cost_known"):
                item["est_cost_usd"] = None
            out.append(item)
        return out

    budget = monthly_budget_usd()
    mtd = month_to_date_cost_usd()
    return {
        "period": period,
        "from": start,
        "calls": len(detail),
        "tokens_in": total_in,
        "tokens_out": total_out,
        "est_cost_usd": total_cost if cost_known else None,
        "month_to_date_cost_usd": mtd,
        "monthly_budget_usd": budget,
        "by_model": _finish(by_model),
        "by_purpose": _finish(by_purpose),
        "by_day": _finish(by_day),
        "recent": detail[:50],
    }
