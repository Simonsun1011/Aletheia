"""Glossary seed import, state machine, Obsidian export — Slice 4 + 7.

术语匹配子集（slice-07-term-matching）：aliases 入库、碰撞校验、lookup 别名→canonical。
"""

from __future__ import annotations

import json
import logging
import os
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from backend.app.config import REPO_ROOT

log = logging.getLogger("aletheia.store")

VALID_STATES = frozenset({"unknown", "known", "saved"})
# Design §3.5.5：我的笔记区标题（工具永不覆盖其下内容）
NOTES_HEADING = "## 我的笔记"
ENCOUNTERED_RE = re.compile(r"^溯源：|^再次遇到：", re.MULTILINE)


class GlossarySeedError(ValueError):
    """种子导入期别名碰撞等硬错误——中止导入，不静默覆盖。"""


def glossary_seed_path() -> Path:
    return REPO_ROOT / "config" / "glossary_seed.json"


def field_labels_path() -> Path:
    return REPO_ROOT / "config" / "field_labels.json"


def load_field_labels() -> dict[str, Any]:
    p = field_labels_path()
    if not p.exists():
        return {}
    return json.loads(p.read_text(encoding="utf-8"))


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _parse_aliases(raw: Any) -> list[str]:
    if raw is None:
        return []
    if isinstance(raw, str):
        s = raw.strip()
        if not s:
            return []
        try:
            raw = json.loads(s)
        except json.JSONDecodeError:
            return []
    if not isinstance(raw, list):
        return []
    out: list[str] = []
    seen: set[str] = set()
    for a in raw:
        t = str(a).strip()
        if not t:
            continue
        key = t.casefold()
        if key in seen:
            continue
        seen.add(key)
        out.append(t)
    return out


def _seed_category_map(path: Optional[Path] = None) -> dict[str, str]:
    p = path or glossary_seed_path()
    if not p.exists():
        return {}
    data = json.loads(p.read_text(encoding="utf-8"))
    terms = data if isinstance(data, list) else data.get("terms") or []
    out: dict[str, str] = {}
    for row in terms:
        term = str(row.get("term") or "").strip()
        if term:
            out[term.casefold()] = str(row.get("category") or "")
    return out


def _validate_alias_collisions(terms: list[dict[str, Any]]) -> None:
    """别名不得等于任何 canonical，不得跨条重复（casefold）。撞则报错中止。"""
    canonicals: dict[str, str] = {}
    for row in terms:
        term = str(row.get("term") or "").strip()
        if not term:
            continue
        key = term.casefold()
        if key in canonicals:
            raise GlossarySeedError(
                f"duplicate canonical term in seed: {term!r} / {canonicals[key]!r}"
            )
        canonicals[key] = term

    alias_owner: dict[str, str] = {}
    for row in terms:
        term = str(row.get("term") or "").strip()
        if not term:
            continue
        for alias in _parse_aliases(row.get("aliases")):
            akey = alias.casefold()
            if akey in canonicals:
                raise GlossarySeedError(
                    f"alias {alias!r} collides with canonical term {canonicals[akey]!r}"
                )
            if akey in alias_owner and alias_owner[akey] != term:
                raise GlossarySeedError(
                    f"alias {alias!r} claimed by both {alias_owner[akey]!r} and {term!r}"
                )
            alias_owner[akey] = term


