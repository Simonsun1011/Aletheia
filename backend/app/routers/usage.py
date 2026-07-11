"""LLM usage aggregation — Slice 4c / contract §8 GET /usage."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Query

from backend.app.ai import usage as llm_usage

router = APIRouter(prefix="/usage", tags=["usage"])


@router.get("")
def get_usage(period: Literal["day", "month"] = Query("month")):
    return llm_usage.aggregate_usage(period)
