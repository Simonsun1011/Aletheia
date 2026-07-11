"""SQLite store + JSONL mirror. Write order: JSONL first, then SQLite."""

from __future__ import annotations

import logging
import sqlite3
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

from ulid import ULID

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
from backend.app.stores import jsonl_mirror
from backend.app.stores.base import AppStore, ConflictError

# CONTRACT-ISSUE: data-model.md says root.status is set to 'closed' when a
# review entry is appended, but append-only + BEFORE UPDATE triggers forbid
# UPDATE on judgment_entries. Chain closed state is therefore DERIVED from
# presence of a kind='review' entry (API status field reflects this). Planning
# layer should either (a) allow a narrow status-only UPDATE exception in the
# trigger, or (b) document derived-status as the canonical rule.

store_log = logging.getLogger("aletheia.store")


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS judgment_entries (
    id TEXT PRIMARY KEY,
    root_id TEXT NOT NULL,
    kind TEXT NOT NULL CHECK (kind IN ('original','amendment','retraction','review')),
    created_at TEXT NOT NULL,
    object TEXT NOT NULL,
    jtype TEXT CHECK (jtype IS NULL OR jtype IN ('fact','market_reaction','causal','action')),
    direction TEXT CHECK (direction IS NULL OR direction IN ('up','down','outperform','underperform','neutral')),
    horizon_days INTEGER,
    confidence REAL CHECK (confidence IS NULL OR (confidence >= 0 AND confidence <= 1)),
    text TEXT NOT NULL,
    supporting TEXT,
    counter TEXT,
    falsification TEXT,
    pre_view TEXT,
    post_view TEXT,
    snapshot_date TEXT,
    expires_on TEXT,
    status TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open','closed'))
);
CREATE INDEX IF NOT EXISTS idx_judgment_root ON judgment_entries(root_id);
CREATE INDEX IF NOT EXISTS idx_judgment_object_status ON judgment_entries(object, status);
CREATE INDEX IF NOT EXISTS idx_judgment_expires ON judgment_entries(expires_on);

CREATE TABLE IF NOT EXISTS quick_notes (
    id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    text TEXT NOT NULL,
    object TEXT
);

CREATE TABLE IF NOT EXISTS watchlist (
    ticker TEXT PRIMARY KEY,
    added_at TEXT NOT NULL,
    add_reason TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('active','archived','shadow')),
    archived_at TEXT,
    archive_reason TEXT
);

CREATE TABLE IF NOT EXISTS snapshots (
    date TEXT NOT NULL,
    module TEXT NOT NULL,
    payload TEXT NOT NULL,
    PRIMARY KEY (date, module)
);

