"""Glossary endpoints — Slice 4 + 7.

{term} 可传别名，服务层解析到 canonical（slice-07-term-matching）。
"""

from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from backend.app.deps import StoreDep
from backend.app.services import glossary as glossary_svc

router = APIRouter(prefix="/glossary", tags=["glossary"])


class GlossaryStateBody(BaseModel):
    state: str = Field(..., description="unknown | known | saved")


class GlossaryExportBody(BaseModel):
    context: Optional[str] = Field(
        None, description="溯源上下文，如「于 AMAT 操作台技术面遇到」"
    )
    note: Optional[str] = Field(
        None, description="可选：写入「我的笔记」的用户看法"
    )


def _err(status: int, code: str, message: str, detail: Optional[dict] = None):
    return JSONResponse(
        status_code=status,
        content={
            "error": {
                "code": code,
                "message": message,
                "detail": detail or {},
            }
        },
    )


def _term_payload(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "term": row["term"],
        "one_liner": row.get("one_liner"),
        "full_md": row.get("full_md"),
        "sources": row.get("sources"),
        "version": row.get("version"),
        "state": row.get("state"),
        "category": row.get("category") or "",
        "aliases": row.get("aliases") or [],
        "updated_at": row.get("updated_at"),
    }


@router.get("")
def list_glossary(store: StoreDep):
    """List terms for client-side matching (feed Term) + export config flag."""
    lister = getattr(store, "list_glossary", None)
    terms = lister() if callable(lister) else []
    return {
        "terms": [
            {
                "term": t["term"],
                "one_liner": t.get("one_liner"),
                "state": t.get("state"),
                "category": t.get("category") or "",
                "aliases": t.get("aliases") or [],
            }
            for t in terms
        ],
        "export_configured": glossary_svc.obsidian_configured(),
    }


@router.get("/export-status")
def export_status():
    return {"configured": glossary_svc.obsidian_configured()}


@router.post("/reset-known")
def reset_known(store: StoreDep):
    """设置页：将 known 重置为 unknown（saved 不动）。"""
    resetter = getattr(store, "reset_known_glossary", None)
    if not callable(resetter):
        return _err(501, "NOT_IMPLEMENTED", "store does not support glossary reset")
    n = resetter()
    return {"reset": n}


@router.get("/{term}")
def glossary_term(term: str, store: StoreDep):
    getter = getattr(store, "get_glossary", None)
    row = getter(term) if callable(getter) else None
    if row is None:
        return _err(404, "NOT_FOUND", f"term not found: {term}")
    return _term_payload(row)


@router.patch("/{term}")
def patch_glossary_state(term: str, body: GlossaryStateBody, store: StoreDep):
    setter = getattr(store, "set_glossary_state", None)
    if not callable(setter):
        return _err(501, "NOT_IMPLEMENTED", "store does not support glossary state")
    try:
        row = setter(term, body.state)
    except ValueError as e:
        return _err(422, "VALIDATION_ERROR", str(e))
    if row is None:
        return _err(404, "NOT_FOUND", f"term not found: {term}")
    return _term_payload(row)


@router.post("/{term}/export")
def export_glossary(term: str, body: GlossaryExportBody, store: StoreDep):
    exporter = getattr(store, "export_glossary_obsidian", None)
    if not callable(exporter):
        return _err(501, "NOT_IMPLEMENTED", "store does not support obsidian export")
    if not glossary_svc.obsidian_configured():
        return _err(
            503,
            "OBSIDIAN_NOT_CONFIGURED",
            "OBSIDIAN_EXPORT_DIR is not set; export button should be disabled",
        )
    try:
        result = exporter(term, context=body.context, note=body.note)
    except KeyError:
        return _err(404, "NOT_FOUND", f"term not found: {term}")
    except Exception as e:
        return _err(500, "EXPORT_FAILED", str(e))
    return result
