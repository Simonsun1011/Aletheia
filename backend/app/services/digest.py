"""Digest: prescreen → dedup survivors → priority → summarize+tag → feed_cards.

Slice 3c: cheap primary screen runs before dedup; feed_raw is discarded after digest.
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

from backend.app.ai import adapter as ai_adapter
from backend.app.ai.guard import guard
from backend.app.ai.usage import BudgetExceededError
from backend.app.feed.config import load_feeds
from backend.app.feed.dedup import RawItem, group_to_card_fields, merge_items
from backend.app.feed.language import language_allowed, is_translated_from_english
from backend.app.feed.priority import score_candidate
from backend.app.feed.relevance import load_relevance
from backend.app.feed.triage import triage
from backend.app.models import FeedCard, FilteredItem
from backend.app.services.tags import active_topics_prompt_lines, apply_ai_tags
from backend.app.stores.base import AppStore

log = logging.getLogger("aletheia.ai")
jobs_log = logging.getLogger("aletheia.jobs")

SUMMARY_PROMPT = "summarize_card_v2.md"
DEFAULT_DIGEST_MAX_LLM = 40
CompleteFn = Callable[..., ai_adapter.CompletionResult]
StopFn = Callable[[], bool]
ProgressFn = Callable[..., None]


def _digest_max_llm() -> int:
    raw = os.environ.get("DIGEST_MAX_LLM", "").strip()
    if not raw:
        return DEFAULT_DIGEST_MAX_LLM
    try:
        return max(1, int(raw))
    except ValueError:
        return DEFAULT_DIGEST_MAX_LLM


def _prescreen_audit_enabled() -> bool:
    """When on, primary-screen discards are also written to filtered_items (tuning)."""
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
    """Cheap primary screen: language → blocklist → relevance (unless skip_relevance).

    Returns (keep, reason). reason is empty when kept.
    """
    ok_lang, lang = language_allowed(item.title, item.content or "")
    if not ok_lang:
        return False, f"language:{lang}"
    if lexicon.is_blocked(item.title, item.content or ""):
        return False, "blocklist"
    skip = bool(item.feed_id) and item.feed_id in skip_ids
    if not skip:
        hit, _ = lexicon.is_relevant(item.title, item.content or "")
        if not hit:
            return False, "relevance"
    return True, ""


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
    on_progress: Optional[ProgressFn] = None,
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
    raw_n = len(raw_rows)
    # filtered = secondary triage rejects in filtered_items (viewable "漏杀")
    filtered = 0
    prescreen_discarded = 0
    skipped_existing = 0
    cancelled = False
    groups: list[Any] = []
    total_groups = 0
    ok = 0
    fail = 0
    folded_ok = 0
    survivors_n = 0

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
            "folded": detail.get("folded"),
            "llm_cap": llm_cap,
            "fail": detail.get("fail"),
            "current_title": detail.get("current_title"),
            "hint": detail.get("hint"),
        }
        try:
            on_progress(msg, {k: v for k, v in payload.items() if v is not None})
        except TypeError:
            on_progress(msg)

    emit.last = 0.0  # type: ignore[attr-defined]
    audit = _prescreen_audit_enabled()

    try:
        emit(
            f"初筛原始稿 {raw_n} 条（语言 / 负向 / 相关性）…",
            force=True,
            step="digest_prescreen",
            hint="廉价关键词过滤，先砍量再去重",
        )

        survivors: list[RawItem] = []
        for i, r in enumerate(raw_rows):
            if should_stop and should_stop():
                cancelled = True
                jobs_log.info(
                    "digest cancelled (prescreen) at %s/%s discarded=%s",
                    i + 1,
                    raw_n,
                    prescreen_discarded,
                )
                emit(
                    f"已停止（初筛丢弃 {prescreen_discarded}）",
                    force=True,
                    step="digest_cancelled",
                    scanned=i + 1,
                    cards_ok=0,
                )
                break

            try:
                objs = json.loads(r.get("objects") or "[]")
            except json.JSONDecodeError:
                objs = []
            item = RawItem(
                source=r.get("source") or "",
                title=r["title"],
                url=r["url"],
                published_at=r.get("published_at"),
                fetched_at=r.get("fetched_at") or "",
                content=r.get("content") or "",
                objects=list(objs),
                feed_id=r.get("feed_id") or "",
            )
            keep, reason = _prescreen_keep(
                item, lexicon=lexicon, skip_ids=skip_ids
            )
            if not keep:
                prescreen_discarded += 1
                if audit:
                    fetched = item.fetched_at or datetime.now(timezone.utc).strftime(
                        "%Y-%m-%dT%H:%M:%SZ"
                    )
                    store.insert_filtered_item(
                        FilteredItem(
                            id=str(ULID()),
                            fetched_at=fetched,
                            source=item.source or None,
                            title=item.title,
                            url=item.url,
                            batch_date=batch_date,
                        )
                    )
                if i == 0 or (i + 1) % 50 == 0 or i + 1 == raw_n:
                    emit(
                        f"初筛 {i + 1}/{raw_n} · 丢弃 {prescreen_discarded} · "
                        f"幸存 {len(survivors)}",
                        step="digest_prescreen",
                        scanned=i + 1,
                        cards_ok=0,
                    )
                jobs_log.info(
                    "prescreen discarded reason=%s title=%s source=%s",
                    reason,
                    item.title[:80],
                    item.source,
                )
                continue
            survivors.append(item)
            if i == 0 or (i + 1) % 50 == 0 or i + 1 == raw_n:
                emit(
                    f"初筛 {i + 1}/{raw_n} · 丢弃 {prescreen_discarded} · "
                    f"幸存 {len(survivors)}",
                    step="digest_prescreen",
                    scanned=i + 1,
                    cards_ok=0,
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
                "capped": 0,
                "cancelled": 1,
                "max_llm": llm_cap,
            }

        emit(
            f"去重幸存集 {survivors_n} 条…",
            force=True,
            step="digest_dedup",
            hint="去重只在初筛幸存集上跑",
        )

        groups = merge_items(survivors)
        total_groups = len(groups)
        emit(
            f"去重后 {total_groups} 组 · 本批最多摘要 {llm_cap} 条",
            force=True,
            step="digest_scan",
            groups=total_groups,
            cards_ok=0,
            hint="初筛已完成；此处只跳过已入卡并收集优先分候选",
        )

        def _scan_msg(gi: int, candidate_count: int) -> str:
            return (
                f"候选收集 {gi}/{total_groups} · 初筛丢 {prescreen_discarded} · "
                f"跳过已入卡 {skipped_existing} · 候选 {candidate_count}"
            )

        # ── Pass 1: collect candidates (already pre-screened; no LLM) ─────────

        candidates: list[dict[str, Any]] = []

        for gi, g in enumerate(groups):
            if should_stop and should_stop():
                cancelled = True
                jobs_log.info(
                    "digest cancelled (pass1) at %s/%s survivors=%s",
                    gi + 1,
                    total_groups,
                    survivors_n,
                )
                emit(
                    f"已停止（候选 {len(candidates)}）",
                    force=True,
                    step="digest_cancelled",
                    scanned=gi + 1,
                    groups=total_groups,
                    filtered=filtered,
                    skipped_existing=skipped_existing,
                    cards_ok=0,
                )
                break

            if gi == 0 or (gi + 1) % 10 == 0 or gi + 1 == total_groups:
                emit(
                    _scan_msg(gi + 1, len(candidates)),
                    step="digest_scan",
                    scanned=gi + 1,
                    groups=total_groups,
                    filtered=filtered,
                    skipped_existing=skipped_existing,
                    cards_ok=0,
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

            # Match detail for priority / objects (items already passed primary screen)
            md = lexicon.match_detail(fields["title"], fields["content"])
            matched = md.get("matched") or []
            objs = list(g.objects)
            for t in matched:
                if t not in objs:
                    objs.append(t)
            g.objects = objs
            fields = group_to_card_fields(g)

            candidates.append(
                {
                    "gi": gi,
                    "fields": fields,
                    "g": g,
                    "dedup": dedup,
                    "fetched": fetched,
                    "published": published,
                    "md": md,
                }
            )

        # ── Compute priority scores + sort ───────────────────────────────────

        wl = store.list_watchlist()
        tier_by: dict[str, str] = {
            i.ticker.upper(): i.tier for i in wl.active + wl.shadow
        }

        for c in candidates:
            fields = c["fields"]
            md = c["md"]
            g = c["g"]
            try:
                obj_list: list[str] = [
                    str(x) for x in json.loads(fields["objects"] or "[]")
                ]
            except json.JSONDecodeError:
                obj_list = []

            pr = score_candidate(
                title=fields["title"],
                content=fields["content"] or "",
                source=fields["source"] or "",
                feed_ids=list(g.feed_ids),
                objects=obj_list,
                url_count=len(g.urls),
                published_at=fields["published_at"],
                title_hit_tickers=md.get("title_tickers") or [],
                body_hit_tickers=md.get("body_tickers") or [],
                theme_hit=bool(md.get("theme_hit")),
                tier_by_ticker=tier_by,
            )

            lede = (fields["content"] or "")[:300]
            triage_boost = triage(fields["title"], lede) * 5
            c["priority_score"] = pr.score + triage_boost
            c["priority_reasons"] = pr.reasons
            c["obj_list"] = obj_list

        candidates.sort(key=lambda x: x["priority_score"], reverse=True)

        top_candidates = candidates[:llm_cap]
        folded_candidates = candidates[llm_cap:]

        total_candidates = len(candidates)
        emit(
            f"优先级排序完成：{total_candidates} 候选，"
            f"{len(top_candidates)} 进 AI，{len(folded_candidates)} 折叠",
            force=True,
            step="digest_scored",
            groups=total_groups,
            filtered=filtered,
            skipped_existing=skipped_existing,
            cards_ok=0,
            folded=len(folded_candidates),
            hint="按优先级得分排序；高分项先行 AI 摘要",
        )

        # ── Pass 2a: top-K → LLM summarize + save folded=0 ───────────────────

        budget_blocked = False

        for c in top_candidates:
            if should_stop and should_stop():
                cancelled = True
                jobs_log.info(
                    "digest cancelled (llm pass) ok=%s fail=%s", ok, fail
                )
                emit(
                    f"已停止（入卡 {ok}）",
                    force=True,
                    step="digest_cancelled",
                    groups=total_groups,
                    filtered=filtered,
                    skipped_existing=skipped_existing,
                    cards_ok=ok,
                    folded=folded_ok,
                    fail=fail,
                )
                break

            fields = c["fields"]
            g = c["g"]
            dedup = c["dedup"]
            fetched = c["fetched"]
            published = c["published"]
            obj_list = c["obj_list"]
            priority_score = c["priority_score"]
            priority_reasons = c["priority_reasons"]

            if budget_blocked:
                jobs_log.error(
                    "digest skip LLM (budget) title=%s", fields["title"][:80]
                )
                fail += 1
                continue

            title_short = (fields["title"] or "")[:72]
            emit(
                f"AI 摘要 {ok + 1}/{llm_cap} · {title_short}",
                force=True,
                step="digest_llm",
                groups=total_groups,
                filtered=filtered,
                skipped_existing=skipped_existing,
                cards_ok=ok,
                folded=folded_ok,
                fail=fail,
                current_title=fields["title"],
                hint="单条通常数秒到一分钟；超过 3 分钟无心跳可点停止",
            )

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
                    timeout_s=90.0,
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
                    folded=0,
                    priority_score=priority_score,
                    priority_reasons=json.dumps(
                        priority_reasons, ensure_ascii=False
                    ),
                )
                store.upsert_feed_card(card)
                apply_ai_tags(
                    store,
                    card.id,
                    tags=tags,
                    suggestions=suggestions,
                    object_tickers=obj_list,
                )
                seen_groups.add(dedup)
                for u in g.urls:
                    seen_urls.add(u)
                log.info(
                    "card saved id=%s urls=%s tags=%s score=%.1f guard=ok prompt=%s",
                    card.id,
                    fields.get("url_count", 1),
                    tags,
                    priority_score,
                    SUMMARY_PROMPT,
                )
                ok += 1
                emit(
                    f"已入卡 {ok}/{llm_cap} · 继续摘要剩余候选…",
                    force=True,
                    step="digest_scan",
                    groups=total_groups,
                    filtered=filtered,
                    skipped_existing=skipped_existing,
                    cards_ok=ok,
                    folded=folded_ok,
                    fail=fail,
                )
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

        # ── Pass 2b: remaining candidates → folded cards (no LLM) ────────────

        if not cancelled:
            for c in folded_candidates:
                fields = c["fields"]
                g = c["g"]
                dedup = c["dedup"]
                fetched = c["fetched"]
                published = c["published"]
                obj_list = c["obj_list"]
                priority_score = c["priority_score"]
                priority_reasons = c["priority_reasons"]

                try:
                    card = FeedCard(
                        id=str(ULID()),
                        fetched_at=fetched,
                        published_at=published or fetched,
                        source=fields["source"],
                        title=fields["title"],
                        url=fields["url"],
                        summary=None,
                        objects=fields["objects"],
                        dedup_group=dedup,
                        batch_date=batch_date,
                        folded=1,
                        priority_score=priority_score,
                        priority_reasons=json.dumps(
                            priority_reasons, ensure_ascii=False
                        ),
                    )
                    store.upsert_feed_card(card)
                    apply_ai_tags(
                        store,
                        card.id,
                        tags=[],
                        suggestions=[],
                        object_tickers=obj_list,
                    )
                    seen_groups.add(dedup)
                    for u in g.urls:
                        seen_urls.add(u)
                    folded_ok += 1
                except Exception as e:
                    fail += 1
                    jobs_log.exception(
                        "digest fold failed title=%s err=%s",
                        fields["title"][:80],
                        e,
                    )

            if folded_ok:
                emit(
                    f"折叠入库 {folded_ok} 条（低优先级，无摘要）",
                    force=True,
                    step="digest_folded",
                    groups=total_groups,
                    filtered=filtered,
                    skipped_existing=skipped_existing,
                    cards_ok=ok,
                    folded=folded_ok,
                    fail=fail,
                    hint="折叠卡片可在 feed 页展开查看原标题",
                )

        jobs_log.info(
            "digest batch=%s raw=%s survivors=%s groups=%s ok=%s folded=%s "
            "fail=%s prescreen_discarded=%s filtered=%s skipped_existing=%s "
            "cancelled=%s",
            batch_date,
            raw_n,
            survivors_n,
            len(groups),
            ok,
            folded_ok,
            fail,
            prescreen_discarded,
            filtered,
            skipped_existing,
            cancelled,
        )
        print(
            f"digest {batch_date}: {ok} cards, {folded_ok} folded, {fail} errors, "
            f"prescreen {prescreen_discarded}, filtered {filtered}, "
            f"{len(groups)} groups"
            + (", cancelled" if cancelled else "")
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
            "folded": folded_ok,
            "capped": folded_ok,
            "cancelled": int(cancelled),
            "max_llm": llm_cap,
        }
    finally:
        try:
            n = store.delete_feed_raw(batch_date=batch_date)
            if n:
                jobs_log.info(
                    "feed_raw discarded batch=%s rows=%s", batch_date, n
                )
        except Exception:
            jobs_log.exception(
                "feed_raw discard failed batch=%s", batch_date
            )
