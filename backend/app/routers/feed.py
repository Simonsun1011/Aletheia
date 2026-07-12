"""Information-stream feed endpoints — slice-03 + slice-08 filters/tags."""

from __future__ import annotations

import json
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import JSONResponse

from backend.app.config import get_settings
from backend.app.deps import StoreDep
from backend.app.models import FeedCard, FeedCardMarkRequest, NoteCreate
from backend.app.services.changefeed import ChangefeedError, promote_card
from backend.app.services.feed_filter import filter_cards
from backend.app.services.feed_ingest import (
    RefreshInProgressError,
    refresh_feed,
    refresh_status,
    request_refresh_cancel,
    start_refresh_background,
)

router = APIRouter(prefix="/feed", tags=["feed"])

_ALLOWED_DAYS = {1, 3, 7, 30}


def _error(status: int, code: str, message: str, detail: Optional[dict] = None):
    return JSONResponse(
        status_code=status,
        content={"error": {"code": code, "message": message, "detail": detail or {}}},
    )


def _parse_objects(card: FeedCard) -> list:
    try:
        objects = json.loads(card.objects or "[]")
    except json.JSONDecodeError:
        objects = []
    return objects if isinstance(objects, list) else []


def _card_view(card: FeedCard, tags: list) -> dict:
    urls: list[str]
    try:
        parsed = json.loads(card.url)
    except json.JSONDecodeError:
        parsed = None
    if isinstance(parsed, list):
        urls = parsed
    else:
        urls = [card.url]
    objects = _parse_objects(card)
    published = card.published_at or card.fetched_at
    published_fallback = card.published_at is None
    active_tags = [t for t in tags if t.status == "active"]
    topic_tags = [t for t in active_tags if t.kind == "topic"]
    company_tags = [t for t in active_tags if t.kind == "company"]
    unclassified = (len(objects) == 0) and (len(topic_tags) == 0)
    return {
        **card.model_dump(),
        "urls": urls,
        "object_list": objects,
        "published_at_display": published,
        "published_at_fallback": published_fallback,
        "tags": [
            {
                "tag_id": t.tag_id,
                "kind": t.kind,
                "display_en": t.display_en,
                "display_zh": t.display_zh,
                "status": t.status,
            }
            for t in active_tags
        ],
        "unclassified": unclassified,
        "marked": bool(card.marked_at),
    }


def _available_topic_tags(tag_map: dict, cards: list[FeedCard]) -> list[dict]:
    """Facet: topic tags that appear on at least one card in the current result set."""
    seen: dict[str, dict] = {}
    for c in cards:
        for t in tag_map.get(c.id, []):
            if t.status != "active" or t.kind != "topic":
                continue
            if t.tag_id not in seen:
                seen[t.tag_id] = {
                    "tag_id": t.tag_id,
                    "kind": t.kind,
                    "display_en": t.display_en,
                    "display_zh": t.display_zh,
                    "status": t.status,
                }
    return sorted(seen.values(), key=lambda x: x["tag_id"])


@router.get("/filtered")
def list_filtered(store: StoreDep, date: Optional[str] = None):
    items = store.list_filtered_items(batch_date=date)
    batch = date
    if batch is None and items:
        batch = items[0].batch_date
    elif batch is None:
        batch = store.latest_batch_date()
    return {"batch_date": batch, "count": len(items), "items": [i.model_dump() for i in items]}


