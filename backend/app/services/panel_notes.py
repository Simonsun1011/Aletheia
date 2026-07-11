"""Load config/panel_notes.json for console panel explanations."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any, Optional

from backend.app.config import REPO_ROOT


def panel_notes_path() -> Path:
    return REPO_ROOT / "config" / "panel_notes.json"


@lru_cache(maxsize=1)
def load_panel_notes(path: Optional[str] = None) -> dict[str, Any]:
    p = Path(path) if path else panel_notes_path()
    if not p.exists():
        return {}
    return json.loads(p.read_text(encoding="utf-8"))


def panel_note(key: str) -> Optional[dict[str, str]]:
    data = load_panel_notes()
    row = data.get(key)
    if not isinstance(row, dict):
        return None
    title = row.get("title")
    body = row.get("body")
    if not title or not body:
        return None
    return {"title": str(title), "body": str(body)}
