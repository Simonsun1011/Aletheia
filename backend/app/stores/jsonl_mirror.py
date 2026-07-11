"""Append-only JSONL mirror for judgment_entries / quick_notes."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Optional


def _month_file(journal_dir: Path, created_at: str) -> Path:
    """Route a row to data/journal/YYYY-MM.jsonl from its created_at."""
    stamp = created_at.replace("Z", "+00:00")
    dt = datetime.fromisoformat(stamp)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    name = dt.strftime("%Y-%m") + ".jsonl"
    return journal_dir / name


def append_row(journal_dir: Path, table: str, row: dict[str, Any]) -> Path:
    """Append one row. Call BEFORE SQLite write (backup-first)."""
    journal_dir.mkdir(parents=True, exist_ok=True)
    created_at = row.get("created_at") or datetime.now(timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    path = _month_file(journal_dir, created_at)
    payload = {"_table": table, **row}
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(payload, ensure_ascii=False) + "\n")
    return path


def iter_rows(journal_dir: Path) -> Iterable[dict[str, Any]]:
    """Yield all JSONL rows across month files, in filename then file order."""
    if not journal_dir.exists():
        return
    for path in sorted(journal_dir.glob("*.jsonl")):
        with path.open(encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                yield json.loads(line)


def count_rows(journal_dir: Path, table: Optional[str] = None) -> int:
    n = 0
    for row in iter_rows(journal_dir):
        if table is None or row.get("_table") == table:
            n += 1
    return n
