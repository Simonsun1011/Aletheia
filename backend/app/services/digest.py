"""Digest: dedup raw feed → relevance filter → summarize+tag → feed_cards."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
from datetime import datetime, timezone
from typing import Callable, Optional

from ulid import ULID

from backend.app.ai import adapter as ai_adapter
from backend.app.ai.guard import guard
from backend.app.ai.usage import BudgetExceededError
from backend.app.feed.config import load_feeds
from backend.app.feed.dedup import RawItem, group_to_card_fields, merge_items
from backend.app.feed.language import language_allowed, is_translated_from_english
from backend.app.feed.relevance import load_relevance
from backend.app.models import FeedCard, FilteredItem
from backend.app.services.tags import active_topics_prompt_lines, apply_ai_tags
from backend.app.stores.base import AppStore

log = logging.getLogger("aletheia.ai")
jobs_log = logging.getLogger("aletheia.jobs")

SUMMARY_PROMPT = "summarize_card_v2.md"
# Hard cap: ticker RSS × watchlist explodes; keep interactive refresh usable.
DEFAULT_DIGEST_MAX_LLM = 40
CompleteFn = Callable[..., ai_adapter.CompletionResult]
StopFn = Callable[[], bool]


def _digest_max_llm() -> int:
    raw = os.environ.get("DIGEST_MAX_LLM", "").strip()
    if not raw:
        return DEFAULT_DIGEST_MAX_LLM
    try:
        return max(1, int(raw))
    except ValueError:
        return DEFAULT_DIGEST_MAX_LLM


def _existing_card_keys(store: AppStore, batch_date: str) -> tuple[set[str], set[str]]:
    """Return (dedup_groups, urls) already in feed_cards for this batch."""
    groups: set[str] = set()
    urls: set[str] = set()
    for c in store.list_feed_cards(batch_date=batch_date, days=1):
        if c.dedup_group:
            groups.add(c.dedup_group)
        u = c.url or ""
        if u.startswith("["):
            try:
                parsed = json.loads(u)
                if isinstance(parsed, list):
                    for x in parsed:
                        if x:
                            urls.add(str(x))
                    continue
            except json.JSONDecodeError:
                pass
        if u:
            urls.add(u)
    return groups, urls


def _dedup_group_id(title: str, urls: list[str]) -> str:
    h = hashlib.sha1((title + "|" + "|".join(sorted(urls))).encode()).hexdigest()[:16]
    return f"dg_{h}"


def _watchlist_tickers(store: AppStore) -> list[str]:
    wl = store.list_watchlist()
    return [i.ticker for i in wl.active + wl.shadow]


def _load_prompt_with_topics(store: AppStore) -> str:
    raw = ai_adapter.load_prompt(SUMMARY_PROMPT)
    return raw.replace("{{ACTIVE_TOPICS}}", active_topics_prompt_lines(store))


def parse_digest_llm_text(text: str) -> tuple[str, list[str], list[str]]:
    """Return (summary, tags, suggestions). Plain text → summary only."""
    raw = (text or "").strip()
    if not raw:
        return "", [], []
    # Strip optional markdown fence
    fenced = re.match(r"^```(?:json)?\s*([\s\S]*?)\s*```$", raw)
    if fenced:
        raw = fenced.group(1).strip()
    if raw.startswith("{"):
        try:
            data = json.loads(raw)
            if isinstance(data, dict):
                summary = str(data.get("summary") or "").strip()
                tags = data.get("tags") or []
                sug = data.get("tag_suggestions") or []
                if not isinstance(tags, list):
                    tags = []
                if not isinstance(sug, list):
                    sug = []
                return (
                    summary,
                    [str(t).strip() for t in tags if str(t).strip()],
                    [str(t).strip() for t in sug if str(t).strip()],
                )
        except json.JSONDecodeError:
            pass
    return raw, [], []


def digest_batch(
    store: AppStore,
    batch_date: str,
    *,
    complete_fn: Optional[CompleteFn] = None,
    on_progress: Optional[Callable[[str], None]] = None,
    should_stop: Optional[StopFn] = None,
    max_llm: Optional[int] = None,
) -> dict[str, int]:
    complete = complete_fn or ai_adapter.complete
    skip_ids = {f.id for f in load_feeds() if f.skip_relevance}
    lexicon = load_relevance(watchlist_tickers=_watchlist_tickers(store))
    system_prompt = _load_prompt_with_topics(store)
    llm_cap = max_llm if max_llm is not None else _digest_max_llm()
    seen_groups, seen_urls = _existing_card_keys(store, batch_date)

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
    skipped_existing = 0
    capped = 0
    cancelled = False
    budget_blocked = False
    total_groups = len(groups)
    for gi, g in enumerate(groups):
        if should_stop and should_stop():
            cancelled = True
            jobs_log.info(
                "digest cancelled at %s/%s ok=%s filtered=%s",
                gi + 1,
                total_groups,
                ok,
                filtered,
            )
            if on_progress:
                on_progress(f"已停止（入卡 {ok}）")
            break
        if on_progress and (gi == 0 or (gi + 1) % 5 == 0 or gi + 1 == total_groups):
            on_progress(
                f"摘要候选 {gi + 1}/{total_groups} · 已入卡 {ok}/{llm_cap}"
            )
        fields = group_to_card_fields(g)
        published = fields["published_at"]
        fetched = fields["fetched_at"] or datetime.now(timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
        dedup = _dedup_group_id(fields["title"], g.urls)
        if dedup in seen_groups or any(u in seen_urls for u in g.urls):
            skipped_existing += 1
            continue

        skip = bool(g.feed_ids) and any(fid in skip_ids for fid in g.feed_ids)
        # Language gate (EN-first; JA/native ZH ok; Romance/etc. out)
        ok_lang, lang = language_allowed(fields["title"], fields["content"])
        if not ok_lang:
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
                "language filtered lang=%s title=%s source=%s",
                lang,
                fields["title"][:80],
                fields["source"],
            )
            filtered += 1
            continue
        # Slice 3c: blocklist wins even for skip_relevance sources
        if lexicon.is_blocked(fields["title"], fields["content"]):
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
                "blocklist filtered title=%s source=%s",
                fields["title"][:80],
                fields["source"],
            )
            filtered += 1
            continue
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
            objs = list(g.objects)
            for t in matched:
                if t not in objs:
                    objs.append(t)
            g.objects = objs
            fields = group_to_card_fields(g)
        else:
            hit, matched = lexicon.is_relevant(fields["title"], fields["content"])
            if hit and matched:
                objs = list(g.objects)
                for t in matched:
                    if t not in objs:
                        objs.append(t)
                g.objects = objs
                fields = group_to_card_fields(g)

        if ok >= llm_cap:
            capped += 1
            continue

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
                system_override=system_prompt,
            )
            summary, tags, suggestions = parse_digest_llm_text(result.text or "")
            if not summary:
                fail += 1
                continue
            if is_translated_from_english(fields["title"], summary):
                log.warning(
                    "summary language mismatch (EN→JA/ZH) dropped title=%s",
                    fields["title"][:80],
                )
                fail += 1
                continue
            gsum = guard(summary, ruleset="summary")
            if not gsum.ok:
                log.error(
                    "summary iron-law blocked title=%s matched=%s",
                    fields["title"][:80],
                    gsum.matched,
                )
                fail += 1
                continue
            try:
                object_list = json.loads(fields["objects"] or "[]")
            except json.JSONDecodeError:
                object_list = []
            card = FeedCard(
                id=str(ULID()),
                fetched_at=fetched,
                published_at=published or fetched,
                source=fields["source"],
                title=fields["title"],
                url=fields["url"],
                summary=summary,
                objects=fields["objects"],
                dedup_group=dedup,
                batch_date=batch_date,
            )
            store.upsert_feed_card(card)
            apply_ai_tags(
                store,
                card.id,
                tags=tags,
                suggestions=suggestions,
                object_tickers=[str(x) for x in object_list],
            )
            seen_groups.add(dedup)
            for u in g.urls:
                seen_urls.add(u)
            log.info(
                "card saved id=%s urls=%s tags=%s guard=ok prompt=%s",
                card.id,
                fields.get("url_count", 1),
                tags,
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

    if capped and on_progress and not cancelled:
        on_progress(f"本批摘要上限 {llm_cap}，其余 {capped} 条留待下次")

    jobs_log.info(
        "digest batch=%s groups=%s ok=%s fail=%s filtered=%s "
        "skipped_existing=%s capped=%s cancelled=%s",
        batch_date,
        len(groups),
        ok,
        fail,
        filtered,
        skipped_existing,
        capped,
        cancelled,
    )
    print(
        f"digest {batch_date}: {ok} cards, {fail} errors, "
        f"{filtered} filtered, {len(groups)} groups"
        + (f", capped={capped}" if capped else "")
        + (", cancelled" if cancelled else "")
    )
    return {
        "groups": len(groups),
        "ok": ok,
        "fail": fail,
        "filtered": filtered,
        "raw": len(raw_rows),
        "skipped_existing": skipped_existing,
        "capped": capped,
        "cancelled": int(cancelled),
        "max_llm": llm_cap,
    }
