"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { apiGet, apiPost } from "@/lib/api";
import { TopNav, Card, Chip, Empty, SkeletonCard, Modal } from "@/components/ui";
import { TypeTag } from "@/components/info";
import { toast } from "@/components/toast";
import { TermRichText } from "@/components/term-rich-text";
import { dateRelative } from "@/lib/format";
import {
  clearFeedRefreshPending,
  FeedRefreshStatus,
  isFeedRefreshPending,
  isHeartbeatStale,
  markFeedRefreshPending,
} from "@/lib/feed-refresh-session";

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

const DAY_OPTIONS = [1, 3, 7, 30] as const;

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
  const [commentFor, setCommentFor] = useState<FeedCardView | null>(null);
  const [commentText, setCommentText] = useState("");
  const [refreshing, setRefreshing] = useState(false);
  const [refreshMsg, setRefreshMsg] = useState<string | null>(null);
  const [refreshStale, setRefreshStale] = useState(false);
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
          `简报已更新：抓取 ${result?.fetch?.raw ?? 0} 条 → 入卡 ${result?.cards ?? 0} 条（过滤 ${result?.digest?.filtered ?? 0}）`
        );
      }
      setRefreshMsg(null);
      setRefreshStale(false);
      await refresh();
    },
    [refresh, stopPolling]
  );

  const pollOnce = useCallback(async () => {
    try {
      const status = await apiGet<FeedRefreshStatus>("/feed/refresh/status");
      if (status.message) setRefreshMsg(status.message);
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
        }
      }
    } catch (e) {
      // keep polling; surface soft error in banner
      setRefreshMsg(`状态查询失败：${String((e as Error).message ?? e)}（将继续重试）`);
    }
  }, [onRefreshFinished]);

  const startPolling = useCallback(() => {
    stopPolling();
    handledFinishRef.current = false;
    void pollOnce();
    pollRef.current = setInterval(() => {
      void pollOnce();
    }, 2000);
  }, [pollOnce, stopPolling]);

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

  const { primaryCards, lowSignalCards } = useMemo(() => {
    const cards = data?.cards ?? [];
    const low: FeedCardView[] = [];
    const primary: FeedCardView[] = [];
    for (const c of cards) {
      const isLow = (c.tags ?? []).some((t) => t.tag_id === "low-signal-pr");
      if (isLow) low.push(c);
      else primary.push(c);
    }
    return { primaryCards: primary, lowSignalCards: low };
  }, [data]);

  async function onRefreshFeed() {
    if (refreshing) return;
    setRefreshing(true);
    setBusy(true);
    setRefreshStale(false);
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
      setBusy(false);
      setRefreshMsg(null);
      toast.error(String((e as Error).message ?? e));
    }
  }

  async function onCancelRefresh() {
    try {
      setBusy(true);
      const st = await apiPost<FeedRefreshStatus>("/feed/refresh/cancel", {});
      setRefreshMsg(st.message || "正在停止…");
      toast.success("已请求停止，当前条目结束后会停下");
    } catch (e) {
      toast.error(String((e as Error).message ?? e));
    } finally {
      setBusy(false);
    }
  }

  async function onPromote(cardId: string) {
    setBusy(true);
    try {
      const d = await apiPost<EventDraft>(`/feed/${cardId}/promote`, {});
      setDraft(d);
      setScope("company");
      setUserComment("");
    } catch (e) {
      toast.error(String((e as Error).message ?? e));
    } finally {
      setBusy(false);
    }
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
        user_comment: commentText.trim() || null,
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
        user_comment: userComment.trim() || null,
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
            disabled={busy}
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
            disabled={busy}
            onClick={() => onPromote(c.id)}
          >
            记入事件
          </button>
        </div>
      </Card>
    );
  }

  return (
    <main>
      <TopNav />
      <div className="read-column">
        <h1>信息流简报</h1>
        <p className="page-intro">
          盘后批次卡片：摘要铁律 + 相关性硬过滤。时间筛选只查已入库卡片，不触发抓取。
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
              disabled={busy}
              onClick={() => void onCancelRefresh()}
            >
              停止生成
            </button>
          )}
        </div>

        {refreshing && (
          <div
            className={refreshStale ? "note-warn" : "note"}
            style={{ marginBottom: "var(--s3)" }}
          >
            {refreshMsg ||
              "生成进行中…其它页面应仍可读库；可点「停止生成」。"}
            {refreshStale && (
              <span>
                {" "}
                · 已超过约 3 分钟无进展心跳，可能卡住；未设硬超时，仍在等待服务端状态。
              </span>
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
            <p style={{ marginBottom: "var(--s3)" }}>信息流加载失败：{loadError}</p>
            <p className="muted" style={{ marginBottom: "var(--s3)" }}>
              若刚点过「生成今日简报」，后台摘要可能仍在跑并把 API 堵死——请在终端重启后端后再点下方刷新。
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

            {primaryCards.length === 0 && lowSignalCards.length === 0 ? (
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
                      暂无简报卡片。不点生成则只读库里历史；点一次才抓取+摘要。
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
            ) : (
              <>
                {primaryCards.map(renderCard)}
                {lowSignalCards.length > 0 && (
                  <div style={{ marginTop: "var(--s5)" }}>
                    <button
                      type="button"
                      className="link-btn"
                      onClick={() => setShowLowSignal((v) => !v)}
                    >
                      {showLowSignal ? "▾" : "▸"} 低信号·公关{" "}
                      {lowSignalCards.length} 条（默认折叠）
                    </button>
                    {showLowSignal && lowSignalCards.map(renderCard)}
                  </div>
                )}
              </>
            )}

            <p className="muted" style={{ marginTop: "var(--s5)" }}>
              {days <= 1 && (data?.filtered_count ?? 0) > 0 && (
                <>
                  本批过滤 {data?.filtered_count} 条{" · "}
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
          </>
        )}
      </div>

      {showFiltered && filtered && (
        <Modal
          title="被过滤条目（漏杀可查）"
          onClose={() => setShowFiltered(false)}
        >
          {filtered.items.length === 0 ? (
            <Empty>本批无被过滤条目。</Empty>
          ) : (
            <ul className="item-list">
              {filtered.items.map((it) => (
                <li key={it.id} className="item">
                  <a href={it.url} target="_blank" rel="noreferrer">
                    {it.title}
                  </a>
                  <div className="muted">{it.source ?? "未知来源"}</div>
                </li>
              ))}
            </ul>
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
