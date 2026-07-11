"""Execution endpoints — docs/api-contract.md §8 /executions (v1.9)."""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException, Query, Request, Response
from fastapi.responses import JSONResponse

from backend.app.deps import StoreDep
from backend.app.models import (
    ExecutionCreate,
    ExecutionRecord,
    ExecutionVoidRequest,
    PositionRow,
)
from backend.app.stores.base import ConflictError

router = APIRouter(tags=["executions"])

APPEND_ONLY_BODY = {
    "error": {
        "code": "APPEND_ONLY_VIOLATION",
        "message": "executions rows are immutable; use POST .../void to correct",
        "detail": {},
    }
}


def _err(status: int, code: str, message: str, detail: Optional[dict] = None):
    raise HTTPException(
        status_code=status,
        detail={"error": {"code": code, "message": message, "detail": detail or {}}},
    )


@router.post("/executions", status_code=201, response_model=ExecutionRecord)
def create_execution(body: ExecutionCreate, store: StoreDep) -> ExecutionRecord:
    return store.create_execution(body)


@router.post("/executions/{exec_id}/void")
def void_execution(
    exec_id: str, body: ExecutionVoidRequest, store: StoreDep
):
    try:
        result = store.void_execution(exec_id, replacement=body.replacement)
        out: dict = {"voided": result["voided"].model_dump()}
        if "replacement" in result:
            out["replacement"] = result["replacement"].model_dump()
        return out
    except KeyError:
        _err(404, "NOT_FOUND", f"execution {exec_id} not found")
    except ConflictError as e:
        _err(409, "ALREADY_VOIDED", str(e))


@router.get("/executions", response_model=list[ExecutionRecord])
def list_executions(
    store: StoreDep,
    ticker: Optional[str] = None,
    include_voided: bool = Query(False),
):
    return store.list_executions(ticker=ticker, include_voided=include_voided)


@router.get("/positions", response_model=list[PositionRow])
def list_positions(store: StoreDep):
    return store.list_positions()


@router.api_route("/executions", methods=["PUT", "PATCH", "DELETE"])
@router.api_route("/executions/{path:path}", methods=["PUT", "PATCH", "DELETE"])
def executions_append_only_guard(request: Request, path: str = "") -> Response:
    return JSONResponse(status_code=405, content=APPEND_ONLY_BODY)
