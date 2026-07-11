"""Glossary seed import + lookup — Slice 4."""

from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from backend.app.config import REPO_ROOT

log = logging.getLogger("aletheia.store")


def glossary_seed_path() -> Path:
    return REPO_ROOT / "config" / "glossary_seed.json"


def import_glossary_seed(conn: sqlite3.Connection, path: Optional[Path] = None) -> int:
    """Idempotent upsert of seed terms. Returns rows touched."""
    p = path or glossary_seed_path()
    if not p.exists():
        log.warning("glossary seed missing: %s", p)
        return 0
    data = json.loads(p.read_text(encoding="utf-8"))
    terms = data if isinstance(data, list) else data.get("terms") or []
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    n = 0
    for row in terms:
        term = str(row["term"]).strip()
        if not term:
            continue
        conn.execute(
            """
            INSERT INTO glossary (term, one_liner, full_md, sources, version, state, updated_at)
            VALUES (?, ?, ?, ?, ?, 'unknown', ?)
            ON CONFLICT(term) DO UPDATE SET
                one_liner=excluded.one_liner,
                full_md=excluded.full_md,
                sources=excluded.sources,
                version=excluded.version,
                updated_at=excluded.updated_at
            """,
            (
                term,
                str(row.get("one_liner") or ""),
                str(row.get("full_md") or row.get("one_liner") or ""),
                json.dumps(row.get("sources") or [], ensure_ascii=False),
                int(row.get("version") or 1),
                now,
            ),
        )
        n += 1
    conn.commit()
    return n


def get_glossary_term(conn: sqlite3.Connection, term: str) -> Optional[dict[str, Any]]:
    row = conn.execute(
        "SELECT * FROM glossary WHERE term = ? COLLATE NOCASE",
        (term.strip(),),
    ).fetchone()
    if row is None:
        return None
    d = dict(row)
    return d
