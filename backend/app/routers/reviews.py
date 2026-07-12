"""Reviews endpoints — docs/api-contract.md §7."""

from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Query

from backend.app.config import get_settings
from backend.app.deps import StoreDep
from backend.app.services import reviews as reviews_svc
from backend.app.services.settle import settle_chain

router = APIRouter(prefix="/reviews", tags=["reviews"])


@router.get("/due")
def reviews_due(store: StoreDep) -> list[dict[str, Any]]:
    chains = reviews_svc.list_due_chains(store)
    return [c.model_dump() for c in chains]


@router.post("/{root_id}/settle")
def reviews_settle(root_id: str, store: StoreDep) -> dict[str, Any]:
    """
    Compute settle numbers for a chain. Does NOT append a review entry —
    caller writes conclusion text via POST /judgments/{root_id}/entries.
    """
    chain = store.get_chain(root_id)
    if chain is None:
        raise HTTPException(
            status_code=404,
            detail={
                "error": {
                    "code": "NOT_FOUND",
                    "message": f"judgment chain {root_id} not found",
                    "detail": {},
                }
            },
        )
    settings = get_settings()
    draft = settle_chain(chain, settings.market_db_path)
    # Explicit: server never invents conclusion text
    draft["review_text"] = None
    return draft


@router.get("/calibration")
def reviews_calibration(
    store: StoreDep,
    jtype: Optional[str] = Query(default=None),
) -> dict[str, Any]:
    settings = get_settings()
    return reviews_svc.calibration(store, settings.market_db_path, jtype=jtype)
