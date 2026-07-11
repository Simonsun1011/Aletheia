"""Load config/sector_map.toml."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from backend.app.config import REPO_ROOT

try:
    import tomllib
except ModuleNotFoundError:  # Python < 3.11
    import tomli as tomllib  # type: ignore


def sector_map_path() -> Path:
    return REPO_ROOT / "config" / "sector_map.toml"


def load_sector_etf(symbol: str, path: Optional[Path] = None) -> Optional[str]:
    """
    Return sector ETF ticker for symbol, or None if QQQ-only / unmapped.
    Empty string in toml → None.
    """
    p = path or sector_map_path()
    if not p.exists():
        return None
    data = tomllib.loads(p.read_text(encoding="utf-8"))
    mapping = data.get("map") or {}
    key = symbol.upper()
    if key not in mapping:
        return None
    val = mapping[key]
    if val is None or str(val).strip() == "":
        return None
    return str(val).upper()
