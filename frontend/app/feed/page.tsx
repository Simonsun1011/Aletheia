"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { apiGet, apiPost, apiPostLlm } from "@/lib/api";
import { TopNav, Card, Chip, Empty, SkeletonCard, Modal } from "@/components/ui";
import { TypeTag } from "@/components/info";
import { toast } from "@/components/toast";
import { TermRichText } from "@/components/term-rich-text";
import { dateRelative } from "@/lib/format";
import {
  clearFeedRefreshPending,
  formatElapsed,
  isFeedRefreshPending,
  isHeartbeatStale,
  markFeedRefreshPending,
  type FeedRefreshDetail,
  type FeedRefreshStatus,
} from "@/lib/feed-refresh-session";
import { ListPager, usePagedItems } from "@/components/list-pager";

type TagChip = {
  tag_id: string;
  kind: string;
  display_en: string;
  display_zh: string;
  status: string;
};

type FeedCardView = {
  id: string;
  title: string;
  summary?: string | null;
  excerpt?: string | null;
  summary_generated_at?: string | null;
  comment_source_lang?: string | null;
  summary_translations?: Record<string, string>;
  source?: string | null;
  urls: string[];
  object_list: string[];
  published_at_display: string;
  published_at_fallback?: boolean;
  tags?: TagChip[];
  unclassified?: boolean;
  marked?: boolean;
  user_comment?: string | null;
  marked_at?: string | null;
  folded?: boolean;
  priority_score?: number | null;
  priority_label?: string | null;
  priority_reasons_list?: string[];
};

type FeedResponse = {
  batch_date: string | null;
  days?: number;
  tag?: string | null;
  cards: FeedCardView[];
  available_tags?: TagChip[];
  unclassified_count?: number;
  filtered_count?: number;
};

type FilteredResponse = {
  batch_date: string | null;
  count: number;
  items: { id: string; title: string; source?: string | null; url: string }[];
};

type EventDraft = {
  id: string;
  fact_text: string;
  object?: string | null;
  user_confirmed: number;
};

type Scope = "company" | "theme" | "macro" | "other";

type SummaryResponse = {
  summary: string;
  summary_generated_at?: string | null;
  cached: boolean;
};

type TranslationResponse = { lang: string; text: string; cached: boolean };

const DAY_OPTIONS = [1, 3, 7, 30] as const;
const EMPTY_FILTERED: FilteredResponse["items"] = [];

