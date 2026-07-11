"""Change Feed endpoints — confirm + manual extract fallback."""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse

from backend.app.deps import StoreDep
from backend.app.models import (
    ChangefeedExtractRequest,
    EventConfirmRequest,
    EventRecord,
)
from backend.app.services.changefeed import ChangefeedError, extract_and_store

router = APIRouter(prefix="/changefeed", tags=["changefeed"])


def _error(status: int, code: str, message: str, detail: Optional[dict] = None):
    return JSONResponse(
        status_code=status,
        content={"error": {"code": code, "message": message, "detail": detail or {}}},
    )


@router.post("/extract", status_code=201, response_model=EventRecord)
def extract(body: ChangefeedExtractRequest, store: StoreDep):
    """Manual paste/URL fallback (not the primary Slice 3 path)."""
    try:
        return extract_and_store(store, body)
    except ChangefeedError as e:
        return _error(422, e.code, e.message, e.detail)
    except Exception as e:
        return _error(422, "AI_ERROR", str(e))


@router.post("/{event_id}/confirm", response_model=EventRecord)
def confirm(event_id: str, body: EventConfirmRequest, store: StoreDep):
    """v1.7: scope is mandatory; a missing scope yields 422 (pydantic)."""
    try:
        return store.confirm_event(
            event_id, scope=body.scope, user_comment=body.user_comment
        )
    except KeyError:
        raise HTTPException(
            status_code=404,
            detail={
                "error": {
                    "code": "NOT_FOUND",
                    "message": f"event {event_id} not found",
                    "detail": {},
                }
            },
        )


@router.get("", response_model=list[EventRecord])
def list_events(store: StoreDep, object: Optional[str] = None):
    return store.list_confirmed_events(object=object)
