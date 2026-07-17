"use client";

import { useCallback, useEffect, useState } from "react";
import { apiGet, apiPost, JudgmentChain } from "@/lib/api";
import { TopNav, Card, Chip, Empty, Skeleton, Modal } from "@/components/ui";
import { toast } from "@/components/toast";
import { pctText, signClass, dateRelative } from "@/lib/format";
import { ListPager, usePagedItems } from "@/components/list-pager";

type SettleDraft = {
  root_id: string;
  object: string;
  jtype?: string | null;
  direction?: string | null;
  horizon_days?: number | null;
  confidence?: number | null;
  created_at?: string;
  expires_on?: string | null;
  snapshot_date?: string | null;
  window_start?: string | null;
  window_end?: string | null;
  object_return?: number | null;
  qqq_return?: number | null;
  sector_etf?: string | null;
  sector_return?: number | null;
  excess_vs_qqq?: number | null;
  excess_vs_sector?: number | null;
  warnings?: string[];
  review_text?: null;
};

function Pct({ v }: { v: number | null | undefined }) {
  return <span className={`num ${signClass(v)}`}>{pctText(v)}</span>;
}

export default function ReviewsPage() {
  const [due, setDue] = useState<JudgmentChain[]>([]);
  const [loading, setLoading] = useState(true);
  const [selected, setSelected] = useState<string | null>(null);
  const [draft, setDraft] = useState<SettleDraft | null>(null);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const rows = await apiGet<JudgmentChain[]>("/reviews/due");
      setDue(rows);
    } catch (e) {
      toast.error(String((e as Error).message ?? e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  const duePage = usePagedItems(due, due.length);

  async function onSettle(rootId: string) {
    setBusy(true);
    setSelected(rootId);
    try {
      const body = await apiPost<SettleDraft>(`/reviews/${rootId}/settle`, {});
      setDraft(body);
      setText("");
    } catch (e) {
      toast.error(String((e as Error).message ?? e));
    } finally {
      setBusy(false);
    }
  }

  async function onSubmitReview() {
    if (!selected || !text.trim()) return;
    setBusy(true);
    try {
      await apiPost(`/judgments/${selected}/entries`, {
        kind: "review",
        text: text.trim(),
      });
      setDraft(null);
      setSelected(null);
      setText("");
      toast.success("复盘已提交，链条关闭");
      await refresh();
    } catch (e) {
      toast.error(String((e as Error).message ?? e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <main>
      <TopNav />
      <h1>复盘</h1>
      <p className="page-intro">
        到期且仍 open 的判断链。数字由服务端结算；结论文字由你亲笔——工具不算对错。
      </p>

      <Card title="到期列表">
        {loading ? (
          <Skeleton lines={4} />
        ) : due.length === 0 ? (
          <Empty icon="✓">暂无到期项——判断到期后会出现在这里等你复盘。</Empty>
        ) : (
          <>
            <div className="list-count">
              <span>共 {due.length} 项到期</span>
            </div>
            <div className="list-scroll tall">
              <ul className="item-list">
                {duePage.slice.map((c) => {
              const cur =
                [...c.entries]
                  .filter((e) => e.kind === "original" || e.kind === "revision")
                  .sort((a, b) => {
                    const t = a.created_at.localeCompare(b.created_at);
                    return t !== 0 ? t : a.id.localeCompare(b.id);
                  })
                  .at(-1) ?? c.entries[0];
              return (
                <li key={c.root_id} className="item">
                  <div className="chain-meta">
                    <strong style={{ color: "var(--text-1)", fontWeight: 600 }}>
                      {c.object}
                    </strong>
                    <Chip>{cur?.jtype}</Chip>
                    {cur?.direction && <Chip>{cur.direction}</Chip>}
                    <span className="badge-due">
                      到期 {dateRelative(cur?.expires_on)}
                    </span>
                  </div>
                  <div style={{ marginBottom: "var(--s2)" }}>{cur?.text}</div>
                  <button
                    type="button"
                    className="secondary btn-small"
                    disabled={busy}
                    onClick={() => onSettle(c.root_id)}
                  >
                    结算数字
                  </button>
                </li>
              );
            })}
              </ul>
              <ListPager
                page={duePage.page}
                pageCount={duePage.pageCount}
                total={duePage.total}
                onChange={duePage.setPage}
              />
            </div>
          </>
        )}
      </Card>

      {draft && (
        <Modal
          title="结算结果（参考数字）"
          onClose={() => {
            setDraft(null);
            setSelected(null);
          }}
          footer={
            <button
              type="button"
              disabled={busy || !text.trim()}
              onClick={onSubmitReview}
            >
              提交复盘（关闭链条）
            </button>
          }
        >
          <table className="kv">
            <tbody>
              <tr>
                <th>标的收益</th>
                <td>
                  <Pct v={draft.object_return} />
                </td>
              </tr>
              <tr>
                <th>同期 QQQ</th>
                <td>
                  <Pct v={draft.qqq_return} />
                </td>
              </tr>
              <tr>
                <th>行业 ETF</th>
                <td>
                  <span className="chip">{draft.sector_etf ?? "—"}</span>{" "}
                  <Pct v={draft.sector_return} />
                </td>
              </tr>
              <tr>
                <th>超额 vs QQQ</th>
                <td>
                  <Pct v={draft.excess_vs_qqq} />
                </td>
              </tr>
              <tr>
                <th>超额 vs 行业</th>
                <td>
                  <Pct v={draft.excess_vs_sector} />
                </td>
              </tr>
              <tr>
                <th>窗口</th>
                <td className="num">
                  {draft.window_start ?? "—"} → {draft.window_end ?? "—"}（
                  {draft.horizon_days ?? "—"} 交易日）
                </td>
              </tr>
              <tr>
                <th>快照日</th>
                <td>{draft.snapshot_date ?? "null（创建日无快照）"}</td>
              </tr>
            </tbody>
          </table>
          {draft.warnings && draft.warnings.length > 0 && (
            <div className="note-warn">warnings: {draft.warnings.join("; ")}</div>
          )}

          <h3 style={{ marginTop: "var(--s4)" }}>复盘结论</h3>
          <p className="muted" style={{ marginBottom: "var(--s2)" }}>
            工具不算对错；请用自己的话写结论文字。
          </p>
          <textarea
            rows={4}
            value={text}
            onChange={(e) => setText(e.target.value)}
            placeholder="如：窗口内相对 QQQ 为正，主因是……"
          />
        </Modal>
      )}
    </main>
  );
}
