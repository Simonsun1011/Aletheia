"""Firestore AppStore stub — architecture §3 second implementation (not wired).

Selecting ALETHEIA_STORE=firestore will construct this class; methods raise
StoreNotConfiguredError until a real client is implemented. Prefer keeping
ALETHEIA_STORE=sqlite and enabling ALETHEIA_CLOUD_MIRROR=firestore for the
v0.4 one-way backup path first.
"""

from __future__ import annotations

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
    WatchlistArchive,
    WatchlistCreate,
    WatchlistItem,
    WatchlistResponse,
)
from backend.app.stores.base import AppStore


class StoreNotConfiguredError(RuntimeError):
    """Raised by stub backends that are selected but not yet wired."""


_MSG = (
    "Firestore AppStore is not wired yet. Keep ALETHEIA_STORE=sqlite; "
    "use ALETHEIA_CLOUD_MIRROR=firestore for offsite backup once credentials "
    "are configured (see GET /api/cloud/status)."
)


class FirestoreStore(AppStore):
    """Skeleton only — every mutating/query method raises until implemented."""

    def __init__(
        self,
        *,
        project_id: Optional[str] = None,
        credentials_path: Optional[str] = None,
    ) -> None:
        self.project_id = project_id
        self.credentials_path = credentials_path

    def init_schema(self) -> None:
        # Schema-less document store; nothing to migrate locally.
        return None

    def close(self) -> None:
        return None

    def _nyi(self) -> None:
        raise StoreNotConfiguredError(_MSG)

    # JudgmentStore
    def create_judgment(self, body: JudgmentCreate) -> JudgmentEntry:
        self._nyi()

    def append_judgment(self, root_id: str, body: JudgmentAppend) -> JudgmentEntry:
        self._nyi()

    def list_chains(
        self,
        *,
        object: Optional[str] = None,
        status: Optional[str] = None,
        jtype: Optional[str] = None,
        origin: Optional[str] = None,
    ) -> list[JudgmentChain]:
        self._nyi()

    def get_chain(self, root_id: str) -> Optional[JudgmentChain]:
        self._nyi()

    # NoteStore
    def create_note(self, body: NoteCreate) -> QuickNote:
        self._nyi()

    def list_notes(
        self, *, object: Optional[str] = None, limit: Optional[int] = None
    ) -> list[QuickNote]:
        self._nyi()

    # WatchlistStore
    def list_watchlist(self, *, tier: Optional[str] = None) -> WatchlistResponse:
        self._nyi()

    def add_watchlist(self, body: WatchlistCreate) -> WatchlistItem:
        self._nyi()

    def archive_watchlist(self, ticker: str, body: WatchlistArchive) -> WatchlistItem:
        self._nyi()

    def set_watchlist_tier(self, ticker: str, tier: str) -> WatchlistItem:
        self._nyi()

    # EventStore
    def create_event(self, event: EventRecord) -> EventRecord:
        self._nyi()

    def get_event(self, event_id: str) -> Optional[EventRecord]:
        self._nyi()

    def confirm_event(
        self,
        event_id: str,
        *,
        scope: Optional[str] = None,
        user_comment: Optional[str] = None,
    ) -> EventRecord:
        self._nyi()

    def list_confirmed_events(
        self, *, object: Optional[str] = None
    ) -> list[EventRecord]:
        self._nyi()

    # FeedStore
    def upsert_feed_card(self, card: FeedCard) -> FeedCard:
        self._nyi()

    def get_feed_card(self, card_id: str) -> Optional[FeedCard]:
        self._nyi()

    def list_feed_cards(
        self, *, batch_date: Optional[str] = None, object: Optional[str] = None
    ) -> list[FeedCard]:
        self._nyi()

    def latest_batch_date(self) -> Optional[str]:
        self._nyi()

    def insert_filtered_item(self, item: FilteredItem) -> FilteredItem:
        self._nyi()

    def list_filtered_items(
        self, *, batch_date: Optional[str] = None
    ) -> list[FilteredItem]:
        self._nyi()

    # NarrativeScanStore
    def insert_narrative_scan(self, row: NarrativeScanRecord) -> NarrativeScanRecord:
        self._nyi()

    def latest_narrative_scan(
        self, ticker: str, date: str
    ) -> Optional[NarrativeScanRecord]:
        self._nyi()

    def get_narrative_scan(self, scan_id: str) -> Optional[NarrativeScanRecord]:
        self._nyi()

    # LlmUsageStore
    def insert_llm_usage(self, row: dict[str, Any]) -> dict[str, Any]:
        self._nyi()

    def sum_llm_cost_since(self, since_iso: str) -> float:
        self._nyi()

    def list_llm_usage_since(self, since_iso: str) -> list[dict[str, Any]]:
        self._nyi()

    # ExecutionStore
    def create_execution(self, body: ExecutionCreate) -> ExecutionRecord:
        self._nyi()

    def get_execution(self, exec_id: str) -> Optional[ExecutionRecord]:
        self._nyi()

    def void_execution(
        self, exec_id: str, *, replacement: Optional[ExecutionCreate] = None
    ) -> dict[str, Any]:
        self._nyi()

    def list_executions(
        self, *, ticker: Optional[str] = None, include_voided: bool = False
    ) -> list[ExecutionRecord]:
        self._nyi()

    def list_positions(self) -> list[PositionRow]:
        self._nyi()

    # SnapshotStore
    def upsert_snapshot(self, date: str, module: str, payload: dict[str, Any]) -> None:
        self._nyi()

    def get_snapshot(self, date: str, module: str) -> Optional[dict[str, Any]]:
        self._nyi()
