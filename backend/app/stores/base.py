"""Store interfaces. Business code must depend only on these — never concrete impls."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Optional

from backend.app.models import (
    EventRecord,
    ExecutionCreate,
    ExecutionRecord,
    FeedCard,
    FilteredItem,
    JudgmentAppend,
    JudgmentChain,
    JudgmentCreate,
    JudgmentEntry,
    NarrativeScanRecord,
    NoteCreate,
    PositionRow,
    QuickNote,
    Tag,
    WatchlistArchive,
    WatchlistCreate,
    WatchlistItem,
    WatchlistResponse,
)


class JudgmentStore(ABC):
    """Append-only. No update/delete methods by design."""

    @abstractmethod
    def create_judgment(self, body: JudgmentCreate) -> JudgmentEntry:
        ...

    @abstractmethod
    def append_judgment(self, root_id: str, body: JudgmentAppend) -> JudgmentEntry:
        ...

    @abstractmethod
    def list_chains(
        self,
        *,
        object: Optional[str] = None,
        status: Optional[str] = None,
        jtype: Optional[str] = None,
        origin: Optional[str] = None,
    ) -> list[JudgmentChain]:
        ...

    @abstractmethod
    def get_chain(self, root_id: str) -> Optional[JudgmentChain]:
        ...


class NoteStore(ABC):
    """Append-only. No update/delete methods by design."""

    @abstractmethod
    def create_note(self, body: NoteCreate) -> QuickNote:
        ...

    @abstractmethod
    def list_notes(
        self, *, object: Optional[str] = None, limit: Optional[int] = None
    ) -> list[QuickNote]:
        ...


class WatchlistStore(ABC):
    @abstractmethod
    def list_watchlist(self, *, tier: Optional[str] = None) -> WatchlistResponse:
        ...

    @abstractmethod
    def add_watchlist(self, body: WatchlistCreate) -> WatchlistItem:
        ...

    @abstractmethod
    def archive_watchlist(self, ticker: str, body: WatchlistArchive) -> WatchlistItem:
        ...

    @abstractmethod
    def set_watchlist_tier(self, ticker: str, tier: str) -> WatchlistItem:
        ...


class EventStore(ABC):
    @abstractmethod
    def create_event(self, event: EventRecord) -> EventRecord:
        ...

    @abstractmethod
    def get_event(self, event_id: str) -> Optional[EventRecord]:
        ...

    @abstractmethod
    def confirm_event(
        self,
        event_id: str,
        *,
        scope: Optional[str] = None,
        user_comment: Optional[str] = None,
    ) -> EventRecord:
        ...

    @abstractmethod
    def list_confirmed_events(
        self, *, object: Optional[str] = None
    ) -> list[EventRecord]:
        ...


class FeedStore(ABC):
    @abstractmethod
    def upsert_feed_card(self, card: FeedCard) -> FeedCard:
        ...

    @abstractmethod
    def get_feed_card(self, card_id: str) -> Optional[FeedCard]:
        ...

    @abstractmethod
    def list_feed_cards(
        self,
        *,
        batch_date: Optional[str] = None,
        object: Optional[str] = None,
        days: Optional[int] = None,
        tag: Optional[str] = None,
    ) -> list[FeedCard]:
        ...

    @abstractmethod
    def mark_feed_card(
        self,
        card_id: str,
        *,
        marked: Optional[bool] = None,
        user_comment: Optional[str] = None,
        source_lang: Optional[str] = None,
    ) -> FeedCard:
        ...

    @abstractmethod
    def cache_feed_summary(
        self, card_id: str, summary: str, generated_at: str
    ) -> FeedCard:
        ...

    @abstractmethod
    def get_summary_translation(self, card_id: str, lang: str) -> Optional[str]:
        ...

    @abstractmethod
    def upsert_summary_translation(
        self, card_id: str, lang: str, text: str
    ) -> str:
        ...

    @abstractmethod
    def latest_batch_date(self) -> Optional[str]:
        ...

    @abstractmethod
    def insert_filtered_item(self, item: FilteredItem) -> FilteredItem:
        ...

    @abstractmethod
    def list_filtered_items(
        self, *, batch_date: Optional[str] = None
    ) -> list[FilteredItem]:
        ...

    def delete_feed_raw(self, *, batch_date: Optional[str] = None) -> int:
        """Drop process-buffer raw rows after digest (Slice 3c). Default no-op."""
        return 0


class TagStore(ABC):
    """Controlled tag registry + card_tags (slice 8 / contract v2.1)."""

    @abstractmethod
    def upsert_tag(self, tag: Tag) -> Tag:
        ...

    @abstractmethod
    def get_tag(self, tag_id: str) -> Optional[Tag]:
        ...

    @abstractmethod
    def list_tags(
        self,
        *,
        status: Optional[str] = None,
        kind: Optional[str] = None,
    ) -> list[Tag]:
        ...

    @abstractmethod
    def set_tag_status(self, tag_id: str, status: str) -> Tag:
        ...

    @abstractmethod
    def delete_tag(self, tag_id: str) -> None:
        """Remove tag row + card_tags links (seed retirement only; not user reject)."""
        ...

    @abstractmethod
    def link_card_tag(self, card_id: str, tag_id: str) -> None:
        ...

    @abstractmethod
    def list_card_tags(self, card_id: str) -> list[Tag]:
        ...

    @abstractmethod
    def list_tags_for_cards(self, card_ids: list[str]) -> dict[str, list[Tag]]:
        ...


class NarrativeScanStore(ABC):
    @abstractmethod
    def insert_narrative_scan(self, row: NarrativeScanRecord) -> NarrativeScanRecord:
        ...

    @abstractmethod
    def latest_narrative_scan(
        self, ticker: str, date: str
    ) -> Optional[NarrativeScanRecord]:
        ...

    @abstractmethod
    def get_narrative_scan(self, scan_id: str) -> Optional[NarrativeScanRecord]:
        ...


class LlmUsageStore(ABC):
    """v1.8 A4: llm_usage persistence via Store — no bypass of the repository."""

    @abstractmethod
    def insert_llm_usage(self, row: dict[str, Any]) -> dict[str, Any]:
        ...

    @abstractmethod
    def sum_llm_cost_since(self, since_iso: str) -> float:
        ...

    @abstractmethod
    def list_llm_usage_since(self, since_iso: str) -> list[dict[str, Any]]:
        ...


class ExecutionStore(ABC):
    """Fact-layer fills. Rows immutable except voided_by; no DELETE."""

    @abstractmethod
    def create_execution(self, body: ExecutionCreate) -> ExecutionRecord:
        ...

    @abstractmethod
    def get_execution(self, exec_id: str) -> Optional[ExecutionRecord]:
        ...

    @abstractmethod
    def void_execution(
        self, exec_id: str, *, replacement: Optional[ExecutionCreate] = None
    ) -> dict[str, Any]:
        """Atomically void + optional replacement. Returns {voided, replacement?}."""
        ...

    @abstractmethod
    def list_executions(
        self, *, ticker: Optional[str] = None, include_voided: bool = False
    ) -> list[ExecutionRecord]:
        ...

    @abstractmethod
    def list_positions(self) -> list[PositionRow]:
        ...


class SnapshotStore(ABC):
    """Daily machine snapshots (app.db). Presentational; upsert allowed."""

    @abstractmethod
    def upsert_snapshot(self, date: str, module: str, payload: dict[str, Any]) -> None:
        ...

    @abstractmethod
    def get_snapshot(self, date: str, module: str) -> Optional[dict[str, Any]]:
        ...


class AppStore(
    JudgmentStore,
    NoteStore,
    WatchlistStore,
    EventStore,
    FeedStore,
    TagStore,
    NarrativeScanStore,
    LlmUsageStore,
    ExecutionStore,
    SnapshotStore,
    ABC,
):
    """Combined store used by the app (single SQLite + JSONL backend in v1)."""

    @abstractmethod
    def init_schema(self) -> None:
        ...


class ConflictError(Exception):
    """Raised when appending to a closed judgment chain or voiding twice."""
