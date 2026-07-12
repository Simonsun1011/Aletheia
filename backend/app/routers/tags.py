"""Tag registry endpoints — slice 8 / contract v2.1."""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException

from backend.app.deps import StoreDep

router = APIRouter(prefix="/tags", tags=["tags"])


@router.get("")
def list_tags(
    store: StoreDep,
    status: Optional[str] = None,
    kind: Optional[str] = None,
):
    if status is not None and status not in (
        "active",
        "proposed",
        "rejected",
        "archived",
    ):
        raise HTTPException(
            status_code=422,
            detail={
                "error": {
                    "code": "VALIDATION_ERROR",
                    "message": "status must be active|proposed|rejected|archived",
                    "detail": {},
                }
            },
        )
    if kind is not None and kind not in ("company", "topic"):
        raise HTTPException(
            status_code=422,
            detail={
                "error": {
                    "code": "VALIDATION_ERROR",
                    "message": "kind must be company|topic",
                    "detail": {},
                }
            },
        )
    return [t.model_dump() for t in store.list_tags(status=status, kind=kind)]


@router.post("/{tag_id}/approve")
def approve_tag(tag_id: str, store: StoreDep):
    tag = store.get_tag(tag_id)
    if tag is None:
        raise HTTPException(
            status_code=404,
            detail={
                "error": {
                    "code": "NOT_FOUND",
                    "message": f"tag {tag_id} not found",
                    "detail": {},
                }
            },
        )
    if tag.status != "proposed":
        raise HTTPException(
            status_code=422,
            detail={
                "error": {
                    "code": "INVALID_STATUS",
                    "message": f"only proposed tags can be approved (got {tag.status})",
                    "detail": {},
                }
            },
        )
    return store.set_tag_status(tag_id, "active").model_dump()


@router.post("/{tag_id}/reject")
def reject_tag(tag_id: str, store: StoreDep):
    tag = store.get_tag(tag_id)
    if tag is None:
        raise HTTPException(
            status_code=404,
            detail={
                "error": {
                    "code": "NOT_FOUND",
                    "message": f"tag {tag_id} not found",
                    "detail": {},
                }
            },
        )
    if tag.status != "proposed":
        raise HTTPException(
            status_code=422,
            detail={
                "error": {
                    "code": "INVALID_STATUS",
                    "message": f"only proposed tags can be rejected (got {tag.status})",
                    "detail": {},
                }
            },
        )
    return store.set_tag_status(tag_id, "rejected").model_dump()
