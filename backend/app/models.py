"""Pydantic models — field names match docs/api-contract.md and docs/data-model.md."""

from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator, model_validator

JType = Literal["fact", "market_reaction", "causal", "action"]
Direction = Literal["up", "down", "outperform", "underperform", "neutral"]
EntryKind = Literal["original", "revision", "amendment", "retraction", "review"]
ChainStatus = Literal["open", "closed"]
Origin = Literal["journal", "console"]
WatchlistStatus = Literal["active", "archived", "shadow"]
WatchlistTier = Literal["focus", "base", "muted"]


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
    origin: Origin = "journal"

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
    """Append to a chain. kind=revision requires the same field set as JudgmentCreate."""

    kind: Literal["revision", "amendment", "retraction", "review"]
    text: str
    jtype: Optional[JType] = None
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
    def revision_requires_full_field_set(self) -> JudgmentAppend:
        if self.kind != "revision":
            return self
        if self.jtype is None:
            raise ValueError("kind=revision requires jtype (immutable; must match original)")
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
                    f"kind=revision with jtype={self.jtype} requires: {', '.join(missing)}"
                )
        return self


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
    origin: Origin = "journal"


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
    tier: WatchlistTier = "base"


class WatchlistArchive(BaseModel):
    archive_reason: str


class WatchlistTierUpdate(BaseModel):
    tier: WatchlistTier


class WatchlistItem(BaseModel):
    ticker: str
    added_at: str
    add_reason: str
    status: WatchlistStatus
    tier: WatchlistTier = "base"
    archived_at: Optional[str] = None
    archive_reason: Optional[str] = None


class WatchlistResponse(BaseModel):
    active: list[WatchlistItem]
    shadow: list[WatchlistItem]


# ── Ticker snapshot (slice 2) ──────────────────────────────


class SnapshotPrice(BaseModel):
    last: Optional[float] = None
    chg_1d: Optional[float] = None
    chg_5d: Optional[float] = None
    chg_20d: Optional[float] = None
    chg_60d: Optional[float] = None


class SnapshotAnchors(BaseModel):
    sma50: Optional[float] = None
    sma200: Optional[float] = None
    boll_lower: Optional[float] = None
    boll_mid: Optional[float] = None
    vwap20: Optional[float] = None
    low_10d: Optional[float] = None
    low_20d: Optional[float] = None
    low_60d: Optional[float] = None
    high_52w: Optional[float] = None
    drawdown_52w: Optional[float] = None


class SnapshotRisk(BaseModel):
    atr14: Optional[float] = None
    rsi14: Optional[float] = None
    vol_20d_ann: Optional[float] = None


class SnapshotRelative(BaseModel):
    vs_qqq_20d: Optional[float] = None
    vs_qqq_60d: Optional[float] = None
    vs_sector_20d: Optional[float] = None
    vs_sector_60d: Optional[float] = None
    sector_etf: Optional[str] = None


class TickerSnapshot(BaseModel):
    symbol: str
    as_of: str
    price: SnapshotPrice
    anchors: SnapshotAnchors
    risk: SnapshotRisk
    relative: SnapshotRelative
    warnings: list[str] = Field(default_factory=list)


# ── Change Feed (slice 3) ──────────────────────────────────

EventCategory = Literal[
    "company", "financial", "estimates", "flows", "industry", "policy", "macro"
]
EventConfirmation = Literal["confirmed", "speculative"]
# v1.7: user-supplied scope at confirm time (distinct from AI-drafted category)
EventScope = Literal["company", "theme", "macro", "other"]


class ChangefeedExtractRequest(BaseModel):
    raw_text: Optional[str] = None
    url: Optional[str] = None

    @model_validator(mode="after")
    def require_text_or_url(self) -> ChangefeedExtractRequest:
        if not (self.raw_text and self.raw_text.strip()) and not (
            self.url and self.url.strip()
        ):
            raise ValueError("raw_text or url is required")
        return self


class EventRecord(BaseModel):
    id: str
    created_at: str
    object: Optional[str] = None
    event_date: Optional[str] = None
    category: Optional[EventCategory] = None
    source_url: Optional[str] = None
    fact_text: str
    impact_path: Optional[str] = None
    confirmation: Optional[EventConfirmation] = None
    user_confirmed: int = 0
    # v1.7: filled at confirm time by the user; NULL while draft
    scope: Optional[EventScope] = None
    user_comment: Optional[str] = None


class EventConfirmRequest(BaseModel):
    """v1.7: scope is mandatory when confirming an event (missing → 422)."""

    scope: EventScope
    user_comment: Optional[str] = None


