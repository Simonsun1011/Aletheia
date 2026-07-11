"""Watchlist endpoints — docs/api-contract.md §3."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from backend.app.deps import StoreDep
from backend.app.models import (
    WatchlistArchive,
    WatchlistCreate,
    WatchlistItem,
    WatchlistResponse,
)

router = APIRouter(prefix="/watchlist", tags=["watchlist"])


@router.get("", response_model=WatchlistResponse)
def get_watchlist(store: StoreDep) -> WatchlistResponse:
    return store.list_watchlist()


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