def import_glossary_seed(conn: sqlite3.Connection, path: Optional[Path] = None) -> int:
    """Idempotent upsert of seed terms. Preserves existing state on conflict.

    Reads `aliases` (JSON array). Validates alias collisions before any write;
    raises GlossarySeedError on collision (caller logs; import aborts).
    """
    p = path or glossary_seed_path()
    if not p.exists():
        log.warning("glossary seed missing: %s", p)
        return 0
    data = json.loads(p.read_text(encoding="utf-8"))
    terms = data if isinstance(data, list) else data.get("terms") or []
    _validate_alias_collisions(terms)
    now = _now()
    n = 0
    for row in terms:
        term = str(row["term"]).strip()
        if not term:
            continue
        aliases = _parse_aliases(row.get("aliases"))
        conn.execute(
            """
            INSERT INTO glossary (term, one_liner, full_md, sources, version, state, updated_at, aliases)
            VALUES (?, ?, ?, ?, ?, 'unknown', ?, ?)
            ON CONFLICT(term) DO UPDATE SET
                one_liner=excluded.one_liner,
                full_md=excluded.full_md,
                sources=excluded.sources,
                version=excluded.version,
                updated_at=excluded.updated_at,
                aliases=excluded.aliases
            """,
            (
                term,
                str(row.get("one_liner") or ""),
                str(row.get("full_md") or row.get("one_liner") or ""),
                json.dumps(row.get("sources") or [], ensure_ascii=False),
                int(row.get("version") or 1),
                now,
                json.dumps(aliases, ensure_ascii=False),
            ),
        )
        n += 1
    conn.commit()
    return n


def _row_to_dict(row: sqlite3.Row, *, category: Optional[str] = None) -> dict[str, Any]:
    d = dict(row)
    sources = d.get("sources")
    if isinstance(sources, str):
        try:
            d["sources"] = json.loads(sources)
        except json.JSONDecodeError:
            d["sources"] = []
    d["aliases"] = _parse_aliases(d.get("aliases"))
    if category is not None:
        d["category"] = category
    return d


def _find_canonical_by_alias(
    conn: sqlite3.Connection, needle: str
) -> Optional[str]:
    """Scan aliases JSON for casefold match; return canonical term or None."""
    needle_cf = needle.casefold()
    rows = conn.execute("SELECT term, aliases FROM glossary").fetchall()
    for r in rows:
        for alias in _parse_aliases(r["aliases"]):
            if alias.casefold() == needle_cf:
                return str(r["term"])
    return None


def get_glossary_term(conn: sqlite3.Connection, term: str) -> Optional[dict[str, Any]]:
    """Lookup by canonical term or alias → always returns canonical row."""
    q = term.strip()
    if not q:
        return None
    row = conn.execute(
        "SELECT * FROM glossary WHERE term = ? COLLATE NOCASE",
        (q,),
    ).fetchone()
    if row is None:
        canonical = _find_canonical_by_alias(conn, q)
        if canonical is None:
            return None
        row = conn.execute(
            "SELECT * FROM glossary WHERE term = ?",
            (canonical,),
        ).fetchone()
        if row is None:
            return None
    cats = _seed_category_map()
    return _row_to_dict(row, category=cats.get(str(row["term"]).casefold(), ""))


def list_glossary_terms(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT term, one_liner, state, version, updated_at, aliases FROM glossary ORDER BY term"
    ).fetchall()
    cats = _seed_category_map()
    out: list[dict[str, Any]] = []
    for r in rows:
        d = dict(r)
        d["aliases"] = _parse_aliases(d.get("aliases"))
        d["category"] = cats.get(str(r["term"]).casefold(), "")
        out.append(d)
    return out


def set_glossary_state(
    conn: sqlite3.Connection, term: str, state: str
) -> Optional[dict[str, Any]]:
    state = (state or "").strip()
    if state not in VALID_STATES:
        raise ValueError(f"invalid glossary state: {state}")
    existing = get_glossary_term(conn, term)
    if existing is None:
        return None
    canonical = existing["term"]
    conn.execute(
        "UPDATE glossary SET state = ?, updated_at = ? WHERE term = ?",
        (state, _now(), canonical),
    )
    conn.commit()
    return get_glossary_term(conn, canonical)


def reset_known_glossary(conn: sqlite3.Connection) -> int:
    """known → unknown（设置页重置）；saved 保留。"""
    cur = conn.execute(
        "UPDATE glossary SET state = 'unknown', updated_at = ? WHERE state = 'known'",
        (_now(),),
    )
    conn.commit()
    return int(cur.rowcount or 0)


