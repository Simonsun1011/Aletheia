"""FastAPI dependency wiring. Routers depend on AppStore interface only."""

from __future__ import annotations

from typing import Annotated, Iterator

from fastapi import Depends, Request

from backend.app.stores.base import AppStore


def get_store(request: Request) -> Iterator[AppStore]:
    """Yield a per-request SqliteStore (own connection), or lifespan store for
    non-SQLite backends.  Per-request connections eliminate the global serial
    point that caused digest to block all web requests (slice-10 reliability)."""
    lifespan_store: AppStore = request.app.state.store
    from backend.app.stores.sqlite_store import SqliteStore

    if isinstance(lifespan_store, SqliteStore):
        req_store = SqliteStore.for_request(
            lifespan_store.db_path,
            lifespan_store.journal_dir,
            cloud_mirror=lifespan_store._cloud_mirror,
        )
        try:
            yield req_store
        finally:
            try:
                req_store.close()
            except Exception:
                pass
    else:
        yield lifespan_store


StoreDep = Annotated[AppStore, Depends(get_store)]
