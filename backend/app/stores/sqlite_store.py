"""SQLite store + JSONL mirror. Write order: JSONL first, then SQLite."""

from __future__ import annotations

import json
import logging
import sqlite3
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

from ulid import ULID

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
    NarrativeScanPayload,
    NarrativeScanRecord,
    NoteCreate,
    PositionRow,
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
    kind TEXT NOT NULL CHECK (kind IN ('original','revision','amendment','retraction','review')),
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
    status TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open','closed')),
    origin TEXT NOT NULL DEFAULT 'journal' CHECK (origin IN ('journal','console'))
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
    tier TEXT NOT NULL DEFAULT 'base' CHECK (tier IN ('focus','base','muted')),
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
    user_confirmed INTEGER DEFAULT 0,
    scope TEXT CHECK (scope IS NULL OR scope IN ('company','theme','macro','other')),
    user_comment TEXT
);

CREATE TABLE IF NOT EXISTS feed_cards (
    id TEXT PRIMARY KEY,
    fetched_at TEXT NOT NULL,
    published_at TEXT,
    source TEXT,
    title TEXT NOT NULL,
    url TEXT NOT NULL,
    summary TEXT,
    objects TEXT,
    dedup_group TEXT,
    batch_date TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_feed_cards_batch ON feed_cards(batch_date);
CREATE INDEX IF NOT EXISTS idx_feed_cards_dedup ON feed_cards(dedup_group);

CREATE TABLE IF NOT EXISTS feed_raw (
    id TEXT PRIMARY KEY,
    fetched_at TEXT NOT NULL,
    published_at TEXT,
    source TEXT,
    title TEXT NOT NULL,
    url TEXT NOT NULL,
    content TEXT,
    objects TEXT,
    batch_date TEXT NOT NULL,
    feed_id TEXT
);

CREATE TABLE IF NOT EXISTS filtered_items (
    id TEXT PRIMARY KEY,
    fetched_at TEXT NOT NULL,
    source TEXT,
    title TEXT NOT NULL,
    url TEXT NOT NULL,
    batch_date TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_filtered_batch ON filtered_items(batch_date);

CREATE TABLE IF NOT EXISTS narrative_scans (
    id TEXT PRIMARY KEY,
    ticker TEXT NOT NULL,
    date TEXT NOT NULL,
    payload TEXT NOT NULL,
    model TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_narrative_scans_ticker_date
    ON narrative_scans(ticker, date, created_at);

CREATE TABLE IF NOT EXISTS llm_usage (
    id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    model TEXT NOT NULL,
    purpose TEXT NOT NULL,
    prompt_version TEXT,
    tokens_in INTEGER,
    tokens_out INTEGER,
    elapsed_ms INTEGER,
    est_cost_usd REAL
);
CREATE INDEX IF NOT EXISTS idx_llm_usage_created ON llm_usage(created_at);

CREATE TABLE IF NOT EXISTS glossary (
    term TEXT PRIMARY KEY,
    one_liner TEXT NOT NULL,
    full_md TEXT NOT NULL,
    sources TEXT,
    version INTEGER DEFAULT 1,
    state TEXT CHECK (state IN ('unknown','known','saved')),
    updated_at TEXT
);

CREATE TABLE IF NOT EXISTS executions (
    id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    ticker TEXT NOT NULL,
    side TEXT NOT NULL CHECK (side IN ('buy','sell')),
    trade_date TEXT NOT NULL,
    shares REAL NOT NULL,
    price REAL NOT NULL,
    fees REAL,
    plan_id TEXT,
    judgment_root_id TEXT,
    note TEXT,
    voided_by TEXT
);
CREATE INDEX IF NOT EXISTS idx_executions_ticker ON executions(ticker);
CREATE INDEX IF NOT EXISTS idx_executions_trade_date ON executions(trade_date);
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

-- executions: immutable except setting voided_by NULL → non-NULL once
CREATE TRIGGER IF NOT EXISTS executions_no_delete
BEFORE DELETE ON executions
BEGIN
    SELECT RAISE(ABORT, 'APPEND_ONLY_VIOLATION: executions is append-only');
END;

CREATE TRIGGER IF NOT EXISTS executions_void_only_update
BEFORE UPDATE ON executions
BEGIN
    SELECT CASE
        WHEN OLD.voided_by IS NOT NULL THEN
            RAISE(ABORT, 'APPEND_ONLY_VIOLATION: executions already voided')
        WHEN NEW.id IS NOT OLD.id
          OR NEW.created_at IS NOT OLD.created_at
          OR NEW.ticker IS NOT OLD.ticker
          OR NEW.side IS NOT OLD.side
          OR NEW.trade_date IS NOT OLD.trade_date
          OR NEW.shares IS NOT OLD.shares
          OR NEW.price IS NOT OLD.price
          OR NEW.fees IS NOT OLD.fees
          OR NEW.plan_id IS NOT OLD.plan_id
          OR NEW.judgment_root_id IS NOT OLD.judgment_root_id
          OR NEW.note IS NOT OLD.note
          OR NEW.voided_by IS NULL THEN
            RAISE(ABORT, 'APPEND_ONLY_VIOLATION: executions only voided_by may change')
        ELSE NULL
    END;
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
        self._migrate_v11_v12()
        self._migrate_v16_v17()
        from backend.app.services.glossary import import_glossary_seed

        try:
            n = import_glossary_seed(self._conn)
            if n:
                store_log.info("glossary seed imported/updated terms=%s", n)
        except Exception as e:
            store_log.warning("glossary seed import failed: %s", e)
        self._conn.commit()

    def _table_sql(self, name: str) -> str:
        row = self._conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name=?",
            (name,),
        ).fetchone()
        return (row[0] or "") if row else ""

    def _migrate_v11_v12(self) -> None:
        """Bring existing DBs up to contract v1.1 (tier) / v1.2 (revision)."""
        # watchlist.tier
        cols = {
            r[1]
            for r in self._conn.execute("PRAGMA table_info(watchlist)").fetchall()
        }
        if cols and "tier" not in cols:
            self._conn.execute(
                "ALTER TABLE watchlist ADD COLUMN tier TEXT NOT NULL DEFAULT 'base'"
            )

        # judgment_entries kind CHECK must allow 'revision'
        jsql = self._table_sql("judgment_entries")
        if jsql and "'revision'" not in jsql:
            self._conn.executescript(
                """
                DROP TRIGGER IF EXISTS judgment_entries_no_update;
                DROP TRIGGER IF EXISTS judgment_entries_no_delete;
                ALTER TABLE judgment_entries RENAME TO judgment_entries_old;
                """
            )
            self._conn.executescript(
                """
                CREATE TABLE judgment_entries (
                    id TEXT PRIMARY KEY,
                    root_id TEXT NOT NULL,
                    kind TEXT NOT NULL CHECK (kind IN ('original','revision','amendment','retraction','review')),
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
                INSERT INTO judgment_entries SELECT * FROM judgment_entries_old;
                DROP TABLE judgment_entries_old;
                CREATE INDEX IF NOT EXISTS idx_judgment_root ON judgment_entries(root_id);
                CREATE INDEX IF NOT EXISTS idx_judgment_object_status ON judgment_entries(object, status);
                CREATE INDEX IF NOT EXISTS idx_judgment_expires ON judgment_entries(expires_on);
                """
            )
            self._conn.executescript(TRIGGER_SQL)

    def _migrate_v16_v17(self) -> None:
        """v1.6: judgment_entries.origin; v1.7: events.scope / events.user_comment.

        ALTER TABLE ADD COLUMN is DDL (not caught by append-only UPDATE/DELETE
        triggers). CHECK constraints live in the fresh-schema CREATE only.
        """
        jcols = {
            r[1]
            for r in self._conn.execute(
                "PRAGMA table_info(judgment_entries)"
            ).fetchall()
        }
        if jcols and "origin" not in jcols:
            self._conn.execute(
                "ALTER TABLE judgment_entries "
                "ADD COLUMN origin TEXT NOT NULL DEFAULT 'journal'"
            )

        ecols = {
            r[1]
            for r in self._conn.execute("PRAGMA table_info(events)").fetchall()
        }
        if ecols and "scope" not in ecols:
            self._conn.execute("ALTER TABLE events ADD COLUMN scope TEXT")
        if ecols and "user_comment" not in ecols:
            self._conn.execute("ALTER TABLE events ADD COLUMN user_comment TEXT")

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
            origin=body.origin,
        )
        row = entry.model_dump()
        jsonl_mirror.append_row(self.journal_dir, "judgment_entries", row)
        self._execute(
            """
            INSERT INTO judgment_entries (
                id, root_id, kind, created_at, object, jtype, direction,
                horizon_days, confidence, text, supporting, counter,
                falsification, pre_view, post_view, snapshot_date, expires_on,
                status, origin
            ) VALUES (
                :id, :root_id, :kind, :created_at, :object, :jtype, :direction,
                :horizon_days, :confidence, :text, :supporting, :counter,
                :falsification, :pre_view, :post_view, :snapshot_date, :expires_on,
                :status, :origin
            )
            """,
            row,
        )
        self._conn.commit()
        store_log.info(
            "judgment created id=%s object=%s jtype=%s origin=%s",
            entry.id,
            entry.object,
            entry.jtype,
            entry.origin,
        )
        return entry

    def append_judgment(self, root_id: str, body: JudgmentAppend) -> JudgmentEntry:
        chain = self.get_chain(root_id)
        if chain is None:
            raise KeyError(root_id)
        if chain.status == "closed" and body.kind != "review":
            raise ConflictError(f"chain {root_id} is closed")

        original = next(e for e in chain.entries if e.kind == "original")

        if body.kind == "revision":
            if body.jtype != original.jtype:
                raise ValueError(
                    f"jtype is immutable on revision (original={original.jtype}, got={body.jtype})"
                )
            expires: Optional[str] = None
            if body.horizon_days is not None:
                start = datetime.now(timezone.utc).date()
                expires = add_trading_days(start, body.horizon_days).isoformat()
            entry = JudgmentEntry(
                id=_new_id(),
                root_id=root_id,
                kind="revision",
                created_at=_now_iso(),
                object=original.object,
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
                snapshot_date=self._today_snapshot_date(original.object),
                expires_on=expires,
                status="open",
                origin=original.origin,
            )
        else:
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
                origin=original.origin,
            )
        row = entry.model_dump()
        jsonl_mirror.append_row(self.journal_dir, "judgment_entries", row)
        self._execute(
            """
            INSERT INTO judgment_entries (
                id, root_id, kind, created_at, object, jtype, direction,
                horizon_days, confidence, text, supporting, counter,
                falsification, pre_view, post_view, snapshot_date, expires_on,
                status, origin
            ) VALUES (
                :id, :root_id, :kind, :created_at, :object, :jtype, :direction,
                :horizon_days, :confidence, :text, :supporting, :counter,
                :falsification, :pre_view, :post_view, :snapshot_date, :expires_on,
                :status, :origin
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
        origin: Optional[str] = None,
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
            orig = next((e for e in chain.entries if e.kind == "original"), None)
            if jtype is not None:
                if orig is None or orig.jtype != jtype:
                    continue
            if origin is not None:
                if orig is None or orig.origin != origin:
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

    def list_watchlist(self, *, tier: Optional[str] = None) -> WatchlistResponse:
        rows = self._conn.execute("SELECT * FROM watchlist").fetchall()
        items = []
        for r in rows:
            d = dict(r)
            if d.get("tier") is None:
                d["tier"] = "base"
            items.append(WatchlistItem(**d))
        if tier is not None:
            items = [i for i in items if i.tier == tier]
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
            tier=body.tier,
            archived_at=None,
            archive_reason=None,
        )
        self._conn.execute(
            """
            INSERT INTO watchlist (ticker, added_at, add_reason, status, tier, archived_at, archive_reason)
            VALUES (:ticker, :added_at, :add_reason, :status, :tier, :archived_at, :archive_reason)
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
        d = dict(updated)
        if d.get("tier") is None:
            d["tier"] = "base"
        return WatchlistItem(**d)

    def set_watchlist_tier(self, ticker: str, tier: str) -> WatchlistItem:
        ticker = ticker.upper()
        cur = self._conn.execute(
            "SELECT * FROM watchlist WHERE ticker = ?", (ticker,)
        )
        if cur.fetchone() is None:
            raise KeyError(ticker)
        self._conn.execute(
            "UPDATE watchlist SET tier = ? WHERE ticker = ?",
            (tier, ticker),
        )
        self._conn.commit()
        updated = self._conn.execute(
            "SELECT * FROM watchlist WHERE ticker = ?", (ticker,)
        ).fetchone()
        d = dict(updated)
        if d.get("tier") is None:
            d["tier"] = "base"
        return WatchlistItem(**d)

    # ── EventStore (Change Feed) ───────────────────────────

    def create_event(self, event: EventRecord) -> EventRecord:
        row = event.model_dump()
        self._conn.execute(
            """
            INSERT INTO events (
                id, created_at, object, event_date, category, source_url,
                fact_text, impact_path, confirmation, user_confirmed,
                scope, user_comment
            ) VALUES (
                :id, :created_at, :object, :event_date, :category, :source_url,
                :fact_text, :impact_path, :confirmation, :user_confirmed,
                :scope, :user_comment
            )
            """,
            row,
        )
        self._conn.commit()
        store_log.info(
            "event created id=%s object=%s user_confirmed=%s",
            event.id,
            event.object,
            event.user_confirmed,
        )
        return event

    def get_event(self, event_id: str) -> Optional[EventRecord]:
        row = self._conn.execute(
            "SELECT * FROM events WHERE id = ?", (event_id,)
        ).fetchone()
        return EventRecord(**dict(row)) if row else None

    def confirm_event(
        self,
        event_id: str,
        *,
        scope: Optional[str] = None,
        user_comment: Optional[str] = None,
    ) -> EventRecord:
        row = self.get_event(event_id)
        if row is None:
            raise KeyError(event_id)
        self._conn.execute(
            "UPDATE events SET user_confirmed = 1, scope = ?, user_comment = ? "
            "WHERE id = ?",
            (scope, user_comment, event_id),
        )
        self._conn.commit()
        store_log.info(
            "event confirmed id=%s scope=%s", event_id, scope
        )
        updated = self.get_event(event_id)
        assert updated is not None
        return updated

    def list_confirmed_events(
        self, *, object: Optional[str] = None
    ) -> list[EventRecord]:
        sql = "SELECT * FROM events WHERE user_confirmed = 1"
        params: list[Any] = []
        if object is not None:
            sql += " AND object = ?"
            params.append(object)
        sql += " ORDER BY created_at DESC"
        rows = self._conn.execute(sql, params).fetchall()
        return [EventRecord(**dict(r)) for r in rows]

    # ── FeedStore ──────────────────────────────────────────

    def upsert_feed_card(self, card: FeedCard) -> FeedCard:
        row = card.model_dump()
        self._conn.execute(
            """
            INSERT INTO feed_cards (
                id, fetched_at, published_at, source, title, url, summary,
                objects, dedup_group, batch_date
            ) VALUES (
                :id, :fetched_at, :published_at, :source, :title, :url, :summary,
                :objects, :dedup_group, :batch_date
            )
            ON CONFLICT(id) DO UPDATE SET
                summary=excluded.summary,
                objects=excluded.objects,
                url=excluded.url,
                source=excluded.source
            """,
            row,
        )
        self._conn.commit()
        return card

    def get_feed_card(self, card_id: str) -> Optional[FeedCard]:
        row = self._conn.execute(
            "SELECT * FROM feed_cards WHERE id = ?", (card_id,)
        ).fetchone()
        return FeedCard(**dict(row)) if row else None

    def delete_feed_card(self, card_id: str) -> None:
        self._conn.execute("DELETE FROM feed_cards WHERE id = ?", (card_id,))
        self._conn.commit()

    def list_feed_cards(
        self, *, batch_date: Optional[str] = None, object: Optional[str] = None
    ) -> list[FeedCard]:
        date = batch_date or self.latest_batch_date()
        if date is None:
            return []
        sql = "SELECT * FROM feed_cards WHERE batch_date = ?"
        params: list[Any] = [date]
        rows = [FeedCard(**dict(r)) for r in self._conn.execute(sql, params).fetchall()]
        if object:
            obj = object.upper()
            filtered: list[FeedCard] = []
            for c in rows:
                try:
                    objs = json.loads(c.objects or "[]")
                except json.JSONDecodeError:
                    objs = []
                if obj in [str(x).upper() for x in objs]:
                    filtered.append(c)
            return filtered
        return rows

    def latest_batch_date(self) -> Optional[str]:
        row = self._conn.execute(
            "SELECT batch_date FROM feed_cards ORDER BY batch_date DESC LIMIT 1"
        ).fetchone()
        return row[0] if row else None

    def insert_filtered_item(self, item: FilteredItem) -> FilteredItem:
        row = item.model_dump()
        self._conn.execute(
            """
            INSERT OR REPLACE INTO filtered_items (
                id, fetched_at, source, title, url, batch_date
            ) VALUES (
                :id, :fetched_at, :source, :title, :url, :batch_date
            )
            """,
            row,
        )
        self._conn.commit()
        return item

    def list_filtered_items(
        self, *, batch_date: Optional[str] = None
    ) -> list[FilteredItem]:
        date = batch_date
        if date is None:
            row = self._conn.execute(
                "SELECT batch_date FROM filtered_items ORDER BY batch_date DESC LIMIT 1"
            ).fetchone()
            if row is None:
                date = self.latest_batch_date()
            else:
                date = row[0]
        if date is None:
            return []
        rows = self._conn.execute(
            "SELECT * FROM filtered_items WHERE batch_date = ? ORDER BY fetched_at",
            (date,),
        ).fetchall()
        return [FilteredItem(**dict(r)) for r in rows]

    def get_glossary(self, term: str) -> Optional[dict[str, Any]]:
        from backend.app.services.glossary import get_glossary_term

        return get_glossary_term(self._conn, term)

    def insert_feed_raw(self, row: dict[str, Any]) -> None:
        self._conn.execute(
            """
            INSERT OR REPLACE INTO feed_raw (
                id, fetched_at, published_at, source, title, url, content,
                objects, batch_date, feed_id
            ) VALUES (
                :id, :fetched_at, :published_at, :source, :title, :url, :content,
                :objects, :batch_date, :feed_id
            )
            """,
            row,
        )
        self._conn.commit()

    def list_feed_raw(self, batch_date: str) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT * FROM feed_raw WHERE batch_date = ? ORDER BY fetched_at",
            (batch_date,),
        ).fetchall()
        return [dict(r) for r in rows]

    # ── NarrativeScanStore ─────────────────────────────────

    def _row_to_scan(self, row: sqlite3.Row) -> Optional[NarrativeScanRecord]:
        """Parse a stored scan. Stale payloads (pre-v1.8, missing attributed_to)
        are treated as a cache miss rather than crashing the request."""
        try:
            payload = NarrativeScanPayload.model_validate_json(row["payload"])
        except Exception as e:
            store_log.warning(
                "stale narrative_scan ignored id=%s ticker=%s err=%s",
                row["id"],
                row["ticker"],
                e,
            )
            return None
        return NarrativeScanRecord(
            id=row["id"],
            ticker=row["ticker"],
            date=row["date"],
            payload=payload,
            model=row["model"],
            created_at=row["created_at"],
        )

    def insert_narrative_scan(self, row: NarrativeScanRecord) -> NarrativeScanRecord:
        self._conn.execute(
            """
            INSERT INTO narrative_scans (id, ticker, date, payload, model, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                row.id,
                row.ticker,
                row.date,
                row.payload.model_dump_json(),
                row.model,
                row.created_at,
            ),
        )
        self._conn.commit()
        return row

    def latest_narrative_scan(
        self, ticker: str, date: str
    ) -> Optional[NarrativeScanRecord]:
        r = self._conn.execute(
            """
            SELECT * FROM narrative_scans
            WHERE ticker = ? AND date = ?
            ORDER BY created_at DESC LIMIT 1
            """,
            (ticker.upper(), date),
        ).fetchone()
        return self._row_to_scan(r) if r else None

    def get_narrative_scan(self, scan_id: str) -> Optional[NarrativeScanRecord]:
        r = self._conn.execute(
            "SELECT * FROM narrative_scans WHERE id = ?", (scan_id,)
        ).fetchone()
        return self._row_to_scan(r) if r else None

    # ── LlmUsageStore (v1.8 A4 — shared connection, DDL only in SCHEMA_SQL) ─

    def insert_llm_usage(self, row: dict[str, Any]) -> dict[str, Any]:
        self._conn.execute(
            """
            INSERT INTO llm_usage (
                id, created_at, model, purpose, prompt_version,
                tokens_in, tokens_out, elapsed_ms, est_cost_usd
            ) VALUES (
                :id, :created_at, :model, :purpose, :prompt_version,
                :tokens_in, :tokens_out, :elapsed_ms, :est_cost_usd
            )
            """,
            row,
        )
        self._conn.commit()
        return row

    def sum_llm_cost_since(self, since_iso: str) -> float:
        row = self._conn.execute(
            """
            SELECT COALESCE(SUM(est_cost_usd), 0) AS s
            FROM llm_usage
            WHERE created_at >= ? AND est_cost_usd IS NOT NULL
            """,
            (since_iso,),
        ).fetchone()
        return float(row["s"] or 0)

    def list_llm_usage_since(self, since_iso: str) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            """
            SELECT * FROM llm_usage
            WHERE created_at >= ?
            ORDER BY created_at DESC
            """,
            (since_iso,),
        ).fetchall()
        return [dict(r) for r in rows]

    # ── ExecutionStore (slice 4d / v1.9) ────────────────────

    def _row_to_execution(self, row: sqlite3.Row) -> ExecutionRecord:
        return ExecutionRecord(**dict(row))

    def _insert_execution_row(
        self, body: ExecutionCreate, *, commit: bool = True
    ) -> ExecutionRecord:
        rec = ExecutionRecord(
            id=_new_id(),
            created_at=_now_iso(),
            ticker=body.ticker,
            side=body.side,
            trade_date=body.trade_date,
            shares=body.shares,
            price=body.price,
            fees=body.fees,
            plan_id=body.plan_id,
            judgment_root_id=body.judgment_root_id,
            note=body.note,
            voided_by=None,
        )
        row = rec.model_dump()
        jsonl_mirror.append_row(self.journal_dir, "executions", row)
        self._execute(
            """
            INSERT INTO executions (
                id, created_at, ticker, side, trade_date, shares, price,
                fees, plan_id, judgment_root_id, note, voided_by
            ) VALUES (
                :id, :created_at, :ticker, :side, :trade_date, :shares, :price,
                :fees, :plan_id, :judgment_root_id, :note, :voided_by
            )
            """,
            row,
        )
        if commit:
            self._conn.commit()
        store_log.info(
            "execution created id=%s ticker=%s side=%s shares=%s price=%s",
            rec.id,
            rec.ticker,
            rec.side,
            rec.shares,
            rec.price,
        )
        return rec

    def create_execution(self, body: ExecutionCreate) -> ExecutionRecord:
        return self._insert_execution_row(body, commit=True)

    def get_execution(self, exec_id: str) -> Optional[ExecutionRecord]:
        row = self._conn.execute(
            "SELECT * FROM executions WHERE id = ?", (exec_id,)
        ).fetchone()
        return self._row_to_execution(row) if row else None

    def void_execution(
        self, exec_id: str, *, replacement: Optional[ExecutionCreate] = None
    ) -> dict[str, Any]:
        old = self.get_execution(exec_id)
        if old is None:
            raise KeyError(exec_id)
        if old.voided_by is not None:
            raise ConflictError(f"execution {exec_id} already voided")

        replacement_row: Optional[ExecutionRecord] = None
        try:
            if replacement is not None:
                replacement_row = self._insert_execution_row(
                    replacement, commit=False
                )
                voided_by = replacement_row.id
            else:
                voided_by = exec_id  # self-ref = voided without replacement

            self._execute(
                "UPDATE executions SET voided_by = ? WHERE id = ?",
                (voided_by, exec_id),
            )
            self._conn.commit()
        except Exception:
            self._conn.rollback()
            raise

        voided = self.get_execution(exec_id)
        assert voided is not None
        # Mirror post-void state for JSONL rebuild
        jsonl_mirror.append_row(
            self.journal_dir, "executions", voided.model_dump()
        )
        store_log.info(
            "execution voided id=%s voided_by=%s replacement=%s",
            exec_id,
            voided_by,
            replacement_row.id if replacement_row else None,
        )
        out: dict[str, Any] = {"voided": voided}
        if replacement_row is not None:
            out["replacement"] = replacement_row
        return out

    def list_executions(
        self, *, ticker: Optional[str] = None, include_voided: bool = False
    ) -> list[ExecutionRecord]:
        sql = "SELECT * FROM executions WHERE 1=1"
        params: list[Any] = []
        if ticker is not None:
            sql += " AND ticker = ?"
            params.append(ticker.upper())
        if not include_voided:
            sql += " AND voided_by IS NULL"
        sql += " ORDER BY trade_date DESC, created_at DESC"
        rows = self._conn.execute(sql, params).fetchall()
        return [self._row_to_execution(r) for r in rows]

    def list_positions(self) -> list[PositionRow]:
        rows = self.list_executions(include_voided=False)
        by_ticker: dict[str, list[ExecutionRecord]] = {}
        for r in rows:
            by_ticker.setdefault(r.ticker, []).append(r)

        positions: list[PositionRow] = []
        for ticker, fills in sorted(by_ticker.items()):
            net = 0.0
            buy_shares = 0.0
            buy_notional = 0.0
            sell_shares = 0.0
            sell_notional = 0.0
            linked: set[str] = set()
            for f in fills:
                if f.judgment_root_id:
                    linked.add(f.judgment_root_id)
                if f.side == "buy":
                    net += f.shares
                    buy_shares += f.shares
                    buy_notional += f.shares * f.price
                else:
                    net -= f.shares
                    sell_shares += f.shares
                    sell_notional += f.shares * f.price
            if abs(net) < 1e-12:
                continue
            if net > 0:
                avg = (buy_notional / buy_shares) if buy_shares > 0 else 0.0
            else:
                avg = (sell_notional / sell_shares) if sell_shares > 0 else 0.0
            positions.append(
                PositionRow(
                    ticker=ticker,
                    shares=round(net, 8),
                    avg_price=round(avg, 6),
                    judgment_linked_count=len(linked),
                )
            )
        return positions