class FeedCard(BaseModel):
    id: str
    fetched_at: str
    published_at: Optional[str] = None
    source: Optional[str] = None
    title: str
    url: str
    summary: Optional[str] = None
    objects: Optional[str] = None  # JSON array string
    dedup_group: Optional[str] = None
    batch_date: str


class FilteredItem(BaseModel):
    """Relevance-filtered-out raw item (auditable discard log)."""

    id: str
    fetched_at: str
    source: Optional[str] = None
    title: str
    url: str
    batch_date: str


# ── Narrative scan (slice 4b) ──────────────────────────────


class NarrativePoint(BaseModel):
    # v1.8 (A1/C2): attribution is a structured, non-empty field — never inferred
    # from free-text regex. A bull/bear opinion without a named source is rejected.
    # v1.9.1: date required so时效可见.
    attributed_to: str
    point: str
    source_url: str
    date: str

    @field_validator("attributed_to")
    @classmethod
    def require_attribution(cls, v: str) -> str:
        v = (v or "").strip()
        if not v:
            raise ValueError("attributed_to must be a non-empty source")
        return v

    @field_validator("date")
    @classmethod
    def require_iso_date(cls, v: str) -> str:
        v = (v or "").strip()
        if len(v) < 10:
            raise ValueError("date must be YYYY-MM-DD")
        # accept YYYY-MM-DD prefix
        datetime.strptime(v[:10], "%Y-%m-%d")
        return v[:10]

    @field_validator("source_url")
    @classmethod
    def require_http_url(cls, v: str) -> str:
        v = (v or "").strip()
        if not v.startswith("http://") and not v.startswith("https://"):
            raise ValueError("source_url must be http(s)")
        return v


class NarrativeEvent(BaseModel):
    date: str
    fact: str
    source_url: str

    @field_validator("date")
    @classmethod
    def require_iso_date(cls, v: str) -> str:
        v = (v or "").strip()
        if len(v) < 10:
            raise ValueError("date must be YYYY-MM-DD")
        datetime.strptime(v[:10], "%Y-%m-%d")
        return v[:10]

    @field_validator("source_url")
    @classmethod
    def require_http_url(cls, v: str) -> str:
        v = (v or "").strip()
        if not v.startswith("http://") and not v.startswith("https://"):
            raise ValueError("source_url must be http(s)")
        return v


class NarrativeScanPayload(BaseModel):
    dominant_narrative: str
    bull_points: list[NarrativePoint] = Field(default_factory=list)
    bear_points: list[NarrativePoint] = Field(default_factory=list)
    recent_events: list[NarrativeEvent] = Field(default_factory=list)
    generated_at: Optional[str] = None
    model: Optional[str] = None


class NarrativeScanRecord(BaseModel):
    id: str
    ticker: str
    date: str
    payload: NarrativeScanPayload
    model: str
    created_at: str


# ── Executions (slice 4d / v1.9) ───────────────────────────

Side = Literal["buy", "sell"]


class ExecutionCreate(BaseModel):
    ticker: str
    side: Side
    trade_date: str
    shares: float
    price: float
    fees: Optional[float] = None
    plan_id: Optional[str] = None
    judgment_root_id: Optional[str] = None
    note: Optional[str] = None

    @field_validator("ticker")
    @classmethod
    def upper_ticker(cls, v: str) -> str:
        v = (v or "").strip().upper()
        if not v:
            raise ValueError("ticker required")
        return v

    @field_validator("trade_date")
    @classmethod
    def trade_date_iso(cls, v: str) -> str:
        v = (v or "").strip()
        datetime.strptime(v[:10], "%Y-%m-%d")
        return v[:10]

    @field_validator("shares", "price")
    @classmethod
    def positive(cls, v: float) -> float:
        if v is None or v <= 0:
            raise ValueError("shares and price must be > 0")
        return v

    @field_validator("fees")
    @classmethod
    def fees_nonneg(cls, v: Optional[float]) -> Optional[float]:
        if v is not None and v < 0:
            raise ValueError("fees must be >= 0")
        return v


class ExecutionRecord(BaseModel):
    id: str
    created_at: str
    ticker: str
    side: Side
    trade_date: str
    shares: float
    price: float
    fees: Optional[float] = None
    plan_id: Optional[str] = None
    judgment_root_id: Optional[str] = None
    note: Optional[str] = None
    voided_by: Optional[str] = None


class ExecutionVoidRequest(BaseModel):
    """Optional replacement body — same fields as ExecutionCreate."""

    replacement: Optional[ExecutionCreate] = None


class PositionRow(BaseModel):
    ticker: str
    shares: float
    avg_price: float
    judgment_linked_count: int
