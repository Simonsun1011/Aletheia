"""Pydantic models — field names match docs/api-contract.md and docs/data-model.md."""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator, model_validator

JType = Literal["fact", "market_reaction", "causal", "action"]
Direction = Literal["up", "down", "outperform", "underperform", "neutral"]
EntryKind = Literal["original", "amendment", "retraction", "review"]
ChainStatus = Literal["open", "closed"]
WatchlistStatus = Literal["active", "archived", "shadow"]


class ErrorBody(BaseModel):
    code: str
    message: str
    detail: dict = Field(default_factory=dict)


class ErrorResponse(BaseModel):
    error: ErrorBody


# ── Judgments ──────────────────────────────────────────────


class JudgmentCreate(BaseModel):
    object: str
    jtype: JType
    text: str
    direction: Optional[Direction] = None
    horizon_days: Optional[int] = None
    confidence: Optional[float] = None
    supporting: Optional[str] = None
    counter: Optional[str] = None
    falsification: Optional[str] = None
    pre_view: Optional[str] = None
    post_view: Optional[str] = None

    @field_validator("confidence")
    @classmethod
    def confidence_range(cls, v: Optional[float]) -> Optional[float]:
        if v is not None and not (0.0 <= v <= 1.0):
            raise ValueError("confidence must be in [0, 1]")
        return v

    @field_validator("horizon_days")
    @classmethod
    def horizon_range(cls, v: Optional[int]) -> Optional[int]:
        if v is not None and not (5 <= v <= 120):
            raise ValueError("horizon_days must be in [5, 120]")
        return v

    @model_validator(mode="after")
    def require_fields_for_scored_types(self) -> JudgmentCreate:
        if self.jtype in ("market_reaction", "action"):
            missing = []
            if self.direction is None:
                missing.append("direction")
            if self.horizon_days is None:
                missing.append("horizon_days")
            if self.confidence is None:
                missing.append("confidence")
            if missing:
                raise ValueError(
                    f"jtype={self.jtype} requires: {', '.join(missing)}"
                )
        return self


class JudgmentAppend(BaseModel):
    kind: Literal["amendment", "retraction", "review"]
    text: str


class JudgmentEntry(BaseModel):
    id: str
    root_id: str
    kind: EntryKind
    created_at: str
    object: str
    jtype: Optional[JType] = None
    direction: Optional[Direction] = None
    horizon_days: Optional[int] = None
    confidence: Optional[float] = None
    text: str
    supporting: Optional[str] = None
    counter: Optional[str] = None
    falsification: Optional[str] = None
    pre_view: Optional[str] = None
    post_view: Optional[str] = None
    snapshot_date: Optional[str] = None
    expires_on: Optional[str] = None
    status: ChainStatus = "open"


class JudgmentChain(BaseModel):
    root_id: str
    object: str
    status: ChainStatus
    entries: list[JudgmentEntry]


# ── Notes ──────────────────────────────────────────────────


class NoteCreate(BaseModel):
    text: str
    object: Optional[str] = None


class QuickNote(BaseModel):
    id: str
    created_at: str
    text: str
    object: Optional[str] = None


# ── Watchlist ──────────────────────────────────────────────


class WatchlistCreate(BaseModel):
    ticker: str
    add_reason: str


class WatchlistArchive(BaseModel):
    archive_reason: str


class WatchlistItem(BaseModel):
    ticker: str
    added_at: str
    add_reason: str
    status: WatchlistStatus
    archived_at: Optional[str] = None
    archive_reason: Optional[str] = None


class WatchlistResponse(BaseModel):
    active: list[WatchlistItem]
    shadow: list[WatchlistItem]
