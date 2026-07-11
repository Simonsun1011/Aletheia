"""Quick notes endpoints — docs/api-contract.md §3."""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Response
from fastapi.responses import JSONResponse

from backend.app.deps import StoreDep
from backend.app.models import NoteCreate, QuickNote

router = APIRouter(prefix="/notes", tags=["notes"])

APPEND_ONLY_BODY = {
    "error": {
        "code": "APPEND_ONLY_VIOLATION",
        "message": "quick_notes is append-only",
        "detail": {},
    }
}


@router.post("", status_code=201, response_model=QuickNote)
def create_note(body: NoteCreate, store: StoreDep) -> QuickNote:
    return store.create_note(body)


@router.get("", response_model=list[QuickNote])
def list_notes(
    store: StoreDep,
    object: Optional[str] = None,
    limit: Optional[int] = None,
) -> list[QuickNote]:
    return store.list_notes(object=object, limit=limit)


@router.api_route("/{path:path}", methods=["PUT", "PATCH", "DELETE"])
@router.api_route("", methods=["PUT", "PATCH", "DELETE"])
def notes_append_only_guard(path: str = "") -> Response:
    return JSONResponse(status_code=405, content=APPEND_ONLY_BODY)
