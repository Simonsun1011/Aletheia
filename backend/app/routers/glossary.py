"""Glossary endpoints — Slice 4."""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from backend.app.deps import StoreDep

router = APIRouter(prefix="/glossary", tags=["glossary"])


@router.get("/{term}")
def glossary_term(term: str, store: StoreDep):
    getter = getattr(store, "get_glossary", None)
    row = getter(term) if callable(getter) else None
    if row is None:
        return JSONResponse(
            status_code=404,
            content={
                "error": {
                    "code": "NOT_FOUND",
                    "message": f"term not found: {term}",
                    "detail": {},
                }
            },
        )
    return {
        "term": row["term"],
        "one_liner": row["one_liner"],
        "full_md": row["full_md"],
        "sources": row.get("sources"),
        "version": row.get("version"),
        "state": row.get("state"),
    }
