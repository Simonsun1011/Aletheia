"use client";

import { useCallback, useEffect, useState } from "react";
import { apiGet, apiPost } from "@/lib/api";
import { TopNav, Card, Chip, Empty, SkeletonCard, Modal } from "@/components/ui";
import { TypeTag } from "@/components/info";
import { toast } from "@/components/toast";
import { TermRichText } from "@/components/term-rich-text";
import { dateRelative } from "@/lib/format";

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

type Scope = "company" | "theme" | "macro" | "other";

export default function FeedPage() {
  const [data, setData] = useState<FeedResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [filtered, setFiltered] = useState<FilteredResponse | null>(null);
  const [showFiltered, setShowFiltered] = useState(false);
  const [busy, setBusy] = useState(false);
  const [draft, setDraft] = useState<EventDraft | null>(null);
  const [scope, setScope] = useState<Scope>("company");
  const [userComment, setUserComment] = useState("");

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const body = await apiGet<FeedResponse>("/feed");
      setData(body);
    } catch (e) {
      toast.error(String((e as Error).message ?? e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

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

  const cards = data?.cards ?? [];

  return (
    <main>
      <TopNav />
      <div className="read-column">
      <h1>信息流简报</h1>
      <p className="page-intro">
        盘后批次卡片：摘要铁律 + 相关性硬过滤。原文外链可查，记入事件需人工确认。
      </p>

      {loading ? (
        <>
          <SkeletonCard lines={2} />
          <SkeletonCard lines={2} />
        </>
      ) : (
        <>
          <div className="batch-sticky">
            批次 {data?.batch_date ?? "—"} · 共 {cards.length} 条
          </div>

          {cards.length === 0 ? (
            <Empty icon="◎">
              暂无卡片——先跑 jobs/fetch_feeds.py 与 jobs/digest.py 生成盘后批次。
            </Empty>
          ) : (
            cards.map((c) => (
              <Card key={c.id} className="feed-card">
                <div className="card-title">{c.title}</div>
                <div className="feed-meta">
                  {c.source ?? "未知来源"} · {dateRelative(c.published_at_display)}
                  {c.published_at_fallback ? "（抓取时间）" : ""}
                </div>
                {c.summary && (
                  <div className="info-ai" style={{ marginBottom: "var(--s3)" }}>
                    <div className="info-row" style={{ margin: 0 }}>
                      <TypeTag type="ai" />
                      <p className="feed-summary" style={{ margin: 0, color: "var(--ai-text)" }}>
                        <TermRichText
                          text={c.summary}
                          context="信息流简报摘要"
                        />
                      </p>
                    </div>
                  </div>
                )}
                {(c.object_list?.length ?? 0) > 0 && (
                  <div className="chip-row" style={{ marginBottom: "var(--s3)" }}>
                    {c.object_list.map((o) => (
                      <Chip key={o} mono>
                        {o}
                      </Chip>
                    ))}
                  </div>
                )}
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
                    onClick={() => onPromote(c.id)}
                  >
                    记入事件
                  </button>
                </div>
              </Card>
            ))
          )}

          {(data?.filtered_count ?? 0) > 0 && (
            <p className="muted" style={{ marginTop: "var(--s5)" }}>
              本批过滤 {data?.filtered_count} 条{" · "}
              <button
                type="button"
                className="link-btn"
                disabled={busy}
                onClick={onShowFiltered}
              >
                查看漏杀
              </button>
            </p>
          )}
        </>
      )}
      </div>

      {showFiltered && filtered && (
        <Modal title="被过滤条目（漏杀可查）" onClose={() => setShowFiltered(false)}>
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
