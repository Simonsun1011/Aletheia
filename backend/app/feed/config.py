"""Load config/feeds.toml."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from backend.app.config import REPO_ROOT

try:
    import tomllib
except ModuleNotFoundError:
    import tomli as tomllib  # type: ignore


@dataclass
class FeedConfig:
    id: str
    name: str
    type: str
    url: str
    enabled: bool = True
    tier: Optional[str] = None
    skip_relevance: bool = False


def feeds_path() -> Path:
    return REPO_ROOT / "config" / "feeds.toml"


def load_feeds(path: Optional[Path] = None) -> list[FeedConfig]:
    p = path or feeds_path()
    data = tomllib.loads(p.read_text(encoding="utf-8"))
    out: list[FeedConfig] = []
    for row in data.get("feeds") or []:
        out.append(
            FeedConfig(
                id=str(row["id"]),
                name=str(row.get("name") or row["id"]),
                type=str(row.get("type") or "rss"),
                url=str(row["url"]),
                enabled=bool(row.get("enabled", True)),
                tier=row.get("tier"),
                skip_relevance=bool(row.get("skip_relevance", False)),
            )
        )
    return out


def enabled_feeds(path: Optional[Path] = None) -> list[FeedConfig]:
    return [f for f in load_feeds(path) if f.enabled]