export default function FeedPage() {
  const [data, setData] = useState<FeedResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [filtered, setFiltered] = useState<FilteredResponse | null>(null);
  const [showFiltered, setShowFiltered] = useState(false);
  const [busy, setBusy] = useState(false);
  const [draft, setDraft] = useState<EventDraft | null>(null);
  const [scope, setScope] = useState<Scope>("company");
  const [userComment, setUserComment] = useState("");
  const [days, setDays] = useState<(typeof DAY_OPTIONS)[number]>(1);
  const [tag, setTag] = useState<string | null>(null);
  const [showLowSignal, setShowLowSignal] = useState(false);
  const [showFolded, setShowFolded] = useState(false);
  const [commentFor, setCommentFor] = useState<FeedCardView | null>(null);
  const [commentText, setCommentText] = useState("");
  const [refreshing, setRefreshing] = useState(false);
  const [cancelBusy, setCancelBusy] = useState(false);
  const [refreshMsg, setRefreshMsg] = useState<string | null>(null);
  const [refreshDetail, setRefreshDetail] = useState<FeedRefreshDetail | null>(
    null
  );
  const [refreshStartedAt, setRefreshStartedAt] = useState<string | null>(null);
  const [refreshElapsed, setRefreshElapsed] = useState<string | null>(null);
  const [refreshStale, setRefreshStale] = useState(false);
  const [pollFailed, setPollFailed] = useState(false);
  const [summaryBusy, setSummaryBusy] = useState<Record<string, boolean>>({});
  const [translationBusy, setTranslationBusy] = useState<Record<string, boolean>>({});
  const [translations, setTranslations] = useState<Record<string, string>>({});
  const [shownTranslations, setShownTranslations] = useState<Record<string, boolean>>({});
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const handledFinishRef = useRef(false);

  const refresh = useCallback(async () => {
    setLoading(true);
    setLoadError(null);
    try {
      const qs = new URLSearchParams();
      qs.set("days", String(days));
      if (tag) qs.set("tag", tag);
      const body = await apiGet<FeedResponse>(`/feed?${qs.toString()}`);
      setData(body);
      const cached: Record<string, string> = {};
      for (const card of body.cards) {
        const zh = card.summary_translations?.zh;
        if (zh) cached[card.id] = zh;
      }
      setTranslations(cached);
      setShownTranslations({});
    } catch (e) {
      const msg = String((e as Error).message ?? e);
      setLoadError(msg);
      toast.error(msg);
    } finally {
      setLoading(false);
    }
  }, [days, tag]);

  const stopPolling = useCallback(() => {
    if (pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
  }, []);

  const onRefreshFinished = useCallback(
    async (status: FeedRefreshStatus) => {
      if (handledFinishRef.current) return;
      handledFinishRef.current = true;
      stopPolling();
      setRefreshing(false);
      setBusy(false);
      clearFeedRefreshPending();
      if (status.phase === "error" || status.error) {
        setRefreshMsg(null);
        setRefreshStale(false);
        toast.error(status.error || status.message || "生成失败");
        return;
      }
      const result = status.result;
      if (status.phase === "cancelled") {
        toast.success(
          `已停止：当前库内 ${result?.cards ?? 0} 条（可稍后再生成补齐）`
        );
      } else {
        toast.success(
          `简报已更新：抓取 ${result?.fetch?.raw ?? 0} 条 → 初筛丢 ${result?.digest?.prescreen_discarded ?? 0} → 入卡 ${result?.cards ?? 0} 条`
        );
      }
      setRefreshMsg(null);
      setRefreshDetail(null);
      setRefreshStartedAt(null);
      setRefreshElapsed(null);
      setRefreshStale(false);
      setPollFailed(false);
      await refresh();
    },
    [refresh, stopPolling]
  );

  const pollOnce = useCallback(async () => {
    try {
      const status = await apiGet<FeedRefreshStatus>("/feed/refresh/status");
      setPollFailed(false);
      if (status.message) setRefreshMsg(status.message);
      if (status.detail) setRefreshDetail(status.detail);
      if (status.started_at) {
        setRefreshStartedAt(status.started_at);
        setRefreshElapsed(formatElapsed(status.started_at));
      }
      setRefreshStale(isHeartbeatStale(status));
      if (status.running) {
        setRefreshing(true);
        return;
      }
      // not running
      if (isFeedRefreshPending() || status.phase === "done" || status.phase === "error" || status.phase === "cancelled") {
        // Finished while we were away, or just completed
        if (
          status.phase === "done" ||
          status.phase === "error" ||
          status.phase === "cancelled" ||
          status.result ||
          status.error
        ) {
          await onRefreshFinished(status);
        } else {
          // pending flag but server idle with no result — stale flag, clear
          clearFeedRefreshPending();
          setRefreshing(false);
          setRefreshMsg(null);
          stopPolling();
        }
      }
    } catch (_e) {
      // Poll itself failed → backend unreachable (distinct from "slow digest")
      setPollFailed(true);
      setRefreshMsg(
        "后端无响应（轮询失败）— 与「摘要慢」不同，请检查后端或停止生成"
      );
    }
  }, [onRefreshFinished, stopPolling]);

  const startPolling = useCallback(() => {
    stopPolling();
    handledFinishRef.current = false;
    void pollOnce();
    pollRef.current = setInterval(() => {
      void pollOnce();
    }, 2000);
  }, [pollOnce, stopPolling]);

  // Tick elapsed clock while refreshing (status poll is every 2s)
  useEffect(() => {
    if (!refreshing || !refreshStartedAt) return;
    const id = window.setInterval(() => {
      setRefreshElapsed(formatElapsed(refreshStartedAt));
    }, 1000);
    return () => window.clearInterval(id);
  }, [refreshing, refreshStartedAt]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  // Resume in-flight generation after SPA tab switch / remount
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const status = await apiGet<FeedRefreshStatus>("/feed/refresh/status");
        if (cancelled) return;
        if (status.running || isFeedRefreshPending()) {
          setRefreshing(true);
          setRefreshMsg(status.message || "生成进行中…");
          if (status.detail) setRefreshDetail(status.detail);
          if (status.started_at) {
            setRefreshStartedAt(status.started_at);
            setRefreshElapsed(formatElapsed(status.started_at));
          }
          markFeedRefreshPending(status.batch_date || undefined);
          startPolling();
        }
      } catch {
        if (isFeedRefreshPending()) {
          setRefreshing(true);
          setRefreshMsg("正在恢复生成状态…");
          startPolling();
        }
      }
    })();
    return () => {
      cancelled = true;
      stopPolling();
    };
  }, [startPolling, stopPolling]);

  const { primaryCards, lowSignalCards, foldedCards } = useMemo(() => {
    const cards = data?.cards ?? [];
    const low: FeedCardView[] = [];
    const primary: FeedCardView[] = [];
    const folded: FeedCardView[] = [];
    for (const c of cards) {
      if (c.folded) {
        folded.push(c);
        continue;
      }
      const isLow = (c.tags ?? []).some((t) => t.tag_id === "low-signal-pr");
      if (isLow) low.push(c);
      else primary.push(c);
    }
    const byScore = (a: FeedCardView, b: FeedCardView) =>
      (b.priority_score ?? 0) - (a.priority_score ?? 0);
    primary.sort(byScore);
    folded.sort(byScore);
    return {
      primaryCards: primary,
      lowSignalCards: low,
      foldedCards: folded,
    };
  }, [data]);

  const primaryPage = usePagedItems(
    primaryCards,
    `${days}|${tag ?? ""}|${primaryCards.length}`
  );
  const foldedPage = usePagedItems(
    foldedCards,
    `folded|${days}|${tag ?? ""}|${foldedCards.length}|${showFolded}`
  );
  const lowSignalPage = usePagedItems(
    lowSignalCards,
    `low|${days}|${tag ?? ""}|${lowSignalCards.length}|${showLowSignal}`
  );

  useEffect(() => {
    document
      .querySelector<HTMLElement>(".feed-stream")
      ?.scrollTo({ top: 0 });
  }, [primaryPage.page, foldedPage.page, lowSignalPage.page]);

  const filteredItems = filtered?.items ?? EMPTY_FILTERED;
  const filteredPage = usePagedItems(
    filteredItems,
    `${showFiltered}|${filteredItems.length}`
  );

  async function onRefreshFeed() {
    if (refreshing) return;
    setRefreshing(true);
    setCancelBusy(false);
    setRefreshStale(false);
    setPollFailed(false);
    setRefreshMsg("已提交，正在启动…");
    handledFinishRef.current = false;
    markFeedRefreshPending();
    try {
      const kicked = await apiPost<FeedRefreshStatus>("/feed/refresh", {});
      if (kicked.accepted === false && kicked.running) {
        setRefreshMsg(kicked.message || "已有任务在跑，继续等待…");
      } else {
        setRefreshMsg(kicked.message || "生成中…");
      }
      startPolling();
    } catch (e) {
      clearFeedRefreshPending();
      setRefreshing(false);
      setRefreshMsg(null);
      toast.error(String((e as Error).message ?? e));
    }
  }

  async function onCancelRefresh() {
    if (cancelBusy) return;
    try {
      setCancelBusy(true);
      const st = await apiPost<FeedRefreshStatus>("/feed/refresh/cancel", {});
      setRefreshMsg(st.message || "正在停止…");
      toast.success("已请求停止，当前条目结束后会停下");
    } catch (e) {
      toast.error(String((e as Error).message ?? e));
    } finally {
      setCancelBusy(false);
    }
  }

  async function onPromote(cardId: string) {
    setBusy(true);
    try {
      const d = await apiPostLlm<EventDraft>(`/feed/${cardId}/promote`, {});
      setDraft(d);
      setScope("company");
      setUserComment("");
    } catch (e) {
      toast.error(String((e as Error).message ?? e));
    } finally {
      setBusy(false);
    }
  }

  async function onGenerateSummary(card: FeedCardView) {
    setSummaryBusy((v) => ({ ...v, [card.id]: true }));
    try {
      const result = await apiPostLlm<SummaryResponse>(
        `/feed/${card.id}/summary`,
        {}
      );
      setData((current) =>
        current
          ? {
              ...current,
              cards: current.cards.map((item) =>
                item.id === card.id
                  ? {
                      ...item,
                      summary: result.summary,
                      summary_generated_at: result.summary_generated_at,
                    }
                  : item
              ),
            }
          : current
      );
      toast.success(result.cached ? "已读取缓存摘要" : "摘要已生成");
    } catch (e) {
      const raw = String((e as Error).message ?? e);
      const msg = raw.includes("AI_GUARD_VIOLATION")
        ? "摘要含禁词（买卖建议或影响判断），已拦截。请读原文，或稍后再试。"
        : raw.includes("SUMMARY_LANGUAGE_MISMATCH")
          ? "摘要语言须与原文一致，已拦截。"
          : raw;
      toast.error(msg);
    } finally {
      setSummaryBusy((v) => ({ ...v, [card.id]: false }));
    }
  }

  async function onToggleTranslation(card: FeedCardView) {
    if (shownTranslations[card.id]) {
      setShownTranslations((v) => ({ ...v, [card.id]: false }));
      return;
    }
    if (translations[card.id] || card.summary_translations?.zh) {
      const text = translations[card.id] || card.summary_translations?.zh || "";
      setTranslations((v) => ({ ...v, [card.id]: text }));
      setShownTranslations((v) => ({ ...v, [card.id]: true }));
      return;
    }
    setTranslationBusy((v) => ({ ...v, [card.id]: true }));
    try {
      const result = await apiPostLlm<TranslationResponse>(
        `/feed/${card.id}/summary/translate?lang=zh`,
        {}
      );
      setTranslations((v) => ({ ...v, [card.id]: result.text }));
      setShownTranslations((v) => ({ ...v, [card.id]: true }));
      setData((current) =>
        current
          ? {
              ...current,
              cards: current.cards.map((item) =>
                item.id === card.id
                  ? {
                      ...item,
                      summary_translations: {
                        ...(item.summary_translations ?? {}),
                        zh: result.text,
                      },
                    }
                  : item
              ),
            }
          : current
      );
      toast.success(result.cached ? "已读取缓存译文" : "译文已生成并保存");
    } catch (e) {
      toast.error(String((e as Error).message ?? e));
    } finally {
      setTranslationBusy((v) => ({ ...v, [card.id]: false }));
    }
  }

  function sourceLangFor(card: FeedCardView): string {
    if (shownTranslations[card.id]) return "zh";
    const summary = card.summary ?? "";
    if (/[\u3040-\u30ff]/.test(summary)) return "ja";
    if (/[\u4e00-\u9fff]/.test(summary)) return "zh";
    return "en";
  }

  async function onToggleMark(card: FeedCardView) {
    setBusy(true);
    try {
      await apiPost(`/feed/${card.id}/mark`, { marked: !card.marked });
      await refresh();
    } catch (e) {
      toast.error(String((e as Error).message ?? e));
    } finally {
      setBusy(false);
    }
  }

  async function onSaveComment() {
    if (!commentFor) return;
    setBusy(true);
    try {
      await apiPost(`/feed/${commentFor.id}/mark`, {
        marked: true,
        // empty string clears; null would mean "keep" on the server
        user_comment: commentText.trim(),
        source_lang: commentText.trim() ? sourceLangFor(commentFor) : null,
      });
      setCommentFor(null);
      setCommentText("");
      toast.success("已保存标记与评论");
      await refresh();
    } catch (e) {
      toast.error(String((e as Error).message ?? e));
    } finally {
      setBusy(false);
    }
  }

  async function onConfirmDraft() {
    if (!draft) return;
    setBusy(true);
    try {
      await apiPost(`/changefeed/${draft.id}/confirm`, {
        scope,
        user_comment: userComment.trim(),
      });
      setDraft(null);
      setUserComment("");
      setScope("company");
      toast.success("事件已确认入库");
    } catch (e) {
      toast.error(String((e as Error).message ?? e));
    } finally {
      setBusy(false);
    }
  }

  async function onShowFiltered() {
    setBusy(true);
    try {
      const q = data?.batch_date ? `?date=${data.batch_date}` : "";
      const body = await apiGet<FilteredResponse>(`/feed/filtered${q}`);
      setFiltered(body);
      setShowFiltered(true);
    } catch (e) {
      toast.error(String((e as Error).message ?? e));
    } finally {
      setBusy(false);
    }
  }

  const facetTags = data?.available_tags ?? [];

  function renderCard(c: FeedCardView) {
    const companyTags = (c.tags ?? []).filter((t) => t.kind === "company");
    const topicTags = (c.tags ?? []).filter((t) => t.kind === "topic");
    return (
      <Card
        key={c.id}
        className={
          c.unclassified ? "feed-card feed-card-unclassified" : "feed-card"
        }
      >
        <div className="card-title">
          {c.title}
          {c.unclassified && (
            <span className="chip chip-warn" style={{ marginLeft: 8 }}>
              未归类
            </span>
          )}
          {c.marked && (
            <span className="chip chip-active" style={{ marginLeft: 8 }}>
              已标记
            </span>
          )}
        </div>
        <div className="feed-meta">
          {c.source ?? "未知来源"} · {dateRelative(c.published_at_display)}
          {c.published_at_fallback ? "（抓取时间）" : ""}
          {c.priority_label ? ` · ${c.priority_label}` : ""}
        </div>
        {c.summary && (
          <div className="info-ai" style={{ marginBottom: "var(--s3)" }}>
            <div className="info-row" style={{ margin: 0 }}>
              <TypeTag type="ai" />
              <p
                className="feed-summary"
                style={{ margin: 0, color: "var(--ai-text)" }}
              >
                <TermRichText text={c.summary} context="信息流简报摘要" />
              </p>
            </div>
          </div>
        )}
        {c.summary && (
          <div className="actions" style={{ marginTop: 0, marginBottom: "var(--s3)" }}>
            <button
              type="button"
              className="link-btn"
              disabled={translationBusy[c.id]}
              onClick={() => void onToggleTranslation(c)}
            >
              {translationBusy[c.id]
                ? "翻译中…"
                : shownTranslations[c.id]
                  ? "收起译文"
                  : translations[c.id] || c.summary_translations?.zh
                    ? "查看中文译文"
                    : "翻译成中文"}
            </button>
          </div>
        )}
        {c.summary && shownTranslations[c.id] && translations[c.id] && (
          <div className="note" style={{ marginBottom: "var(--s3)" }}>
            <strong>中文译文</strong>
            <p style={{ margin: "4px 0 0" }}>{translations[c.id]}</p>
          </div>
        )}
        {!c.summary && (
          <div style={{ marginBottom: "var(--s3)" }}>
            <button
              type="button"
              className="secondary btn-small"
              disabled={summaryBusy[c.id]}
              onClick={() => void onGenerateSummary(c)}
            >
              {summaryBusy[c.id] ? "生成摘要中…" : "生成摘要"}
            </button>
            <span className="muted" style={{ marginLeft: 8 }}>
              评论与记入事件需先生成摘要
            </span>
          </div>
        )}
        {c.folded && !c.summary && (
          <p className="muted" style={{ marginBottom: "var(--s3)" }}>
            展示上限外折叠（标题、来源与原文链接均保留）
          </p>
        )}
        {c.user_comment && (
          <p className="note" style={{ marginBottom: "var(--s3)" }}>
            我的评论：{c.user_comment}
          </p>
        )}
        <div className="chip-row" style={{ marginBottom: "var(--s3)" }}>
          {companyTags.map((t) => (
            <Chip key={t.tag_id} mono>
              {t.tag_id}
            </Chip>
          ))}
          {topicTags.map((t) => (
            <span key={t.tag_id} className="chip">
              {t.display_zh || t.display_en}
            </span>
          ))}
          {(c.object_list ?? [])
            .filter((o) => !companyTags.some((t) => t.tag_id === o))
            .map((o) => (
              <Chip key={o} mono>
                {o}
              </Chip>
            ))}
        </div>
        <div className="actions" style={{ marginTop: 0 }}>
          {(c.urls ?? []).map((u) => (
            <a key={u} href={u} target="_blank" rel="noreferrer">
              原文 ↗
            </a>
          ))}
          <button
            type="button"
            className="secondary btn-small"
            disabled={busy}
            onClick={() => onToggleMark(c)}
          >
            {c.marked ? "取消标记" : "标记"}
          </button>
          <button
            type="button"
            className="secondary btn-small"
            disabled={busy || !c.summary}
            title={!c.summary ? "请先生成摘要" : undefined}
            onClick={() => {
              setCommentFor(c);
              setCommentText(c.user_comment ?? "");
            }}
          >
            评论
          </button>
          <button
            type="button"
            className="secondary btn-small"
            disabled={busy || !c.summary}
            title={!c.summary ? "请先生成摘要" : undefined}
            onClick={() => onPromote(c.id)}
          >
            记入事件
          </button>
        </div>
      </Card>
    );
  }

  return (
    <main className="feed-page">
      <TopNav />
      <div className="read-column">
        <div className="feed-chrome">
          <h1>信息流简报</h1>
          <p className="page-intro">
            盘后批次卡片：确定性质量过滤 + 优先级排序。时间筛选只查已入库卡片，不触发抓取。
          </p>

          <div
            className="chip-row"
            style={{ marginBottom: "var(--s3)", alignItems: "center" }}
          >
            {DAY_OPTIONS.map((d) => (
              <button
                key={d}
                type="button"
                className={days === d ? "chip chip-active" : "chip"}
                style={{ cursor: "pointer", border: "none" }}
                onClick={() => setDays(d)}
              >
                {d === 1 ? "1天" : `${d}天`}
              </button>
            ))}
            <button
              type="button"
              className="secondary btn-small"
              style={{ marginLeft: "auto" }}
              disabled={busy || refreshing}
              onClick={onRefreshFeed}
            >
              {refreshing ? "生成中…" : "生成今日简报"}
            </button>
            {refreshing && (
              <button
                type="button"
                className="secondary btn-small"
                disabled={cancelBusy}
                onClick={() => void onCancelRefresh()}
              >
                {cancelBusy ? "正在停止…" : "停止生成"}
              </button>
            )}
          </div>

          {refreshing && (
            <div
              className={pollFailed || refreshStale ? "note-warn" : "note"}
              style={{ marginBottom: "var(--s3)" }}
            >
              <div>
                <strong>{refreshMsg || "生成进行中…"}</strong>
                {!pollFailed && refreshElapsed && (
                  <span className="muted"> · 已用时 {refreshElapsed}</span>
                )}
              </div>
              {!pollFailed && refreshDetail?.current_title && (
                <div className="muted" style={{ marginTop: 4 }}>
                  当前：{refreshDetail.current_title}
                </div>
              )}
              {!pollFailed &&
                (refreshDetail?.cards_ok != null ||
                  refreshDetail?.prescreen_discarded != null ||
                  refreshDetail?.filtered != null ||
                  refreshDetail?.groups != null) && (
                <div className="muted" style={{ marginTop: 4 }}>
                  {refreshDetail!.prescreen_discarded != null && (
                    <span>初筛丢 {refreshDetail!.prescreen_discarded}</span>
                  )}
                  {refreshDetail!.survivors != null && (
                    <span>
                      {refreshDetail!.prescreen_discarded != null ? " · " : ""}
                      幸存 {refreshDetail!.survivors}
                    </span>
                  )}
                  {refreshDetail!.groups != null && (
                    <span>
                      {(refreshDetail!.prescreen_discarded != null ||
                        refreshDetail!.survivors != null) &&
                        " · "}
                      候选组 {refreshDetail!.scanned ?? 0}/
                      {refreshDetail!.groups}
                    </span>
                  )}
                  {refreshDetail!.filtered != null &&
                    refreshDetail!.filtered > 0 && (
                      <span> · 漏杀记 {refreshDetail!.filtered}</span>
                    )}
                  {refreshDetail!.skipped_existing != null &&
                    refreshDetail!.skipped_existing > 0 && (
                      <span>
                        {" "}
                        · 跳过已入卡 {refreshDetail!.skipped_existing}
                      </span>
                    )}
                  {refreshDetail!.cards_ok != null && (
                    <span> · 入卡 {refreshDetail!.cards_ok}</span>
                  )}
                  {refreshDetail!.folded != null &&
                    refreshDetail!.folded > 0 && (
                      <span> · 折叠 {refreshDetail!.folded}</span>
                    )}
                </div>
              )}
              {!pollFailed && refreshDetail?.hint && (
                <div className="muted" style={{ marginTop: 4 }}>
                  {refreshDetail.hint}
                </div>
              )}
              {!pollFailed && !refreshDetail?.hint && (
                <div className="muted" style={{ marginTop: 4 }}>
                  可切换到其他页；后台会完成过滤、排序与卡片持久化。
                </div>
              )}
              {!pollFailed && refreshStale && (
                <div style={{ marginTop: 4 }}>
                  已超过约 3 分钟无进展心跳，可能卡住；可点「停止生成」。
                </div>
              )}
            </div>
          )}

          <div className="chip-row" style={{ marginBottom: "var(--s4)" }}>
            <button
              type="button"
              className={!tag ? "chip chip-active" : "chip"}
              style={{ cursor: "pointer", border: "none" }}
              onClick={() => setTag(null)}
            >
              全部主题
            </button>
            {facetTags.map((t) => (
              <button
                key={t.tag_id}
                type="button"
                className={tag === t.tag_id ? "chip chip-active" : "chip"}
                style={{ cursor: "pointer", border: "none" }}
                onClick={() => setTag(t.tag_id)}
              >
                {t.display_zh || t.display_en}
              </button>
            ))}
          </div>
        </div>

        <div className="feed-stream" aria-label="信息流卡片列表">
          {loading ? (
            <>
              <SkeletonCard lines={2} />
              <SkeletonCard lines={2} />
              <p className="muted" style={{ marginTop: "var(--s3)" }}>
                正在从后端拉简报…
              </p>
            </>
          ) : loadError ? (
            <Empty icon="⚠">
              <p style={{ marginBottom: "var(--s3)" }}>
                信息流加载失败：{loadError}
              </p>
              <p className="muted" style={{ marginBottom: "var(--s3)" }}>
                若刚点过「生成今日简报」，后台管线可能仍在运行——请稍后重试或检查后端状态。
              </p>
              <button type="button" onClick={() => void refresh()}>
                重试加载
              </button>
            </Empty>
          ) : (
            <>
              <div className="batch-sticky">
                {days <= 1
                  ? `批次 ${data?.batch_date ?? "—"} · 共 ${(data?.cards ?? []).length} 条`
                  : `近 ${days} 天 · 共 ${(data?.cards ?? []).length} 条`}
                {tag ? ` · #${tag}` : ""}
              </div>

              {primaryCards.length === 0 &&
              lowSignalCards.length === 0 &&
              foldedCards.length === 0 ? (
                <Empty icon="◎">
                  {refreshing ? (
                    <p>
                      {refreshMsg || "正在生成今日简报…"}
                      <br />
                      <span className="muted">
                        可切换到其他页；完成后回来会自动加载。
                        {refreshStale
                          ? " 心跳已久无更新，可能卡住（仍等待中，无硬超时）。"
                          : ""}
                      </span>
                    </p>
                  ) : (
                    <>
                      <p style={{ marginBottom: "var(--s3)" }}>
                        暂无简报卡片。不点生成则只读库里历史；点一次才抓取、过滤并排序。
                      </p>
                      <button
                        type="button"
                        disabled={busy || refreshing}
                        onClick={onRefreshFeed}
                      >
                        生成今日简报
                      </button>
                    </>
                  )}
                </Empty>
              ) : primaryCards.length === 0 ? (
                <Empty icon="◎">主列表暂无卡片（见下方折叠区）。</Empty>
              ) : (
                <>
                  {primaryPage.slice.map(renderCard)}
                  <ListPager
                    page={primaryPage.page}
                    pageCount={primaryPage.pageCount}
                    total={primaryPage.total}
                    onChange={primaryPage.setPage}
                  />
                </>
              )}
            </>
          )}
        </div>

        {!loading && !loadError && (
          <div className="feed-stream-foot">
            {foldedCards.length > 0 && (
              <div>
                <button
                  type="button"
                  className="link-btn"
                  onClick={() => setShowFolded((v) => !v)}
                >
                  {showFolded ? "▾" : "▸"} 低优先折叠 {foldedCards.length} 条（可展开）
                </button>
                {showFolded && (
                  <div className="feed-stream-foot-list">
                    {foldedPage.slice.map(renderCard)}
                    <ListPager
                      page={foldedPage.page}
                      pageCount={foldedPage.pageCount}
                      total={foldedPage.total}
                      onChange={foldedPage.setPage}
                    />
                  </div>
                )}
              </div>
            )}
            {lowSignalCards.length > 0 && (
              <div>
                <button
                  type="button"
                  className="link-btn"
                  onClick={() => setShowLowSignal((v) => !v)}
                >
                  {showLowSignal ? "▾" : "▸"} 低信号·公关 {lowSignalCards.length}{" "}
                  条（默认折叠）
                </button>
                {showLowSignal && (
                  <div className="feed-stream-foot-list">
                    {lowSignalPage.slice.map(renderCard)}
                    <ListPager
                      page={lowSignalPage.page}
                      pageCount={lowSignalPage.pageCount}
                      total={lowSignalPage.total}
                      onChange={lowSignalPage.setPage}
                    />
                  </div>
                )}
              </div>
            )}
            {(days <= 1 && (data?.filtered_count ?? 0) > 0) ||
            (data?.unclassified_count ?? 0) > 0 ? (
              <p className="muted" style={{ margin: 0 }}>
                {days <= 1 && (data?.filtered_count ?? 0) > 0 && (
                  <>
                    本批漏杀可查 {data?.filtered_count} 条{" · "}
                    <button
                      type="button"
                      className="link-btn"
                      disabled={busy}
                      onClick={onShowFiltered}
                    >
                      查看漏杀
                    </button>
                    {" · "}
                  </>
                )}
                {(data?.unclassified_count ?? 0) > 0 && (
                  <span className="chip chip-warn">
                    本批 {data?.unclassified_count} 条未归类
                  </span>
                )}
              </p>
            ) : null}
          </div>
        )}
      </div>

      {showFiltered && filtered && (
        <Modal
          title="漏杀可查（次级分诊 / 调参审计）"
          onClose={() => setShowFiltered(false)}
        >
          {filtered.items.length === 0 ? (
            <Empty>本批无漏杀可查条目（初筛默认只计数；分诊未开时多为空）。</Empty>
          ) : (
            <>
              <ul className="item-list">
                {filteredPage.slice.map((it) => (
                  <li key={it.id} className="item">
                    <a href={it.url} target="_blank" rel="noreferrer">
                      {it.title}
                    </a>
                    <div className="muted">{it.source ?? "未知来源"}</div>
                  </li>
                ))}
              </ul>
              <ListPager
                page={filteredPage.page}
                pageCount={filteredPage.pageCount}
                total={filteredPage.total}
                onChange={filteredPage.setPage}
              />
            </>
          )}
        </Modal>
      )}

      {commentFor && (
        <Modal
          title="卡片评论（语料留痕）"
          onClose={() => setCommentFor(null)}
          footer={
            <>
              <button type="button" disabled={busy} onClick={onSaveComment}>
                保存
              </button>
              <button
                type="button"
                className="secondary"
                onClick={() => setCommentFor(null)}
              >
                取消
              </button>
            </>
          }
        >
          <p className="muted" style={{ marginBottom: "var(--s3)" }}>
            轻量留痕，写入随感语料流；不是「记入事件」。
          </p>
          <textarea
            rows={4}
            value={commentText}
            onChange={(e) => setCommentText(e.target.value)}
            placeholder="可选评论…"
            style={{ width: "100%" }}
          />
        </Modal>
      )}

      {draft && (
        <Modal
          title="记入事件（待确认）"
          onClose={() => setDraft(null)}
          footer={
            <>
              <button type="button" disabled={busy} onClick={onConfirmDraft}>
                确认入库
              </button>
              <button
                type="button"
                className="secondary"
                onClick={() => setDraft(null)}
              >
                丢弃
              </button>
            </>
          }
        >
          <p className="muted" style={{ marginBottom: "var(--s3)" }}>
            {draft.object ?? "未指定对象"} · {draft.id}
          </p>
          <p style={{ marginBottom: "var(--s4)" }}>{draft.fact_text}</p>
          <div className="row">
            <div className="field">
              <label htmlFor="scope">范围</label>
              <select
                id="scope"
                value={scope}
                onChange={(e) => setScope(e.target.value as Scope)}
              >
                <option value="company">个股</option>
                <option value="theme">主题</option>
                <option value="macro">宏观</option>
                <option value="other">其他</option>
              </select>
            </div>
            <div className="field">
              <label htmlFor="comment">备注（可选）</label>
              <input
                id="comment"
                value={userComment}
                onChange={(e) => setUserComment(e.target.value)}
              />
            </div>
          </div>
        </Modal>
      )}
    </main>
  );
}
