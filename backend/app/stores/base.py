"""Store interfaces. Business code must depend only on these — never concrete impls."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional

from backend.app.models import (
    JudgmentAppend,
    JudgmentChain,
    JudgmentCreate,
    JudgmentEntry,
    NoteCreate,
    QuickNote,
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
    def list_watchlist(self) -> WatchlistResponse:
        ...

    @abstractmethod
    def add_watchlist(self, body: WatchlistCreate) -> WatchlistItem:
        ...

    @abstractmethod
    def archive_watchlist(self, ticker: str, body: WatchlistArchive) -> WatchlistItem:
        ...


class AppStore(JudgmentStore, NoteStore, WatchlistStore, ABC):
    """Combined store used by the app (single SQLite + JSONL backend in v1)."""

    @abstractmethod
    def init_schema(self) -> None:
        ...


class ConflictError(Exception):
    """Raised when appending to a closed judgment chain."""
