"""Change Feed / promote / extract fallback service."""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from typing import Any, Callable, Optional

from ulid import ULID

from backend.app.ai import adapter as ai_adapter
from backend.app.ai.guard import guard
from backend.app.models import ChangefeedExtractRequest, EventRecord, FeedCard
from backend.app.stores.base import AppStore

log = logging.getLogger("aletheia.ai")

PROMOTE_PROMPT = "promote_event_v1.md"
EXTRACT_PROMPT = "extract_event_v1.md"
CATEGORIES = {
    "company",
    "financial",
    "estimates",
    "flows",
    "industry",
    "policy",
    "macro",
}

CompleteFn = Callable[..., ai_adapter.CompletionResult]


class ChangefeedError(Exception):
    def __init__(self, code: str, message: str, detail: Optional[dict] = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.detail = detail or {}


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_json_object(text: str) -> dict[str, Any]:
    text = text.strip()
    fence = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    if fence:
        text = fence.group(1).strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        raise ChangefeedError(
            "VALIDATION_ERROR",
            "AI output is not valid JSON",
            {"parse_error": str(e)},
        ) from e
    if not isinstance(data, dict):
        raise ChangefeedError("VALIDATION_ERROR", "AI output must be a JSON object")
    return data


def _primary_url(url_field: str) -> str:
    try:
        parsed = json.loads(url_field)
        if isinstance(parsed, list) and parsed:
            return str(parsed[0])
    except json.JSONDecodeError:
        pass
    return url_field


def _event_from_ai(
    data: dict[str, Any], *, default_url: Optional[str] = None
) -> EventRecord:
    fact_text = data.get("fact_text")
    if not fact_text or not str(fact_text).strip():
        raise ChangefeedError(
            "VALIDATION_ERROR",
            "AI output missing required field fact_text",
            {"fields": data},
        )
    raw_blob = json.dumps(data, ensure_ascii=False)
    g = guard(raw_blob, ruleset="conclusion")
    if not g.ok:
        raise ChangefeedError(
            "AI_GUARD_VIOLATION",
            "AI output contains forbidden investment conclusions",
            {"matched": g.matched},
        )
    for field in ("fact_text", "impact_path"):
        val = data.get(field)
        if val:
            g2 = guard(str(val), ruleset="conclusion")
            if not g2.ok:
                raise ChangefeedError(
                    "AI_GUARD_VIOLATION",
                    f"AI field {field} contains forbidden conclusions",
                    {"matched": g2.matched},
                )

    category = data.get("category")
    if category not in CATEGORIES:
        category = None
    confirmation = data.get("confirmation")
    if confirmation not in ("confirmed", "speculative"):
        confirmation = "speculative"

    return EventRecord(
        id=str(ULID()),
        created_at=_now_iso(),
        object=(str(data["object"]).strip() if data.get("object") else None),
        event_date=data.get("event_date"),
        category=category,
        source_url=data.get("source_url") or default_url,
        fact_text=str(fact_text).strip(),
        impact_path=(
            str(data["impact_path"]).strip() if data.get("impact_path") else None
        ),
        confirmation=confirmation,
        user_confirmed=0,
    )


def promote_card(
    store: AppStore,
    card_id: str,
    *,
    complete_fn: Optional[CompleteFn] = None,
) -> tuple[EventRecord, Optional[str]]:
    card = store.get_feed_card(card_id)
    if card is None:
        raise KeyError(card_id)
    if not (card.summary or "").strip():
        raise ChangefeedError(
            "SUMMARY_REQUIRED",
            "generate the card summary before promoting it",
        )
    complete = complete_fn or ai_adapter.complete
    user_content = (
        f"title: {card.title}\n"
        f"source: {card.source}\n"
        f"url: {_primary_url(card.url)}\n"
        f"published_at: {card.published_at or card.fetched_at}\n"
        f"objects: {card.objects}\n"
        f"summary: {card.summary}\n"
    )
    result = complete(
        prompt_file=PROMOTE_PROMPT,
        user_content=user_content,
        purpose="promote",
        budget_mode="interactive",
    )
    g = guard(result.text, ruleset="conclusion")
    if not g.ok:
        log.error("guard blocked promote matched=%s", g.matched)
        raise ChangefeedError(
            "AI_GUARD_VIOLATION",
            "AI output contains forbidden investment conclusions",
            {"matched": g.matched},
        )
    data = _parse_json_object(result.text)
    # The model chooses structure only. The factual body is the cached summary,
    # byte-for-byte, and cannot be rewritten by promotion.
    data["fact_text"] = card.summary
    event = _event_from_ai(data, default_url=_primary_url(card.url))
    stored = store.create_event(event)
    return stored, result.budget_warning


def extract_and_store(
    store: AppStore,
    body: ChangefeedExtractRequest,
    *,
    complete_fn: Optional[CompleteFn] = None,
) -> EventRecord:
    """Manual URL/text fallback — same confirm flow as promote."""
    complete = complete_fn or ai_adapter.complete
    parts: list[str] = []
    if body.url and body.url.strip():
        parts.append(f"source_url: {body.url.strip()}")
    if body.raw_text and body.raw_text.strip():
        parts.append("原文：\n" + body.raw_text.strip())
    result = complete(
        prompt_file=EXTRACT_PROMPT,
        user_content="\n\n".join(parts),
        purpose="other",
        budget_mode="interactive",
    )
    g = guard(result.text, ruleset="conclusion")
    if not g.ok:
        raise ChangefeedError(
            "AI_GUARD_VIOLATION",
            "AI output contains forbidden investment conclusions",
            {"matched": g.matched},
        )
    data = _parse_json_object(result.text)
    event = _event_from_ai(
        data, default_url=(body.url.strip() if body.url else None)
    )
    return store.create_event(event)
