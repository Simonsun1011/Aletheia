"""Lazy feed-card summary generation and translation caches."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Callable, Optional

from backend.app.ai import adapter as ai_adapter
from backend.app.ai.guard import guard
from backend.app.feed.language import is_translated_from_english
from backend.app.stores.base import AppStore

CompleteFn = Callable[..., ai_adapter.CompletionResult]
_LANG = re.compile(r"^(?:zh|en|ja)(?:-[A-Za-z0-9]{2,8})?$", re.IGNORECASE)


class FeedSummaryError(Exception):
    def __init__(self, code: str, message: str, status: int = 422):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _text(raw: str) -> str:
    value = (raw or "").strip()
    fence = re.match(r"^```(?:json)?\s*([\s\S]*?)\s*```$", value)
    if fence:
        value = fence.group(1).strip()
    if value.startswith("{"):
        try:
            payload = json.loads(value)
            if isinstance(payload, dict) and payload.get("summary"):
                value = str(payload["summary"]).strip()
        except json.JSONDecodeError:
            pass
    return value


def generate_summary(
    store: AppStore,
    card_id: str,
    *,
    complete_fn: Optional[CompleteFn] = None,
) -> dict:
    card = store.get_feed_card(card_id)
    if card is None:
        raise KeyError(card_id)
    if card.summary:
        return {
            "summary": card.summary,
            "summary_generated_at": card.summary_generated_at,
            "cached": True,
        }
    if not (card.excerpt or "").strip():
        raise FeedSummaryError(
            "EXCERPT_REQUIRED", "card excerpt is empty; summary cannot be generated"
        )
    complete = complete_fn or ai_adapter.complete
    try:
        result = complete(
            prompt_file="summarize_card_v2.md",
            user_content=(
                f"title: {card.title}\n"
                f"source: {card.source or ''}\n"
                f"url: {card.url}\n"
                f"excerpt: {card.excerpt.strip()}\n"
            ),
            purpose="summary",
            budget_mode="interactive",
            timeout_s=90,
        )
    except Exception as error:
        raise FeedSummaryError(
            "LLM_ERROR", f"summary generation failed: {type(error).__name__}", 502
        ) from error
    summary = _text(result.text)
    if not summary:
        raise FeedSummaryError("VALIDATION_ERROR", "AI returned an empty summary")
    checked = guard(summary, ruleset="summary")
    if not checked.ok:
        raise FeedSummaryError(
            "AI_GUARD_VIOLATION",
            "AI summary contains forbidden conclusions",
        )
    if is_translated_from_english(card.title, summary):
        raise FeedSummaryError(
            "SUMMARY_LANGUAGE_MISMATCH",
            "summary must use the source language",
        )
    generated_at = _now_iso()
    stored = store.cache_feed_summary(card_id, summary, generated_at)
    return {
        "summary": stored.summary,
        "summary_generated_at": stored.summary_generated_at,
        "cached": False,
        "warning": result.budget_warning,
    }


def translate_summary(
    store: AppStore,
    card_id: str,
    lang: str,
    *,
    complete_fn: Optional[CompleteFn] = None,
) -> dict:
    normalized = (lang or "").strip().lower()
    if not _LANG.fullmatch(normalized):
        raise FeedSummaryError(
            "INVALID_LANGUAGE", "lang must be a short BCP47 zh/en/ja language tag"
        )
    card = store.get_feed_card(card_id)
    if card is None:
        raise KeyError(card_id)
    if not card.summary:
        raise FeedSummaryError(
            "SUMMARY_REQUIRED", "generate the card summary before translating", 409
        )
    cached = store.get_summary_translation(card_id, normalized)
    if cached is not None:
        return {"lang": normalized, "text": cached, "cached": True}
    complete = complete_fn or ai_adapter.complete
    try:
        result = complete(
            prompt_file="translate_summary_v1.md",
            user_content=f"target_lang: {normalized}\nsummary:\n{card.summary}",
            purpose="summary",
            budget_mode="interactive",
            timeout_s=90,
        )
    except Exception as error:
        raise FeedSummaryError(
            "LLM_ERROR", f"summary translation failed: {type(error).__name__}", 502
        ) from error
    text = _text(result.text)
    checked = guard(text, ruleset="summary")
    if not text or not checked.ok:
        raise FeedSummaryError(
            "AI_GUARD_VIOLATION",
            "translated summary is empty or contains forbidden conclusions",
        )
    store.upsert_summary_translation(card_id, normalized, text)
    return {
        "lang": normalized,
        "text": text,
        "cached": False,
        "warning": result.budget_warning,
    }
