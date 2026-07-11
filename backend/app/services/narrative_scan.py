"""AI independent narrative scan (console zone B) — Slice 4b."""

from __future__ import annotations

import json
import logging
import os
import re
from datetime import datetime, timezone
from typing import Any, Callable, Optional

from ulid import ULID

from backend.app.ai import adapter as ai_adapter
from backend.app.ai.guard import guard_attributed_field
from backend.app.models import (
    NarrativeScanPayload,
    NarrativeScanRecord,
)
from backend.app.stores.base import AppStore

log = logging.getLogger("aletheia.ai")

PROMPT = "narrative_scan_v1.md"
EMPTY_NARRATIVE = "暂无新叙事"
RECENT_EVENTS_MAX_DAYS = 30
SearchFn = Callable[..., ai_adapter.CompletionResult]


class NarrativeScanError(Exception):
    def __init__(self, code: str, message: str, detail: Optional[dict] = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.detail = detail or {}


def search_model_configured() -> bool:
    return bool((os.getenv("MODEL_SEARCH") or "").strip())


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _extract_json(text: str) -> dict[str, Any]:
    raw = (text or "").strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        m = re.search(r"\{[\s\S]*\}", raw)
        if not m:
            raise NarrativeScanError(
                "AI_PARSE_ERROR", "narrative scan output is not JSON"
            )
        return json.loads(m.group(0))


def _empty_payload(model: Optional[str] = None) -> NarrativeScanPayload:
    return NarrativeScanPayload(
        dominant_narrative=EMPTY_NARRATIVE,
        bull_points=[],
        bear_points=[],
        recent_events=[],
        generated_at=_now(),
        model=model,
    )


def _has_content(payload: NarrativeScanPayload) -> bool:
    if payload.bull_points or payload.bear_points or payload.recent_events:
        return True
    dom = (payload.dominant_narrative or "").strip()
    return bool(dom) and dom != EMPTY_NARRATIVE


def _guard_chunk(text: str, *, attributed: bool) -> None:
    r = guard_attributed_field(text, attributed=attributed)
    if not r.ok:
        log.error(
            "narrative scan guard blocked matched=%s text=%s",
            r.matched,
            text[:200],
        )
        raise NarrativeScanError(
            "AI_GUARD_VIOLATION",
            "narrative scan failed attributed_views guard",
            {"matched": r.matched, "text": text[:200]},
        )


def _guard_payload(payload: NarrativeScanPayload) -> None:
    # v1.8 (A1/C2) — contract §8 field rules:
    # - dominant_narrative: only always_block (建议买卖/应该)
    # - bull/bear: opinion without attributed_to → fail; with attribution,
    #   conditional terms (看多/看空/目标价) may pass
    # - recent_events.fact: only always_block (same as dominant). Reporting an
    #   analyst PT move as a fact must not fail the whole scan — over-blocking
    #   caused the 00:48 incident (matched=['目标价'] on recent_events).
    _guard_chunk(payload.dominant_narrative, attributed=True)
    for p in payload.bull_points + payload.bear_points:
        attributed = bool(p.attributed_to and p.attributed_to.strip())
        _guard_chunk(p.point, attributed=attributed)
    for e in payload.recent_events:
        _guard_chunk(e.fact, attributed=True)


def _soft_empty_result(
    store: AppStore,
    ticker: str,
    day: str,
    *,
    force: bool,
    model: Optional[str],
    err: Optional[NarrativeScanError],
) -> tuple[NarrativeScanRecord, Optional[str], str]:
    """No usable narrative → calm empty state, not a user-facing hard error."""
    log.warning(
        "narrative scan soft-empty ticker=%s force=%s err=%s",
        ticker,
        force,
        err.code if err else None,
    )
    if force:
        cached = store.latest_narrative_scan(ticker, day)
        if cached is not None:
            return cached, None, EMPTY_NARRATIVE
    row = NarrativeScanRecord(
        id=str(ULID()),
        ticker=ticker,
        date=day,
        payload=_empty_payload(model),
        model=model or "none",
        created_at=_now(),
    )
    store.insert_narrative_scan(row)
    return row, None, EMPTY_NARRATIVE


def _filter_recent_events(
    events: list,
) -> list:
    """v1.9.1: keep only events within the last 30 days."""
    from datetime import date, datetime, timedelta

    cutoff = date.today() - timedelta(days=RECENT_EVENTS_MAX_DAYS)
    kept = []
    for e in events:
        try:
            d = datetime.strptime(str(e.date)[:10], "%Y-%m-%d").date()
        except Exception:
            log.warning("drop recent_event with bad date=%s", getattr(e, "date", None))
            continue
        if d < cutoff:
            log.info("drop recent_event outside 30d date=%s", d.isoformat())
            continue
        kept.append(e)
    return kept


def run_narrative_scan(
    store: AppStore,
    ticker: str,
    *,
    force: bool = False,
    search_fn: Optional[SearchFn] = None,
    last_earnings_date: Optional[str] = None,
) -> tuple[NarrativeScanRecord, Optional[str], Optional[str]]:
    """
    Returns (record, budget_warning, notice).
    notice is set to EMPTY_NARRATIVE when there is nothing new to show —
    callers should treat that as a calm empty state, not an error.
    """
    ticker = ticker.upper()
    day = _today()
    if not force:
        cached = store.latest_narrative_scan(ticker, day)
        if cached is not None:
            log.info("narrative scan cache hit ticker=%s date=%s", ticker, day)
            notice = (
                EMPTY_NARRATIVE
                if not _has_content(cached.payload)
                else None
            )
            return cached, None, notice

    if not search_model_configured() and search_fn is None:
        raise NarrativeScanError(
            ai_adapter.SearchModelNotConfigured.code,
            "MODEL_SEARCH is not configured",
        )

    earnings = (last_earnings_date or "").strip() or "unknown"
    fn = search_fn or ai_adapter.call_with_search
    user_content = (
        f"ticker: {ticker}\n"
        f"last_earnings_date: {earnings}\n"
        "Focus dominant_narrative and bull/bear on narratives since last earnings; "
        f"recent_events only within the last {RECENT_EVENTS_MAX_DAYS} days. "
        "Every bull/bear point and recent_event must include date (YYYY-MM-DD)."
    )
    retry_hint = (
        "\n\nIMPORTANT: Rewrite without any of: 目标价, price target, PT, "
        "建议买入, 建议卖出, buy/sell recommendations, or position sizing."
        "\nEvery bull_points/bear_points item needs attributed_to, point, source_url, date."
        "\nIf there is no reliable new narrative, return empty arrays and "
        f'set dominant_narrative to "{EMPTY_NARRATIVE}".'
    )

    last_err: Optional[NarrativeScanError] = None
    result = None
    payload = None
    for attempt in range(2):
        try:
            result = fn(
                prompt_file=PROMPT,
                user_content=user_content + (retry_hint if attempt else ""),
                purpose="scan",
                budget_mode="interactive",
            )
        except ai_adapter.SearchModelNotConfigured as e:
            raise NarrativeScanError(e.code, str(e)) from e
        except ai_adapter.AdapterError as e:
            raise NarrativeScanError("AI_ADAPTER_ERROR", str(e)) from e

        try:
            data = _extract_json(result.text)
            payload = NarrativeScanPayload.model_validate(data)
            payload.recent_events = _filter_recent_events(payload.recent_events)
        except NarrativeScanError as e:
            last_err = e
            continue
        except Exception as e:
            last_err = NarrativeScanError(
                "AI_PARSE_ERROR", f"invalid narrative scan schema: {e}"
            )
            continue

        for p in payload.bull_points + payload.bear_points:
            if not p.source_url:
                last_err = NarrativeScanError(
                    "VALIDATION_ERROR", "bull/bear point missing source_url"
                )
                break
        else:
            for e in payload.recent_events:
                if not e.source_url:
                    last_err = NarrativeScanError(
                        "VALIDATION_ERROR", "recent_event missing source_url"
                    )
                    break
            else:
                try:
                    payload.generated_at = _now()
                    payload.model = result.model
                    _guard_payload(payload)
                    last_err = None
                    break
                except NarrativeScanError as e:
                    last_err = e
                    log.warning(
                        "narrative scan attempt %s guard/parse fail: %s",
                        attempt + 1,
                        e.code,
                    )
                    continue
            continue
        continue

    if last_err is not None or result is None or payload is None:
        return _soft_empty_result(
            store,
            ticker,
            day,
            force=force,
            model=getattr(result, "model", None),
            err=last_err,
        )

    notice: Optional[str] = None
    if not _has_content(payload):
        payload.dominant_narrative = EMPTY_NARRATIVE
        notice = EMPTY_NARRATIVE

    row = NarrativeScanRecord(
        id=str(ULID()),
        ticker=ticker,
        date=day,
        payload=payload,
        model=result.model,
        created_at=_now(),
    )
    store.insert_narrative_scan(row)
    log.info(
        "narrative scan saved id=%s ticker=%s model=%s prompt=%s notice=%s earnings=%s",
        row.id,
        ticker,
        row.model,
        PROMPT,
        notice,
        earnings,
    )
    return row, result.budget_warning, notice