@router.get("")
def list_feed(
    store: StoreDep,
    date: Optional[str] = None,
    object: Optional[str] = None,
    days: Optional[int] = Query(default=1),
    tag: Optional[str] = None,
):
    """Query accumulated cards only — never triggers fetch/digest."""
    if days is not None and days not in _ALLOWED_DAYS:
        return _error(
            422,
            "VALIDATION_ERROR",
            "days must be 1|3|7|30",
            {"days": days},
        )
    if tag:
        t = store.get_tag(tag)
        if t is None or t.status != "active":
            return {
                "batch_date": date or store.latest_batch_date(),
                "days": days or 1,
                "tag": tag,
                "cards": [],
                "available_tags": [],
                "unclassified_count": 0,
                "filtered_count": 0,
                "purged_on_read": 0,
            }

    cards = store.list_feed_cards(
        batch_date=date,
        object=object,
        days=days,
        tag=tag,
    )
    if days is None or days <= 1:
        cards, purged = filter_cards(store, cards, purge=True)
        batch = date or store.latest_batch_date()
        filtered_n = len(store.list_filtered_items(batch_date=batch)) if batch else 0
    else:
        cards, purged = filter_cards(store, cards, purge=False)
        filtered_n = 0
        batch = None

    tag_map = store.list_tags_for_cards([c.id for c in cards])
    views = [_card_view(c, tag_map.get(c.id, [])) for c in cards]
    unclassified_count = sum(1 for v in views if v.get("unclassified"))
    return {
        "batch_date": batch if (days is None or days <= 1) else None,
        "days": days or 1,
        "tag": tag,
        "cards": views,
        "available_tags": _available_topic_tags(tag_map, cards),
        "unclassified_count": unclassified_count,
        "filtered_count": filtered_n,
        "purged_on_read": purged,
    }


@router.get("/refresh/status")
def refresh_feed_status():
    """Poll background refresh progress (survives SPA tab switches)."""
    return refresh_status()


@router.post("/refresh/cancel")
def refresh_feed_cancel():
    """Best-effort stop of in-flight digest (between LLM items)."""
    return request_refresh_cancel()


@router.post("/refresh")
def refresh_feed_endpoint(
    store: StoreDep,
    date: Optional[str] = None,
    skip_fetch: bool = False,
    background: bool = True,
):
    """User-triggered fetch+digest.

    Default background=True → 202-style accepted + poll GET /feed/refresh/status.
    background=False → synchronous (CLI / tests).

    CONTRACT-ISSUE: api-contract.md lists GET/promote/mark only; add refresh endpoints.
    """
    if background:
        settings = get_settings()
        out = start_refresh_background(
            db_path=settings.app_db_path,
            journal_dir=settings.journal_dir,
            batch_date=date,
            skip_fetch=skip_fetch,
        )
        # 200 with accepted flag — clients poll status
        return out
    try:
        return refresh_feed(store, date, skip_fetch=skip_fetch)
    except RefreshInProgressError as e:
        return _error(409, e.code, str(e))


@router.post("/{card_id}/mark")
def mark_card(card_id: str, body: FeedCardMarkRequest, store: StoreDep):
    """Mark / comment on a card — light corpus trail (not promote/event)."""
    try:
        card = store.mark_feed_card(
            card_id,
            marked=body.marked,
            user_comment=body.user_comment,
        )
    except KeyError:
        raise HTTPException(
            status_code=404,
            detail={
                "error": {
                    "code": "NOT_FOUND",
                    "message": f"feed card {card_id} not found",
                    "detail": {},
                }
            },
        )

    # Also append to quick_notes corpus when a non-empty comment is set
    if body.user_comment is not None and body.user_comment.strip():
        objs = _parse_objects(card)
        obj = str(objs[0]).upper() if objs else None
        store.create_note(
            NoteCreate(
                text=f"[feed:{card_id}] {body.user_comment.strip()}",
                object=obj,
            )
        )

    tags = store.list_card_tags(card_id)
    return _card_view(card, tags)


@router.post("/{card_id}/promote", status_code=201)
def promote(card_id: str, store: StoreDep):
    try:
        event, warn = promote_card(store, card_id)
        body = event.model_dump()
        if warn:
            body["warning"] = warn
        return body
    except KeyError:
        raise HTTPException(
            status_code=404,
            detail={
                "error": {
                    "code": "NOT_FOUND",
                    "message": f"feed card {card_id} not found",
                    "detail": {},
                }
            },
        )
    except ChangefeedError as e:
        return _error(422, e.code, e.message, e.detail)