CREATE TABLE IF NOT EXISTS events (
    id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    object TEXT,
    event_date TEXT,
    category TEXT CHECK (category IN ('company','financial','estimates','flows','industry','policy','macro')),
    source_url TEXT,
    fact_text TEXT NOT NULL,
    impact_path TEXT,
    confirmation TEXT CHECK (confirmation IN ('confirmed','speculative')),
    user_confirmed INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS glossary (
    term TEXT PRIMARY KEY,
    one_liner TEXT NOT NULL,
    full_md TEXT NOT NULL,
    sources TEXT,
    version INTEGER DEFAULT 1,
    state TEXT CHECK (state IN ('unknown','known','saved')),
    updated_at TEXT
);
"""

TRIGGER_SQL = """
CREATE TRIGGER IF NOT EXISTS judgment_entries_no_update
BEFORE UPDATE ON judgment_entries
BEGIN
    SELECT RAISE(ABORT, 'APPEND_ONLY_VIOLATION: judgment_entries is append-only');
END;

CREATE TRIGGER IF NOT EXISTS judgment_entries_no_delete
BEFORE DELETE ON judgment_entries
BEGIN
    SELECT RAISE(ABORT, 'APPEND_ONLY_VIOLATION: judgment_entries is append-only');
END;

CREATE TRIGGER IF NOT EXISTS quick_notes_no_update
BEFORE UPDATE ON quick_notes
BEGIN
    SELECT RAISE(ABORT, 'APPEND_ONLY_VIOLATION: quick_notes is append-only');
END;

CREATE TRIGGER IF NOT EXISTS quick_notes_no_delete
BEFORE DELETE ON quick_notes
BEGIN
    SELECT RAISE(ABORT, 'APPEND_ONLY_VIOLATION: quick_notes is append-only');
END;
"""


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def add_trading_days(start: date, n: int) -> date:
    """v1 approximation: skip Sat/Sun (no holiday calendar)."""
    d = start
    added = 0
    while added < n:
        d += timedelta(days=1)
        if d.weekday() < 5:
            added += 1
    return d


def _new_id() -> str:
    return str(ULID())


class SqliteStore(AppStore):
    def __init__(self, db_path: Path, journal_dir: Path) -> None:
        self.db_path = Path(db_path)
        self.journal_dir = Path(journal_dir)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.journal_dir.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")

    def init_schema(self) -> None:
        self._conn.executescript(SCHEMA_SQL)
        self._conn.executescript(TRIGGER_SQL)
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    def _row_to_entry(self, row: sqlite3.Row, *, chain_status: str) -> JudgmentEntry:
        d = dict(row)
        d["status"] = chain_status
        return JudgmentEntry(**d)

    def _fetch_entries(self, root_id: str) -> list[sqlite3.Row]:
        cur = self._conn.execute(
            "SELECT * FROM judgment_entries WHERE root_id = ? ORDER BY created_at ASC, id ASC",
            (root_id,),
        )
        return list(cur.fetchall())

    def _build_chain(self, root_id: str) -> Optional[JudgmentChain]:
        rows = self._fetch_entries(root_id)
        if not rows:
            return None
        closed = any(r["kind"] == "review" for r in rows)
        status = "closed" if closed else "open"
        original = next((r for r in rows if r["kind"] == "original"), rows[0])
        entries = [self._row_to_entry(r, chain_status=status) for r in rows]
        return JudgmentChain(
            root_id=root_id,
            object=original["object"],
            status=status,
            entries=entries,
        )

    def _today_snapshot_date(self, object_sym: str) -> Optional[str]:
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        module = f"ticker:{object_sym}"
        cur = self._conn.execute(
            "SELECT date FROM snapshots WHERE date = ? AND module = ?",
            (today, module),
        )
        return today if cur.fetchone() else None

    def _execute(self, sql: str, params: Any = ()) -> sqlite3.Cursor:
        """Execute SQL; log WARNING on append-only trigger abort."""
        try:
            return self._conn.execute(sql, params)
        except sqlite3.IntegrityError as e:
            if "APPEND_ONLY_VIOLATION" in str(e):
                store_log.warning(
                    "append-only rejection via SQLite trigger: %s", e
                )
            raise

    # ── JudgmentStore ──────────────────────────────────────

    def create_judgment(self, body: JudgmentCreate) -> JudgmentEntry:
        eid = _new_id()
        created = _now_iso()
        expires: Optional[str] = None
        if body.horizon_days is not None:
            start = datetime.now(timezone.utc).date()
            expires = add_trading_days(start, body.horizon_days).isoformat()

        entry = JudgmentEntry(
            id=eid,
            root_id=eid,
            kind="original",
            created_at=created,
            object=body.object,
            jtype=body.jtype,
            direction=body.direction,
            horizon_days=body.horizon_days,
            confidence=body.confidence,
            text=body.text,
            supporting=body.supporting,
            counter=body.counter,
            falsification=body.falsification,
            pre_view=body.pre_view,
            post_view=body.post_view,
            snapshot_date=self._today_snapshot_date(body.object),
            expires_on=expires,
            status="open",
        )
        row = entry.model_dump()
        jsonl_mirror.append_row(self.journal_dir, "judgment_entries", row)
        self._execute(
            """
            INSERT INTO judgment_entries (
                id, root_id, kind, created_at, object, jtype, direction,
                horizon_days, confidence, text, supporting, counter,
                falsification, pre_view, post_view, snapshot_date, expires_on, status
            ) VALUES (
                :id, :root_id, :kind, :created_at, :object, :jtype, :direction,
                :horizon_days, :confidence, :text, :supporting, :counter,
                :falsification, :pre_view, :post_view, :snapshot_date, :expires_on, :status
            )
            """,
            row,
        )
        self._conn.commit()
        store_log.info(
            "judgment created id=%s object=%s jtype=%s",
            entry.id,
            entry.object,
            entry.jtype,
        )
        return entry

    def append_judgment(self, root_id: str, body: JudgmentAppend) -> JudgmentEntry:
        chain = self.get_chain(root_id)
        if chain is None:
            raise KeyError(root_id)
        if chain.status == "closed" and body.kind != "review":
            raise ConflictError(f"chain {root_id} is closed")

        original = next(e for e in chain.entries if e.kind == "original")
        entry = JudgmentEntry(
            id=_new_id(),
            root_id=root_id,
            kind=body.kind,
            created_at=_now_iso(),
            object=original.object,
            jtype=None,
            direction=None,
            horizon_days=None,
            confidence=None,
            text=body.text,
            supporting=None,
            counter=None,
            falsification=None,
            pre_view=None,
            post_view=None,
            snapshot_date=None,
            expires_on=None,
            status="closed" if body.kind == "review" else "open",
        )
        row = entry.model_dump()
        jsonl_mirror.append_row(self.journal_dir, "judgment_entries", row)
        self._execute(
            """
            INSERT INTO judgment_entries (
                id, root_id, kind, created_at, object, jtype, direction,
                horizon_days, confidence, text, supporting, counter,
                falsification, pre_view, post_view, snapshot_date, expires_on, status
            ) VALUES (
                :id, :root_id, :kind, :created_at, :object, :jtype, :direction,
                :horizon_days, :confidence, :text, :supporting, :counter,
                :falsification, :pre_view, :post_view, :snapshot_date, :expires_on, :status
            )
            """,
            row,
        )
        self._conn.commit()
        store_log.info(
            "judgment appended root_id=%s kind=%s id=%s",
            root_id,
            entry.kind,
            entry.id,
        )
        return entry

    def list_chains(
        self,
        *,
        object: Optional[str] = None,
        status: Optional[str] = None,
        jtype: Optional[str] = None,
    ) -> list[JudgmentChain]:
        sql = "SELECT DISTINCT root_id FROM judgment_entries WHERE 1=1"
        params: list[Any] = []
        if object is not None:
            sql += " AND object = ?"
            params.append(object)
        root_ids = [r[0] for r in self._conn.execute(sql, params).fetchall()]

        chains: list[JudgmentChain] = []
        for rid in root_ids:
            chain = self._build_chain(rid)
            if chain is None:
                continue
            if status is not None and chain.status != status:
                continue
            if jtype is not None:
                orig = next((e for e in chain.entries if e.kind == "original"), None)
                if orig is None or orig.jtype != jtype:
                    continue
            chains.append(chain)
        chains.sort(
            key=lambda c: next(
                e.created_at for e in c.entries if e.kind == "original"
            ),
            reverse=True,
        )
        return chains

    def get_chain(self, root_id: str) -> Optional[JudgmentChain]:
        return self._build_chain(root_id)

    # ── NoteStore ──────────────────────────────────────────

    def create_note(self, body: NoteCreate) -> QuickNote:
        note = QuickNote(
            id=_new_id(),
            created_at=_now_iso(),
            text=body.text,
            object=body.object,
        )
        row = note.model_dump()
        jsonl_mirror.append_row(self.journal_dir, "quick_notes", row)
        self._execute(
            "INSERT INTO quick_notes (id, created_at, text, object) "
            "VALUES (:id, :created_at, :text, :object)",
            row,
        )
        self._conn.commit()
        store_log.info("note created id=%s object=%s", note.id, note.object)
        return note

    def list_notes(
        self, *, object: Optional[str] = None, limit: Optional[int] = None
    ) -> list[QuickNote]:
        sql = "SELECT * FROM quick_notes WHERE 1=1"
        params: list[Any] = []
        if object is not None:
            sql += " AND object = ?"
            params.append(object)
        sql += " ORDER BY created_at DESC"
        if limit is not None:
            sql += " LIMIT ?"
            params.append(limit)
        rows = self._conn.execute(sql, params).fetchall()
        return [QuickNote(**dict(r)) for r in rows]

    # ── WatchlistStore ─────────────────────────────────────

    def list_watchlist(self) -> WatchlistResponse:
        rows = self._conn.execute("SELECT * FROM watchlist").fetchall()
        items = [WatchlistItem(**dict(r)) for r in rows]
        return WatchlistResponse(
            active=[i for i in items if i.status == "active"],
            shadow=[i for i in items if i.status == "shadow"],
        )

    def add_watchlist(self, body: WatchlistCreate) -> WatchlistItem:
        item = WatchlistItem(
            ticker=body.ticker.upper(),
            added_at=_now_iso(),
            add_reason=body.add_reason,
            status="active",
            archived_at=None,
            archive_reason=None,
        )
        self._conn.execute(
            """
            INSERT INTO watchlist (ticker, added_at, add_reason, status, archived_at, archive_reason)
            VALUES (:ticker, :added_at, :add_reason, :status, :archived_at, :archive_reason)
            """,
            item.model_dump(),
        )
        self._conn.commit()
        return item

    def archive_watchlist(self, ticker: str, body: WatchlistArchive) -> WatchlistItem:
        ticker = ticker.upper()
        cur = self._conn.execute(
            "SELECT * FROM watchlist WHERE ticker = ?", (ticker,)
        )
        row = cur.fetchone()
        if row is None:
            raise KeyError(ticker)
        archived_at = _now_iso()
        self._conn.execute(
            """
            UPDATE watchlist
            SET status = 'archived', archived_at = ?, archive_reason = ?
            WHERE ticker = ?
            """,
            (archived_at, body.archive_reason, ticker),
        )
        self._conn.commit()
        updated = self._conn.execute(
            "SELECT * FROM watchlist WHERE ticker = ?", (ticker,)
        ).fetchone()
        return WatchlistItem(**dict(updated))
