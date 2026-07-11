"""FastAPI dependency wiring. Routers depend on AppStore interface only."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Request

from backend.app.stores.base import AppStore


def get_store(request: Request) -> AppStore:
    store: AppStore = request.app.state.store
    return store


StoreDep = Annotated[AppStore, Depends(get_store)]
