"""Apply relevance whitelist to existing feed_cards (read-path + purge)."""

from __future__ import annotations

import json
import logging
from typing import Optional

from ulid import ULID

from backend.app.feed.config import load_feeds
from backend.app.feed.language import (
    is_translated_from_english,
    language_allowed,
)
from backend.app.feed.relevance import RelevanceLexicon, load_relevance
from backend.app.models import FeedCard, FilteredItem
from backend.app.stores.base import AppStore

log = logging.getLogger("aletheia.jobs")


def _skip_source_names() -> set[str]:
    feeds = load_feeds()
    names: set[str] = set()
    for f in feeds:
        if f.skip_relevance:
            names.add(f.name)
            names.add(f.id)
    return names


def source_skips_relevance(source: Optional[str]) -> bool:
    if not source:
        return False
    skip = _skip_source_names()
    for part in source.split("+"):
        if part.strip() in skip:
            return True
    return False


def card_is_relevant(card: FeedCard, lexicon: RelevanceLexicon) -> bool:
    """True if card should appear in the briefing."""
    body = card.summary or ""
    # Language: drop Romance/etc.; drop EN title with JA/ZH summary (translated)
    ok_lang, _ = language_allowed(card.title, body)
    if not ok_lang:
        return False
    if is_translated_from_english(card.title, body):
        return False
    # Slice 3c: blocklist applies even to skip_relevance / object-linked cards
    if lexicon.is_blocked(card.title, body):
        return False
    if source_skips_relevance(card.source):
        return True
    try:
        objs = json.loads(card.objects or "[]")
    except json.JSONDecodeError:
        objs = []
    if objs:
        # already linked to tickers at digest time
        return True
    hit, _ = lexicon.is_relevant(card.title, body)
    return hit


def lexicon_for_store(store: AppStore) -> RelevanceLexicon:
    wl = store.list_watchlist()
    tickers = [i.ticker for i in wl.active + wl.shadow]
    return load_relevance(watchlist_tickers=tickers)


def filter_cards(
    store: AppStore, cards: list[FeedCard], *, purge: bool = True
) -> tuple[list[FeedCard], int]:
    """
    Keep relevant cards. If purge=True, move irrelevant ones to filtered_items
    and delete from feed_cards so they never reappear.
    Returns (kept, purged_count).
    """
    if not cards:
        return [], 0
    lexicon = lexicon_for_store(store)
    kept: list[FeedCard] = []
    purged = 0
    for card in cards:
        if card_is_relevant(card, lexicon):
            kept.append(card)
            continue
        if purge:
            url = card.url
            try:
                parsed = json.loads(card.url)
                if isinstance(parsed, list) and parsed:
                    url = parsed[0]
            except json.JSONDecodeError:
                pass
            store.insert_filtered_item(
                FilteredItem(
                    id=str(ULID()),
                    fetched_at=card.fetched_at,
                    source=card.source,
                    title=card.title,
                    url=url,
                    batch_date=card.batch_date,
                )
            )
            deleter = getattr(store, "delete_feed_card", None)
            if callable(deleter):
                deleter(card.id)
            log.info(
                "purged irrelevant card id=%s title=%s",
                card.id,
                card.title[:80],
            )
            purged += 1
    return kept, purged
