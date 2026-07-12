"""Console endpoints — Slice 4 / 4b."""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse

from backend.app.deps import StoreDep
from backend.app.services.console import build_console, last_earnings_date
from backend.app.services.narrative_scan import NarrativeScanError, run_narrative_scan

router = APIRouter(prefix="/console", tags=["console"])


def _err(status: int, code: str, message: str, detail: Optional[dict] = None):
    return JSONResponse(
        status_code=status,
        content={"error": {"code": code, "message": message, "detail": detail or {}}},
    )


@router.get("/{symbol}")
def get_console(
    symbol: str,
    store: StoreDep,
    amount: float = Query(5000, gt=0),
    window: int = Query(5, ge=1, le=20),
    live: bool = Query(
        False,
        description="If true, also hit yfinance for VIX/10Y/fundamentals (slower).",
    ),
):
    return build_console(store, symbol, amount=amount, window=window, live=live)


@router.post("/{symbol}/narrative-scan")
def post_narrative_scan(
    symbol: str,
    store: StoreDep,
    force: bool = Query(False),
):
    try:
        earnings = last_earnings_date(symbol)
        row, warn, notice = run_narrative_scan(
            store, symbol, force=force, last_earnings_date=earnings
        )
        body = row.model_dump()
        if warn:
            body["warning"] = warn
        if notice:
            body["notice"] = notice
        return body
    except NarrativeScanError as e:
        status = 422
        if e.code == "SEARCH_MODEL_NOT_CONFIGURED":
            status = 503
        return _err(status, e.code, e.message, e.detail)


@router.get("/{symbol}/narrative-scan")
def get_narrative_scan(symbol: str, store: StoreDep):
    from datetime import datetime, timezone

    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    row = store.latest_narrative_scan(symbol.upper(), day)
    if row is None:
        return _err(404, "NOT_FOUND", f"no narrative scan for {symbol} today")
    return row.model_dump()
