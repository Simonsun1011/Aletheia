"""Digest: dedup raw feed → relevance filter → summarize → feed_cards."""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timezone
from typing import Callable, Optional

from ulid import ULID

from backend.app.ai import adapter as ai_adapter
from backend.app.ai.guard import guard
from backend.app.ai.usage import BudgetExceededError
from backend.app.feed.config import load_feeds
from backend.app.feed.dedup import RawItem, group_to_card_fields, merge_items
from backend.app.feed.relevance import load_relevance
from backend.app.models import FeedCard, FilteredItem
from backend.app.stores.base import AppStore

log = logging.getLogger("aletheia.ai")
jobs_log = logging.getLogger("aletheia.jobs")

SUMMARY_PROMPT = "summarize_card_v1.md"
CompleteFn = Callable[..., ai_adapter.CompletionResult]


def _dedup_group_id(title: str, urls: list[str]) -> str:
    h = hashlib.sha1((title + "|" + "|".join(sorted(urls))).encode()).hexdigest()[:16]
    return f"dg_{h}"


def _watchlist_tickers(store: AppStore) -> list[str]:
    wl = store.list_watchlist()
    return [i.ticker for i in wl.active + wl.shadow]


def digest_batch(
    store: AppStore,
    batch_date: str,
    *,
    complete_fn: Optional[CompleteFn] = None,
) -> dict[str, int]:
    complete = complete_fn or ai_adapter.complete
    skip_ids = {f.id for f in load_feeds() if f.skip_relevance}
    lexicon = load_relevance(watchlist_tickers=_watchlist_tickers(store))

    raw_rows = store.list_feed_raw(batch_date)
    items: list[RawItem] = []
    for r in raw_rows:
        try:
            objs = json.loads(r.get("objects") or "[]")
        except json.JSONDecodeError:
            objs = []
        items.append(
            RawItem(
                source=r.get("source") or "",
                title=r["title"],
                url=r["url"],
                published_at=r.get("published_at"),
                fetched_at=r.get("fetched_at") or "",
                content=r.get("content") or "",
                objects=list(objs),
                feed_id=r.get("feed_id") or "",
            )
        )

    groups = merge_items(items)
    ok = 0
    fail = 0
    filtered = 0
    budget_blocked = False
    for g in groups:
        fields = group_to_card_fields(g)
        published = fields["published_at"]
        fetched = fields["fetched_at"] or datetime.now(timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )

        skip = bool(g.feed_ids) and any(fid in skip_ids for fid in g.feed_ids)
        if not skip:
            hit, matched = lexicon.is_relevant(fields["title"], fields["content"])
            if not hit:
                item = FilteredItem(
                    id=str(ULID()),
                    fetched_at=fetched,
                    source=fields["source"] or None,
                    title=fields["title"],
                    url=g.urls[0] if g.urls else fields["url"],
                    batch_date=batch_date,
                )
                store.insert_filtered_item(item)
                jobs_log.info(
                    "relevance filtered title=%s source=%s",
                    fields["title"][:80],
                    fields["source"],
                )
                filtered += 1
                continue
            # merge matched tickers into objects
            objs = list(g.objects)
            for t in matched:
                if t not in objs:
                    objs.append(t)
            g.objects = objs
            fields = group_to_card_fields(g)
        else:
            # still try to attach tickers if text matches, without filtering
            hit, matched = lexicon.is_relevant(fields["title"], fields["content"])
            if hit and matched:
                objs = list(g.objects)
                for t in matched:
                    if t not in objs:
                        objs.append(t)
                g.objects = objs
                fields = group_to_card_fields(g)

        if budget_blocked:
            jobs_log.error(
                "digest skip LLM (budget) title=%s", fields["title"][:80]
            )
            fail += 1
            continue

        try:
            user_content = (
                f"title: {fields['title']}\n"
                f"source: {fields['source']}\n"
                f"url: {fields['url']}\n"
                f"body:\n{fields['content'][:3000]}"
            )
            result = complete(
                prompt_file=SUMMARY_PROMPT,
                user_content=user_content,
                purpose="summary",
                budget_mode="batch",
            )
            summary = (result.text or "").strip()
            gsum = guard(summary, ruleset="summary")
            if not gsum.ok:
                log.error(
                    "summary iron-law blocked title=%s matched=%s",
                    fields["title"][:80],
                    gsum.matched,
                )
                fail += 1
                continue
            card = FeedCard(
                id=str(ULID()),
                fetched_at=fetched,
                published_at=published or fetched,
                source=fields["source"],
                title=fields["title"],
                url=fields["url"],
                summary=summary,
                objects=fields["objects"],
                dedup_group=_dedup_group_id(fields["title"], g.urls),
                batch_date=batch_date,
            )
            store.upsert_feed_card(card)
            log.info(
                "card saved id=%s urls=%s guard=ok prompt=%s",
                card.id,
                fields.get("url_count", 1),
                SUMMARY_PROMPT,
            )
            ok += 1
        except BudgetExceededError as e:
            budget_blocked = True
            fail += 1
            jobs_log.error("digest budget exceeded: %s", e)
            continue
        except Exception as e:
            fail += 1
            jobs_log.exception(
                "digest item failed title=%s err=%s", fields["title"][:80], e
            )
            continue

    jobs_log.info(
        "digest batch=%s groups=%s ok=%s fail=%s filtered=%s",
        batch_date,
        len(groups),
        ok,
        fail,
        filtered,
    )
    print(
        f"digest {batch_date}: {ok} cards, {fail} errors, "
        f"{filtered} filtered, {len(groups)} groups"
    )
    return {
        "groups": len(groups),
        "ok": ok,
        "fail": fail,
        "filtered": filtered,
        "raw": len(raw_rows),
    }
