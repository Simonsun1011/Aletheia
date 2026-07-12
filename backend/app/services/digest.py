"""Digest: prescreen → dedup survivors → priority → persist title cards.

Slice 3c keeps summaries lazy. Slice 8 v0.12 adds a separate best-effort,
tag-only LLM call after each card is durably persisted.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import time
from datetime import datetime, timezone
from typing import Any, Callable, Optional

from ulid import ULID

# Kept as a module attribute for callers that still monkeypatch the old digest
# completion path. Digest itself never invokes it.
from backend.app.ai import adapter as ai_adapter
from backend.app.feed.config import load_feeds
from backend.app.feed.dedup import RawItem, group_to_card_fields, merge_items
from backend.app.feed.language import language_allowed
from backend.app.feed.priority import score_candidate
from backend.app.feed.relevance import load_relevance
from backend.app.feed.triage import triage
from backend.app.models import FeedCard, FilteredItem
from backend.app.services.tags import active_topics_prompt_lines, apply_ai_tags
from backend.app.stores.base import AppStore

jobs_log = logging.getLogger("aletheia.jobs")

DEFAULT_FEED_DISPLAY_MAX = 40
CompleteFn = Callable[..., Any]
StopFn = Callable[[], bool]
ProgressFn = Callable[..., None]


def _feed_display_max() -> int:
    raw = os.environ.get("FEED_DISPLAY_MAX", "").strip()
    if not raw:
        return DEFAULT_FEED_DISPLAY_MAX
    try:
        return max(0, int(raw))
    except ValueError:
        return DEFAULT_FEED_DISPLAY_MAX


def _prescreen_audit_enabled() -> bool:
    """When on, primary-screen discards are written for temporary tuning."""
    return os.environ.get("FEED_PRESCREEN_AUDIT", "").strip().lower() in (
        "1",
        "true",
        "yes",
    )


def _prescreen_keep(
    item: RawItem,
    *,
    lexicon: Any,
    skip_ids: set[str],
) -> tuple[bool, str]:
    """Cheap primary screen; quality checks are never bypassed by relevance."""
    ok_lang, lang = language_allowed(item.title, item.content or "")
    if not ok_lang:
        return False, f"language:{lang}"
    if lexicon.is_blocked(item.title, item.content or ""):
        return False, "blocklist"
    quality_reason = lexicon.quality_reason(item.source, item.title, item.url)
    if quality_reason:
        return False, quality_reason
    skip_relevance = bool(item.feed_id) and item.feed_id in skip_ids
    if not skip_relevance:
        hit, _ = lexicon.is_relevant(item.title, item.content or "")
        if not hit:
            return False, "relevance"
    return True, ""


def _existing_card_keys(store: AppStore, batch_date: str) -> tuple[set[str], set[str]]:
    """Return (dedup_groups, urls) already persisted for this batch."""
    groups: set[str] = set()
    urls: set[str] = set()
    for card in store.list_feed_cards(batch_date=batch_date, days=1):
        if card.dedup_group:
            groups.add(card.dedup_group)
        value = card.url or ""
        if value.startswith("["):
            try:
                parsed = json.loads(value)
                if isinstance(parsed, list):
                    urls.update(str(url) for url in parsed if url)
                    continue
            except json.JSONDecodeError:
                pass
        if value:
            urls.add(value)
    return groups, urls


def _dedup_group_id(title: str, urls: list[str]) -> str:
    digest = hashlib.sha1(
        (title + "|" + "|".join(sorted(urls))).encode()
    ).hexdigest()[:16]
    return f"dg_{digest}"


def _watchlist_tickers(store: AppStore) -> list[str]:
    watchlist = store.list_watchlist()
    return [item.ticker for item in watchlist.active + watchlist.shadow]


def parse_digest_llm_text(text: str) -> tuple[str, list[str], list[str]]:
    """Legacy parser retained for compatibility; digest no longer calls it."""
    raw = (text or "").strip()
    if not raw:
        return "", [], []
    fenced = re.match(r"^```(?:json)?\s*([\s\S]*?)\s*```$", raw)
    if fenced:
        raw = fenced.group(1).strip()
    if raw.startswith("{"):
        try:
            data = json.loads(raw)
            if isinstance(data, dict):
                summary = str(data.get("summary") or "").strip()
                tags = data.get("tags") or []
                suggestions = data.get("tag_suggestions") or []
                return (
                    summary,
                    [str(tag).strip() for tag in tags if str(tag).strip()]
                    if isinstance(tags, list)
                    else [],
                    [
                        str(suggestion).strip()
                        for suggestion in suggestions
                        if str(suggestion).strip()
                    ]
                    if isinstance(suggestions, list)
                    else [],
                )
        except json.JSONDecodeError:
            pass
    return raw, [], []


def parse_tag_llm_text(text: str) -> tuple[list[str], list[str]]:
    """Parse tag-only JSON independently from legacy summary payloads."""
    raw = (text or "").strip()
    fenced = re.match(r"^```(?:json)?\s*([\s\S]*?)\s*```$", raw)
    if fenced:
        raw = fenced.group(1).strip()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return [], []
    if not isinstance(data, dict):
        return [], []
    tags = data.get("tags")
    suggestions = data.get("tag_suggestions")
    return (
        [str(v).strip() for v in tags if str(v).strip()]
        if isinstance(tags, list)
        else [],
        [str(v).strip() for v in suggestions if str(v).strip()]
        if isinstance(suggestions, list)
        else [],
    )


def _first_paragraph(content: str, limit: int = 1500) -> str:
    """Persist the first non-empty source paragraph as lazy-summary input."""
    text = (content or "").strip()
    if not text:
        return ""
    paragraphs = re.split(r"(?:\r?\n){2,}", text)
    first = next((p.strip() for p in paragraphs if p.strip()), text)
    return first[:limit]


def digest_batch(
    store: AppStore,
    batch_date: str,
    *,
    complete_fn: Optional[CompleteFn] = None,
    on_progress: Optional[ProgressFn] = None,
    should_stop: Optional[StopFn] = None,
    display_max: Optional[int] = None,
    max_llm: Optional[int] = None,
) -> dict[str, int]:
    """Build all surviving cards; summaries remain empty.

    Tag-only calls are best effort and never decide card survival.
    """
    complete = complete_fn or ai_adapter.complete
    if display_max is None:
        display_max = max_llm if max_llm is not None else _feed_display_max()
    display_limit = max(0, int(display_max))

    skip_ids = {feed.id for feed in load_feeds() if feed.skip_relevance}
    lexicon = load_relevance(watchlist_tickers=_watchlist_tickers(store))
    seen_groups, seen_urls = _existing_card_keys(store, batch_date)
    raw_rows = store.list_feed_raw(batch_date)
    raw_n = len(raw_rows)

    filtered = 0
    prescreen_discarded = 0
    skipped_existing = 0
    cancelled = False
    survivors_n = 0
    groups: list[Any] = []
    ok = 0
    fail = 0
    folded = 0

    def emit(msg: str, *, force: bool = False, **detail: Any) -> None:
        if not on_progress:
            return
        now = time.monotonic()
        if not force and now - emit.last < 0.75:  # type: ignore[attr-defined]
            return
        emit.last = now  # type: ignore[attr-defined]
        payload = {
            "step": detail.get("step", "digest"),
            "raw": raw_n,
            "scanned": detail.get("scanned"),
            "groups": detail.get("groups"),
            "filtered": detail.get("filtered", filtered),
            "prescreen_discarded": detail.get(
                "prescreen_discarded", prescreen_discarded
            ),
            "survivors": detail.get("survivors", survivors_n),
            "skipped_existing": detail.get("skipped_existing"),
            "cards_ok": detail.get("cards_ok"),
            "display_max": display_limit,
            "folded": detail.get("folded"),
            "fail": detail.get("fail"),
            "current_title": detail.get("current_title"),
            "hint": detail.get("hint"),
        }
        try:
            on_progress(msg, {key: value for key, value in payload.items() if value is not None})
        except TypeError:
            on_progress(msg)

    emit.last = 0.0  # type: ignore[attr-defined]
    audit = _prescreen_audit_enabled()

    try:
        emit(
            f"初筛原始稿 {raw_n} 条（语言 / 负向 / 质量 / 相关性）…",
            force=True,
            step="digest_prescreen",
            hint="廉价确定性过滤，先砍量再去重",
        )
        survivors: list[RawItem] = []
        for index, row in enumerate(raw_rows):
            if should_stop and should_stop():
                cancelled = True
                emit(
                    f"已停止（初筛丢弃 {prescreen_discarded}）",
                    force=True,
                    step="digest_cancelled",
                    scanned=index,
                    cards_ok=0,
                    folded=0,
                )
                break
            try:
                objects = json.loads(row.get("objects") or "[]")
            except json.JSONDecodeError:
                objects = []
            item = RawItem(
                source=row.get("source") or "",
                title=row["title"],
                url=row["url"],
                published_at=row.get("published_at"),
                fetched_at=row.get("fetched_at") or "",
                content=row.get("content") or "",
                objects=list(objects),
                feed_id=row.get("feed_id") or "",
            )
            keep, reason = _prescreen_keep(
                item, lexicon=lexicon, skip_ids=skip_ids
            )
            if not keep:
                prescreen_discarded += 1
                if audit:
                    fetched_at = item.fetched_at or datetime.now(
                        timezone.utc
                    ).strftime("%Y-%m-%dT%H:%M:%SZ")
                    store.insert_filtered_item(
                        FilteredItem(
                            id=str(ULID()),
                            fetched_at=fetched_at,
                            source=item.source or None,
                            title=item.title,
                            url=item.url,
                            batch_date=batch_date,
                        )
                    )
                jobs_log.info(
                    "prescreen discarded reason=%s title=%s source=%s",
                    reason,
                    item.title[:80],
                    item.source,
                )
            else:
                survivors.append(item)
            if index == 0 or (index + 1) % 50 == 0 or index + 1 == raw_n:
                emit(
                    f"初筛 {index + 1}/{raw_n} · 丢弃 {prescreen_discarded} · "
                    f"幸存 {len(survivors)}",
                    step="digest_prescreen",
                    scanned=index + 1,
                    cards_ok=0,
                    folded=0,
                )

        survivors_n = len(survivors)
        if cancelled:
            return {
                "groups": 0,
                "ok": 0,
                "fail": 0,
                "filtered": filtered,
                "prescreen_discarded": prescreen_discarded,
                "survivors": survivors_n,
                "raw": raw_n,
                "skipped_existing": 0,
                "folded": 0,
                "cancelled": 1,
                "display_max": display_limit,
            }

        emit(
            f"去重幸存集 {survivors_n} 条…",
            force=True,
            step="digest_dedup",
            hint="去重只在初筛幸存集上跑",
        )
        groups = merge_items(survivors)
        total_groups = len(groups)
        candidates: list[dict[str, Any]] = []

        for group_index, group in enumerate(groups):
            if should_stop and should_stop():
                cancelled = True
                break
            fields = group_to_card_fields(group)
            dedup = _dedup_group_id(fields["title"], group.urls)
            if dedup in seen_groups or any(url in seen_urls for url in group.urls):
                skipped_existing += 1
                continue

            detail = lexicon.match_detail(fields["title"], fields["content"])
            objects = list(group.objects)
            for ticker in detail.get("matched") or []:
                if ticker not in objects:
                    objects.append(ticker)
            group.objects = objects
            fields = group_to_card_fields(group)
            fetched = fields["fetched_at"] or datetime.now(timezone.utc).strftime(
                "%Y-%m-%dT%H:%M:%SZ"
            )
            candidates.append(
                {
                    "fields": fields,
                    "group": group,
                    "dedup": dedup,
                    "fetched": fetched,
                    "detail": detail,
                }
            )
            if (
                group_index == 0
                or (group_index + 1) % 10 == 0
                or group_index + 1 == total_groups
            ):
                emit(
                    f"候选收集 {group_index + 1}/{total_groups} · "
                    f"跳过已入卡 {skipped_existing} · 候选 {len(candidates)}",
                    step="digest_scan",
                    scanned=group_index + 1,
                    groups=total_groups,
                    skipped_existing=skipped_existing,
                    cards_ok=0,
                    folded=0,
                )

        if not cancelled:
            watchlist = store.list_watchlist()
            tier_by = {
                item.ticker.upper(): item.tier
                for item in watchlist.active + watchlist.shadow
            }
            for candidate in candidates:
                fields = candidate["fields"]
                group = candidate["group"]
                detail = candidate["detail"]
                try:
                    object_list = [
                        str(value)
                        for value in json.loads(fields["objects"] or "[]")
                    ]
                except json.JSONDecodeError:
                    object_list = []
                priority = score_candidate(
                    title=fields["title"],
                    content=fields["content"] or "",
                    source=fields["source"] or "",
                    feed_ids=list(group.feed_ids),
                    objects=object_list,
                    url_count=len(group.urls),
                    published_at=fields["published_at"],
                    title_hit_tickers=detail.get("title_tickers") or [],
                    body_hit_tickers=detail.get("body_tickers") or [],
                    theme_hit=bool(detail.get("theme_hit")),
                    tier_by_ticker=tier_by,
                )
                candidate["priority_score"] = priority.score + (
                    triage(fields["title"], (fields["content"] or "")[:300]) * 5
                )
                candidate["priority_reasons"] = priority.reasons
                candidate["object_list"] = object_list

            candidates.sort(
                key=lambda candidate: candidate["priority_score"], reverse=True
            )
            folded_target = max(0, len(candidates) - display_limit)
            emit(
                f"优先级排序完成：{len(candidates)} 候选，"
                f"主列表 {min(display_limit, len(candidates))}，折叠 {folded_target}",
                force=True,
                step="digest_scored",
                groups=total_groups,
                skipped_existing=skipped_existing,
                cards_ok=0,
                folded=folded_target,
                hint="全部候选持久化；展示上限之外默认折叠",
            )

            for index, candidate in enumerate(candidates):
                if should_stop and should_stop():
                    cancelled = True
                    break
                fields = candidate["fields"]
                group = candidate["group"]
                is_folded = int(index >= display_limit)
                try:
                    card = FeedCard(
                        id=str(ULID()),
                        fetched_at=candidate["fetched"],
                        published_at=fields["published_at"]
                        or candidate["fetched"],
                        source=fields["source"],
                        title=fields["title"],
                        url=fields["url"],
                        excerpt=_first_paragraph(fields["content"] or ""),
                        summary=None,
                        objects=fields["objects"],
                        dedup_group=candidate["dedup"],
                        batch_date=batch_date,
                        folded=is_folded,
                        priority_score=candidate["priority_score"],
                        priority_reasons=json.dumps(
                            candidate["priority_reasons"], ensure_ascii=False
                        ),
                    )
                    store.upsert_feed_card(card)
                    apply_ai_tags(
                        store,
                        card.id,
                        tags=[],
                        suggestions=[],
                        object_tickers=candidate["object_list"],
                    )
                    try:
                        system = ai_adapter.load_prompt("tag_card_v1.md").replace(
                            "{{ACTIVE_TOPICS}}", active_topics_prompt_lines(store)
                        )
                        result = complete(
                            prompt_file="tag_card_v1.md",
                            user_content=(
                                f"title: {card.title}\n"
                                f"excerpt: {card.excerpt or ''}\n"
                            ),
                            purpose="other",
                            budget_mode="batch",
                            system_override=system,
                        )
                        tag_ids, suggestions = parse_tag_llm_text(result.text)
                        apply_ai_tags(
                            store,
                            card.id,
                            tags=tag_ids,
                            suggestions=suggestions,
                            object_tickers=[],
                        )
                    except Exception as tag_error:
                        jobs_log.warning(
                            "tag-only LLM failed; card kept id=%s err=%s",
                            card.id,
                            type(tag_error).__name__,
                        )
                    seen_groups.add(candidate["dedup"])
                    seen_urls.update(group.urls)
                    ok += 1
                    folded += is_folded
                    emit(
                        f"持久化卡片 {ok}/{len(candidates)} · 折叠 {folded}",
                        step="digest_persist",
                        groups=total_groups,
                        cards_ok=ok,
                        folded=folded,
                        fail=fail,
                        current_title=fields["title"],
                        hint="保存标题、首段、标签与优先级；摘要按需生成",
                    )
                except Exception as error:
                    fail += 1
                    jobs_log.exception(
                        "digest card failed title=%s err=%s",
                        fields["title"][:80],
                        error,
                    )

        jobs_log.info(
            "digest batch=%s raw=%s survivors=%s groups=%s ok=%s folded=%s "
            "fail=%s prescreen_discarded=%s filtered=%s skipped_existing=%s "
            "display_max=%s cancelled=%s",
            batch_date,
            raw_n,
            survivors_n,
            len(groups),
            ok,
            folded,
            fail,
            prescreen_discarded,
            filtered,
            skipped_existing,
            display_limit,
            cancelled,
        )
        return {
            "groups": len(groups),
            "ok": ok,
            "fail": fail,
            "filtered": filtered,
            "prescreen_discarded": prescreen_discarded,
            "survivors": survivors_n,
            "raw": raw_n,
            "skipped_existing": skipped_existing,
            "folded": folded,
            "cancelled": int(cancelled),
            "display_max": display_limit,
        }
    finally:
        try:
            deleted = store.delete_feed_raw(batch_date=batch_date)
            if deleted:
                jobs_log.info(
                    "feed_raw discarded batch=%s rows=%s", batch_date, deleted
                )
        except Exception:
            jobs_log.exception("feed_raw discard failed batch=%s", batch_date)
