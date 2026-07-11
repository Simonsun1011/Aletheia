"""Title normalization + similarity merge for feed items."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import Any, Optional


def normalize_title(title: str) -> str:
    t = unicodedata.normalize("NFKC", title or "")
    t = t.lower()
    t = re.sub(r"https?://\S+", " ", t)
    t = re.sub(r"[^\w\s]", " ", t, flags=re.UNICODE)
    t = re.sub(r"\s+", " ", t).strip()
    return t


def title_similarity(a: str, b: str) -> float:
    na, nb = normalize_title(a), normalize_title(b)
    if not na or not nb:
        return 0.0
    return SequenceMatcher(None, na, nb).ratio()


@dataclass
class RawItem:
    source: str
    title: str
    url: str
    published_at: Optional[str] = None
    fetched_at: str = ""
    content: str = ""
    objects: list[str] = field(default_factory=list)
    feed_id: str = ""


@dataclass
class DedupGroup:
    title: str
    urls: list[str]
    sources: list[str]
    published_at: Optional[str]
    fetched_at: str
    content: str
    objects: list[str]
    members: list[RawItem] = field(default_factory=list)
    feed_ids: list[str] = field(default_factory=list)


def merge_items(items: list[RawItem], threshold: float = 0.72) -> list[DedupGroup]:
    """
    Greedy cluster by title similarity. Same event from multiple sources
    → one group with multiple urls.
    """
    groups: list[DedupGroup] = []
    for item in items:
        placed = False
        for g in groups:
            if title_similarity(item.title, g.title) >= threshold:
                g.members.append(item)
                if item.url not in g.urls:
                    g.urls.append(item.url)
                if item.source not in g.sources:
                    g.sources.append(item.source)
                for o in item.objects:
                    if o not in g.objects:
                        g.objects.append(o)
                if item.feed_id and item.feed_id not in g.feed_ids:
                    g.feed_ids.append(item.feed_id)
                # prefer earliest published
                if item.published_at and (
                    g.published_at is None or item.published_at < g.published_at
                ):
                    g.published_at = item.published_at
                if len(item.content) > len(g.content):
                    g.content = item.content
                placed = True
                break
        if not placed:
            groups.append(
                DedupGroup(
                    title=item.title,
                    urls=[item.url],
                    sources=[item.source],
                    published_at=item.published_at,
                    fetched_at=item.fetched_at,
                    content=item.content or item.title,
                    objects=list(item.objects),
                    members=[item],
                    feed_ids=[item.feed_id] if item.feed_id else [],
                )
            )
    return groups


def group_to_card_fields(g: DedupGroup) -> dict[str, Any]:
    """Map dedup group to feed_cards columns. Multi-url → JSON array string."""
    import json

    url_field = g.urls[0] if len(g.urls) == 1 else json.dumps(g.urls, ensure_ascii=False)
    return {
        "source": "+".join(g.sources) if len(g.sources) > 1 else (g.sources[0] if g.sources else ""),
        "title": g.title,
        "url": url_field,
        "published_at": g.published_at,
        "fetched_at": g.fetched_at,
        "objects": json.dumps(g.objects, ensure_ascii=False),
        "content": g.content,
        "url_count": len(g.urls),
    }