def obsidian_export_dir() -> Optional[Path]:
    """Path from OBSIDIAN_EXPORT_DIR — never split on spaces."""
    raw = os.getenv("OBSIDIAN_EXPORT_DIR")
    if raw is None:
        return None
    raw = raw.strip()
    if not raw:
        return None
    return Path(raw)


def obsidian_configured() -> bool:
    return obsidian_export_dir() is not None


def _safe_filename(term: str) -> str:
    # Obsidian-friendly; keep CJK; strip path separators
    name = term.strip().replace("/", "-").replace("\\", "-").replace(":", "：")
    return f"{name}.md"


def _build_new_note(
    *,
    term: str,
    category: str,
    one_liner: str,
    full_md: str,
    encounter: str,
    note: Optional[str] = None,
) -> str:
    added = _today()
    body = (full_md or one_liner or "").strip()
    notes_body = (note or "").strip()
    notes_section = f"{NOTES_HEADING}\n\n"
    if notes_body:
        notes_section += f"{notes_body}\n\n"
    return (
        f"---\n"
        f"term: {term}\n"
        f"category: {category or ''}\n"
        f"added: {added}\n"
        f"---\n\n"
        f"# [[{term}]]\n\n"
        f"{one_liner.strip()}\n\n"
        f"{body}\n\n"
        f"溯源：{encounter}\n\n"
        f"{notes_section}"
    )


def _append_under_notes(text: str, note: str) -> str:
    """Append dated user note under 我的笔记; never delete existing content."""
    note = note.strip()
    if not note:
        return text
    stamped = f"（{_today()}）\n{note}"
    if NOTES_HEADING in text:
        parts = text.split(NOTES_HEADING, 1)
        existing = parts[1]
        # keep leading newlines style
        return (
            parts[0]
            + NOTES_HEADING
            + existing.rstrip()
            + "\n\n"
            + stamped
            + "\n"
        )
    return text.rstrip() + f"\n\n{NOTES_HEADING}\n\n{stamped}\n"


def export_glossary_to_obsidian(
    conn: sqlite3.Connection,
    term: str,
    *,
    context: Optional[str] = None,
    note: Optional[str] = None,
) -> dict[str, Any]:
    """
    Write/update vault note per DESIGN §3.5.5.
    Re-export appends a「再次遇到」line; never overwrites 「我的笔记」 section.
    Optional `note` is appended under 我的笔记.
    Sets state=saved.
    """
    root = obsidian_export_dir()
    if root is None:
        raise RuntimeError("OBSIDIAN_EXPORT_DIR is not configured")

    row = get_glossary_term(conn, term)
    if row is None:
        raise KeyError(term)

    root.mkdir(parents=True, exist_ok=True)
    path = root / _safe_filename(row["term"])
    encounter = context.strip() if context and context.strip() else f"{_today()} 于 Aletheia 遇到"
    category = str(row.get("category") or "")
    user_note = (note or "").strip() or None

    if not path.exists():
        path.write_text(
            _build_new_note(
                term=row["term"],
                category=category,
                one_liner=str(row.get("one_liner") or ""),
                full_md=str(row.get("full_md") or ""),
                encounter=encounter,
                note=user_note,
            ),
            encoding="utf-8",
        )
    else:
        text = path.read_text(encoding="utf-8")
        append_line = f"再次遇到：{encounter}"
        if NOTES_HEADING in text:
            parts = text.split(NOTES_HEADING, 1)
            head = parts[0].rstrip() + "\n\n" + append_line + "\n\n"
            text = head + NOTES_HEADING + parts[1]
        else:
            text = text.rstrip() + "\n\n" + append_line + f"\n\n{NOTES_HEADING}\n\n"
        if user_note:
            text = _append_under_notes(text, user_note)
        path.write_text(text, encoding="utf-8")

    updated = set_glossary_state(conn, row["term"], "saved")
    return {
        "term": row["term"],
        "path": str(path),
        "state": updated["state"] if updated else "saved",
    }
