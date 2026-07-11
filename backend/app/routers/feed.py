"""Information-stream feed endpoints — slice-03-infostream-mvp."""

from __future__ import annotations

import json
from typing import Optional

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse

from backend.app.deps import StoreDep
from backend.app.models import EventRecord, FeedCard
from backend.app.services.changefeed import ChangefeedError, promote_card
from backend.app.services.feed_filter import filter_cards

router = APIRouter(prefix="/feed", tags=["feed"])


def _error(status: int, code: str, message: str, detail: Optional[dict] = None):
    return JSONResponse(
        status_code=status,
        content={"error": {"code": code, "message": message, "detail": detail or {}}},
    )


def _card_view(card: FeedCard) -> dict:
    urls: list[str]
    try:
        parsed = json.loads(card.url)
        urls = parsed if isinstance(parsed, list) else [card.url]
    except json.JSONDecodeError:
        urls = [card.url]
    try:
        objects = json.loads(card.objects or "[]")
    except json.JSONDecodeError:
        objects = []
    published = card.published_at or card.fetched_at
    published_fallback = card.published_at is None
    return {
        **card.model_dump(),
        "urls": urls,
        "object_list": objects,
        "published_at_display": published,
        "published_at_fallback": published_fallback,
    }


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
):
    batch = date or store.latest_batch_date()
    cards = store.list_feed_cards(batch_date=batch, object=object)
    # Re-apply relevance to already-stored cards; purge noise from DB
    cards, purged = filter_cards(store, cards, purge=True)
    filtered_n = len(store.list_filtered_items(batch_date=batch)) if batch else 0
    return {
        "batch_date": batch,
        "cards": [_card_view(c) for c in cards],
        "filtered_count": filtered_n,
        "purged_on_read": purged,
    }


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
