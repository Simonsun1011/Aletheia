"""Rebuild judgment_entries and quick_notes from JSONL (idempotent).

Usage:
    python -m backend.app.stores.rebuild
    python -m backend.app.stores.rebuild --db data/app.db --journal data/journal
"""

from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path

from backend.app.config import get_settings
from backend.app.stores import jsonl_mirror
from backend.app.stores.sqlite_store import SCHEMA_SQL, TRIGGER_SQL

JUDGMENT_COLS = [
    "id",
    "root_id",
    "kind",
    "created_at",
    "object",
    "jtype",
    "direction",
    "horizon_days",
    "confidence",
    "text",
    "supporting",
    "counter",
    "falsification",
    "pre_view",
    "post_view",
    "snapshot_date",
    "expires_on",
    "status",
    "origin",
]

NOTE_COLS = ["id", "created_at", "text", "object"]

EXECUTION_COLS = [
    "id",
    "created_at",
    "ticker",
    "side",
    "trade_date",
    "shares",
    "price",
    "fees",
    "plan_id",
    "judgment_root_id",
    "note",
    "voided_by",
]


def rebuild(db_path: Path, journal_dir: Path) -> dict[str, int]:
    """Drop and recreate judgment/notes/executions from JSONL. Watchlist/etc untouched."""
    db_path = Path(db_path)
    journal_dir = Path(journal_dir)
    db_path.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(str(db_path))
    try:
        # Drop triggers first (they block DELETE), then tables
        conn.executescript(
            """
            DROP TRIGGER IF EXISTS judgment_entries_no_update;
            DROP TRIGGER IF EXISTS judgment_entries_no_delete;
            DROP TRIGGER IF EXISTS quick_notes_no_update;
            DROP TRIGGER IF EXISTS quick_notes_no_delete;
            DROP TRIGGER IF EXISTS executions_no_delete;
            DROP TRIGGER IF EXISTS executions_void_only_update;
            DROP TABLE IF EXISTS judgment_entries;
            DROP TABLE IF EXISTS quick_notes;
            DROP TABLE IF EXISTS executions;
            """
        )
        conn.executescript(SCHEMA_SQL)
        # Insert without triggers, then re-enable
        j_count = 0
        n_count = 0
        e_count = 0
        for raw in jsonl_mirror.iter_rows(journal_dir):
            table = raw.get("_table")
            if table == "judgment_entries":
                row = {c: raw.get(c) for c in JUDGMENT_COLS}
                if row.get("status") is None:
                    row["status"] = "open"
                if row.get("origin") is None:
                    row["origin"] = "journal"
                placeholders = ", ".join(f":{c}" for c in JUDGMENT_COLS)
                cols = ", ".join(JUDGMENT_COLS)
                conn.execute(
                    f"INSERT OR REPLACE INTO judgment_entries ({cols}) VALUES ({placeholders})",
                    row,
                )
                j_count += 1
            elif table == "quick_notes":
                row = {c: raw.get(c) for c in NOTE_COLS}
                placeholders = ", ".join(f":{c}" for c in NOTE_COLS)
                cols = ", ".join(NOTE_COLS)
                conn.execute(
                    f"INSERT OR REPLACE INTO quick_notes ({cols}) VALUES ({placeholders})",
                    row,
                )
                n_count += 1
            elif table == "executions":
                row = {c: raw.get(c) for c in EXECUTION_COLS}
                placeholders = ", ".join(f":{c}" for c in EXECUTION_COLS)
                cols = ", ".join(EXECUTION_COLS)
                conn.execute(
                    f"INSERT OR REPLACE INTO executions ({cols}) VALUES ({placeholders})",
                    row,
                )
                e_count += 1
        conn.executescript(TRIGGER_SQL)
        conn.commit()
        return {
            "judgment_entries": j_count,
            "quick_notes": n_count,
            "executions": e_count,
        }
    finally:
        conn.close()


def main() -> None:
    settings = get_settings()
    parser = argparse.ArgumentParser(description="Rebuild app.db judgment tables from JSONL")
    parser.add_argument("--db", type=Path, default=settings.app_db_path)
    parser.add_argument("--journal", type=Path, default=settings.journal_dir)
    args = parser.parse_args()
    counts = rebuild(args.db, args.journal)
    print(f"Rebuilt {args.db}: {counts}")


if __name__ == "__main__":
    main()
