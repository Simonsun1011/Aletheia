"""Judgment endpoints — docs/api-contract.md §2."""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException, Response
from fastapi.responses import JSONResponse

from backend.app.deps import StoreDep
from backend.app.models import JudgmentAppend, JudgmentCreate, JudgmentEntry
from backend.app.stores.base import ConflictError

router = APIRouter(prefix="/judgments", tags=["judgments"])

APPEND_ONLY_BODY = {
    "error": {
        "code": "APPEND_ONLY_VIOLATION",
        "message": "judgment_entries is append-only; use POST .../entries to amend",
        "detail": {},
    }
}


def _append_only_response() -> JSONResponse:
    return JSONResponse(status_code=405, content=APPEND_ONLY_BODY)


@router.post("", status_code=201, response_model=JudgmentEntry)
def create_judgment(body: JudgmentCreate, store: StoreDep) -> JudgmentEntry:
    return store.create_judgment(body)


@router.post("/{root_id}/entries", status_code=201, response_model=JudgmentEntry)
def append_entry(
    root_id: str, body: JudgmentAppend, store: StoreDep
) -> JudgmentEntry:
    try:
        return store.append_judgment(root_id, body)
    except KeyError:
        raise HTTPException(
            status_code=404,
            detail={
                "error": {
                    "code": "NOT_FOUND",
                    "message": f"judgment chain {root_id} not found",
                    "detail": {},
                }
            },
        )
    except ConflictError as e:
        raise HTTPException(
            status_code=409,
            detail={
                "error": {
                    "code": "CHAIN_CLOSED",
                    "message": str(e),
                    "detail": {},
                }
            },
        )


@router.get("")
def list_judgments(
    store: StoreDep,
    object: Optional[str] = None,
    status: Optional[str] = None,
    jtype: Optional[str] = None,
):
    return store.list_chains(object=object, status=status, jtype=jtype)


@router.get("/{root_id}")
def get_judgment(root_id: str, store: StoreDep):
    chain = store.get_chain(root_id)
    if chain is None:
        raise HTTPException(
            status_code=404,
            detail={
                "error": {
                    "code": "NOT_FOUND",
                    "message": f"judgment chain {root_id} not found",
                    "detail": {},
                }
            },
        )
    return chain


@router.api_route("/{path:path}", methods=["PUT", "PATCH", "DELETE"])
@router.api_route("", methods=["PUT", "PATCH", "DELETE"])
def judgments_append_only_guard(path: str = "") -> Response:
    return _append_only_response()
