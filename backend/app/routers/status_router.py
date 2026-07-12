"""GET /api/status — deep health check (may touch DB; distinct from /api/health)."""

from __future__ import annotations

import os

from fastapi import APIRouter, Request

router = APIRouter(tags=["status"])


@router.get("/status")
async def get_status(request: Request):
    """System-wide status snapshot.  May be slow / fail under load.
    Use /api/health for lightweight liveness (never touches DB)."""
    from backend.app.services.feed_ingest import refresh_status
    from backend.app.stores.sqlite_store import SqliteStore

    db_ok = True
    journal_mode: str | None = None
    wal = False

    try:
        store = request.app.state.store
        if isinstance(store, SqliteStore):
            row = store._conn.execute("PRAGMA journal_mode").fetchone()
            journal_mode = row[0] if row else None
            wal = journal_mode == "wal"
    except Exception:
        db_ok = False

    llm_configured = bool(os.getenv("MODEL_SUMMARY"))
    search_model_configured = bool(os.getenv("MODEL_SEARCH"))

    return {
        "ok": True,
        "db_ok": db_ok,
        "journal_mode": journal_mode,
        "wal": wal,
        "refresh": refresh_status(),
        "llm_configured": llm_configured,
        "search_model_configured": search_model_configured,
        "version": "0.1.0",
    }
