"""Ticker snapshot endpoints — docs/api-contract.md §4."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from backend.app.config import get_settings
from backend.app.market.ensure import ensure_local_market_data
from backend.app.market.snapshot import build_snapshot
from backend.app.models import TickerSnapshot

router = APIRouter(prefix="/tickers", tags=["tickers"])


@router.get("/{symbol}/snapshot", response_model=TickerSnapshot)
def get_snapshot(symbol: str) -> TickerSnapshot:
    settings = get_settings()
    # Same on-demand path as console — stock page should not require a prior job.
    ensure_warnings = ensure_local_market_data(
        settings.market_db_path, symbol.upper()
    )
    payload = build_snapshot(settings.market_db_path, symbol)
    if payload is None:
        raise HTTPException(
            status_code=404,
            detail={
                "error": {
                    "code": "NOT_FOUND",
                    "message": f"no market data for {symbol.upper()}",
                    "detail": {},
                }
            },
        )
    payload["warnings"] = list(ensure_warnings) + list(payload.get("warnings") or [])
    return TickerSnapshot(**payload)
