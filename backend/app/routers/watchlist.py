"""Watchlist endpoints — docs/api-contract.md §3 (incl. v1.1 tier)."""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException

from backend.app.deps import StoreDep
from backend.app.models import (
    WatchlistArchive,
    WatchlistCreate,
    WatchlistItem,
    WatchlistResponse,
    WatchlistTierUpdate,
)
from backend.app.services.tags import seed_default_watchlist_if_empty

router = APIRouter(prefix="/watchlist", tags=["watchlist"])


@router.get("", response_model=WatchlistResponse)
def get_watchlist(
    store: StoreDep, tier: Optional[str] = None
) -> WatchlistResponse:
    # Slice 8b: first-run empty DB → one-time DEFAULT seed (idempotent)
    seed_default_watchlist_if_empty(store)
    return store.list_watchlist(tier=tier)


@router.post("", status_code=201, response_model=WatchlistItem)
def add_watchlist(body: WatchlistCreate, store: StoreDep) -> WatchlistItem:
    return store.add_watchlist(body)


@router.post("/{ticker}/archive", response_model=WatchlistItem)
def archive_watchlist(
    ticker: str, body: WatchlistArchive, store: StoreDep
) -> WatchlistItem:
    try:
        return store.archive_watchlist(ticker, body)
    except KeyError:
        raise HTTPException(
            status_code=404,
            detail={
                "error": {
                    "code": "NOT_FOUND",
                    "message": f"ticker {ticker} not on watchlist",
                    "detail": {},
                }
            },
        )


@router.post("/{ticker}/tier", response_model=WatchlistItem)
def set_watchlist_tier(
    ticker: str, body: WatchlistTierUpdate, store: StoreDep
) -> WatchlistItem:
    try:
        return store.set_watchlist_tier(ticker, body.tier)
    except KeyError:
        raise HTTPException(
            status_code=404,
            detail={
                "error": {
                    "code": "NOT_FOUND",
                    "message": f"ticker {ticker} not on watchlist",
                    "detail": {},
                }
            },
        )
