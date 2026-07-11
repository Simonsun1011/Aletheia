"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { apiGet, apiPost } from "@/lib/api";

type FeedCardView = {
  id: string;
  title: string;
  summary?: string | null;
  source?: string | null;
  urls: string[];
  object_list: string[];
  published_at_display: string;
  published_at_fallback?: boolean;
};

type FeedResponse = {
  batch_date: string | null;
  cards: FeedCardView[];
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

export default function FeedPage() {
  const [data, setData] = useState<FeedResponse | null>(null);
  const [filtered, setFiltered] = useState<FilteredResponse | null>(null);
  const [showFiltered, setShowFiltered] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [draft, setDraft] = useState<EventDraft | null>(null);
  const [scope, setScope] = useState<
    "company" | "theme" | "macro" | "other"
  >("company");
  const [userComment, setUserComment] = useState("");

  const refresh = useCallback(async () => {
    const body = await apiGet<FeedResponse>("/feed");
    setData(body);
  }, []);

  useEffect(() => {
    refresh().catch((e) => setError(String(e.message ?? e)));
  }, [refresh]);

  async function onPromote(cardId: string) {
    setBusy(true);
    setError(null);
    try {
      const d = await apiPost<EventDraft>(`/feed/${cardId}/promote`, {});
      setDraft(d);
    } catch (e) {
      setError(String((e as Error).message ?? e));
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
    } catch (e) {
      setError(String((e as Error).message ?? e));
    } finally {
      setBusy(false);
    }
  }

  async function onShowFiltered() {
    setBusy(true);
    setError(null);
    try {
      const q = data?.batch_date ? `?date=${data.batch_date}` : "";
      const body = await apiGet<FilteredResponse>(`/feed/filtered${q}`);
      setFiltered(body);
      setShowFiltered(true);
    } catch (e) {
      setError(String((e as Error).message ?? e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <main>
      <p>
        <Link href="/">← 判断日志</Link>
        {" · "}
        <Link href="/feed">信息流</Link>
        {" · "}
        <Link href="/console">操作台</Link>
        {" · "}
        <Link href="/settings">设置</Link>
      </p>
      <h1>信息流简报</h1>
      <p className="muted">
        Slice 3：盘后批次卡片（摘要铁律 + 相关性硬过滤）。[原文] 外链 · [记入事件]
        需人工确认。
      </p>
      {error && <p className="error">{error}</p>}
      <p className="muted">batch {data?.batch_date ?? "—"}</p>

      {draft && (
        <section>
          <h2>事件草稿（未确认）</h2>
          <p className="muted">
            {draft.object ?? "—"} · {draft.id}
          </p>
          <p>{draft.fact_text}</p>
          <div className="actions" style={{ flexWrap: "wrap" }}>
            <label>
              范围{" "}
              <select
                value={scope}
                onChange={(e) =>
                  setScope(
                    e.target.value as "company" | "theme" | "macro" | "other"
                  )
                }
              >
                <option value="company">个股</option>
                <option value="theme">主题</option>
                <option value="macro">宏观</option>
                <option value="other">其他</option>
              </select>
            </label>
            <input
              value={userComment}
              onChange={(e) => setUserComment(e.target.value)}
              placeholder="备注（可选）"
            />
          </div>
          <div className="actions">
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
          </div>
        </section>
      )}

      {(data?.cards ?? []).map((c) => (
        <section key={c.id}>
          <h2 style={{ fontSize: "1rem" }}>{c.title}</h2>
          <p className="muted">
            {c.source ?? "—"} · {c.published_at_display}
            {c.published_at_fallback ? "（用抓取时间）" : ""}
          </p>
          <p>{c.summary}</p>
          <p className="muted">
            {(c.object_list || []).map((o) => (
              <span key={o} style={{ marginRight: "0.5rem" }}>
                [{o}]
              </span>
            ))}
          </p>
          <div className="actions">
            {(c.urls || []).map((u) => (
              <a key={u} href={u} target="_blank" rel="noreferrer">
                原文
              </a>
            ))}
            <button
              type="button"
              className="secondary"
              disabled={busy}
              onClick={() => onPromote(c.id)}
            >
              记入事件
            </button>
          </div>
        </section>
      ))}

      {data && data.cards.length === 0 && (
        <p className="muted">
          暂无卡片。先跑 jobs/fetch_feeds.py 与 jobs/digest.py。
        </p>
      )}

      {(data?.filtered_count ?? 0) > 0 && (
        <p className="muted" style={{ marginTop: "2rem" }}>
          本批过滤 {data?.filtered_count} 条
          {" · "}
          <button
            type="button"
            className="secondary"
            disabled={busy}
            onClick={onShowFiltered}
          >
            查看
          </button>
        </p>
      )}

      {showFiltered && filtered && (
        <section>
          <h2>被过滤条目（漏杀可查）</h2>
          <ul>
            {filtered.items.map((it) => (
              <li key={it.id}>
                <a href={it.url} target="_blank" rel="noreferrer">
                  {it.title}
                </a>
                <span className="muted"> · {it.source ?? "—"}</span>
              </li>
            ))}
          </ul>
          <button
            type="button"
            className="secondary"
            onClick={() => setShowFiltered(false)}
          >
            收起
          </button>
        </section>
      )}
    </main>
  );
}
