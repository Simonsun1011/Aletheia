"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { apiGet, apiPost } from "@/lib/api";
import { TopNav, Card, Stat, Empty, Skeleton } from "@/components/ui";
import { toast } from "@/components/toast";
import { money, num } from "@/lib/format";
import { useGlossaryOptional } from "@/components/glossary-provider";

type AggRow = {
  key: string;
  tokens_in: number;
  tokens_out: number;
  est_cost_usd: number | null;
  calls: number;
};

type UsageResponse = {
  period: string;
  from: string;
  calls: number;
  tokens_in: number;
  tokens_out: number;
  est_cost_usd: number | null;
  month_to_date_cost_usd: number;
  monthly_budget_usd: number | null;
  by_purpose: AggRow[];
  by_day: AggRow[];
  by_model: AggRow[];
};

type TagRow = {
  tag_id: string;
  kind: string;
  display_en: string;
  display_zh: string;
  status: string;
  created_at: string;
};

function UsageTable({ rows, keyLabel }: { rows: AggRow[]; keyLabel: string }) {
  if (!rows.length) return <Empty>本月尚无调用记录。</Empty>;
  return (
    <table className="numeric">
      <thead>
        <tr>
          <th>{keyLabel}</th>
          <th>calls</th>
          <th>tokens in</th>
          <th>tokens out</th>
          <th>est cost</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((r) => (
          <tr key={r.key}>
            <td style={{ textAlign: "left" }}>{r.key}</td>
            <td>{num(r.calls)}</td>
            <td>{num(r.tokens_in)}</td>
            <td>{num(r.tokens_out)}</td>
            <td>{money(r.est_cost_usd, 4)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

export default function SettingsPage() {
  const [data, setData] = useState<UsageResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [resetBusy, setResetBusy] = useState(false);
  const [proposed, setProposed] = useState<TagRow[]>([]);
  const [tagBusy, setTagBusy] = useState(false);
  const glossary = useGlossaryOptional();

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const body = await apiGet<UsageResponse>("/usage?period=month");
      setData(body);
    } catch (e) {
      toast.error(String((e as Error).message ?? e));
    } finally {
      setLoading(false);
    }
  }, []);

  const refreshProposed = useCallback(async () => {
    try {
      const rows = await apiGet<TagRow[]>("/tags?status=proposed");
      setProposed(rows);
    } catch (e) {
      toast.error(String((e as Error).message ?? e));
    }
  }, []);

  useEffect(() => {
    refresh();
    refreshProposed();
  }, [refresh, refreshProposed]);

  const last7 = useMemo(() => {
    if (!data?.by_day?.length) return [];
    return [...data.by_day].sort((a, b) => a.key.localeCompare(b.key)).slice(-7);
  }, [data]);

  const overBudget =
    data?.monthly_budget_usd != null &&
    data.month_to_date_cost_usd >= data.monthly_budget_usd;

  const knownCount =
    glossary?.terms.filter((t) => t.state === "known").length ?? 0;
  const savedCount =
    glossary?.terms.filter((t) => t.state === "saved").length ?? 0;

  async function onResetKnown() {
    if (!glossary) return;
    setResetBusy(true);
    try {
      await glossary.resetKnown();
    } catch (e) {
      toast.error(String((e as Error).message ?? e));
    } finally {
      setResetBusy(false);
    }
  }

  async function onRestore(term: string) {
    if (!glossary) return;
    setResetBusy(true);
    try {
      await glossary.setState(term, "unknown");
      toast.success(`已恢复：${term}`);
    } catch (e) {
      toast.error(String((e as Error).message ?? e));
    } finally {
      setResetBusy(false);
    }
  }

  async function onApproveTag(tagId: string) {
    setTagBusy(true);
    try {
      await apiPost(`/tags/${encodeURIComponent(tagId)}/approve`, {});
      toast.success(`已批准：${tagId}`);
      await refreshProposed();
    } catch (e) {
      toast.error(String((e as Error).message ?? e));
    } finally {
      setTagBusy(false);
    }
  }

  async function onRejectTag(tagId: string) {
    setTagBusy(true);
    try {
      await apiPost(`/tags/${encodeURIComponent(tagId)}/reject`, {});
      toast.success(`已拒绝：${tagId}`);
      await refreshProposed();
    } catch (e) {
      toast.error(String((e as Error).message ?? e));
    } finally {
      setTagBusy(false);
    }
  }

  return (
    <main>
      <TopNav />
      <h1>设置</h1>
      <p className="page-intro">
        标签人审、术语标记、LLM 用量（本月 UTC）。预算硬约束：基础设施月费 ≤ $10。
      </p>

      <Card title="待审标签（AI 建议）">
        <p className="muted" style={{ marginBottom: "var(--s3)" }}>
          digest 提出的新主题标签默认不生效；批准后可作筛选项，拒绝后丢弃。
        </p>
        {proposed.length === 0 ? (
          <Empty>暂无待审标签。</Empty>
        ) : (
          <ul className="item-list">
            {proposed.map((t) => (
              <li key={t.tag_id} className="item">
                <div
                  style={{
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "space-between",
                    gap: 12,
                  }}
                >
                  <div>
                    <strong>{t.display_en}</strong>
                    {t.display_zh !== t.display_en && (
                      <span className="muted"> · {t.display_zh}</span>
                    )}
                    <div className="muted" style={{ fontSize: 12 }}>
                      {t.tag_id} · {t.created_at}
                    </div>
                  </div>
                  <div className="actions" style={{ margin: 0 }}>
                    <button
                      type="button"
                      className="btn-small"
                      disabled={tagBusy}
                      onClick={() => onApproveTag(t.tag_id)}
                    >
                      批准
                    </button>
                    <button
                      type="button"
                      className="secondary btn-small"
                      disabled={tagBusy}
                      onClick={() => onRejectTag(t.tag_id)}
                    >
                      拒绝
                    </button>
                  </div>
                </div>
              </li>
            ))}
          </ul>
        )}
      </Card>

      <Card title="术语标记">
        <p className="muted" style={{ marginBottom: "var(--s3)" }}>
          「忽略」= 全站不再弹出该术语的悬停/展开解释（操作台字段与信息流摘要均生效）。
          下方可展开查看并单项恢复。「已入库」为已导出 Obsidian 的术语。
        </p>
        <div className="stat-grid" style={{ marginBottom: "var(--s3)" }}>
          <Stat value={num(knownCount)} label="已忽略 (known)" />
          <Stat value={num(savedCount)} label="已入库 (saved)" />
          <Stat
            value={glossary?.exportConfigured ? "已配置" : "未配置"}
            label="OBSIDIAN_EXPORT_DIR"
            tone={glossary?.exportConfigured ? undefined : "neg"}
          />
        </div>

        <details className="note" style={{ marginBottom: "var(--s3)" }}>
          <summary>已忽略的说明（{knownCount}）▸</summary>
          {knownCount === 0 ? (
            <p className="muted" style={{ marginTop: "var(--s2)" }}>
              暂无忽略项。在术语浮层点「忽略」后会出现在此。
            </p>
          ) : (
            <ul className="item-list" style={{ marginTop: "var(--s2)" }}>
              {(glossary?.terms.filter((t) => t.state === "known") ?? []).map(
                (t) => (
                  <li key={t.term} className="item">
                    <div
                      style={{
                        display: "flex",
                        alignItems: "flex-start",
                        justifyContent: "space-between",
                        gap: 12,
                      }}
                    >
                      <div style={{ minWidth: 0 }}>
                        <div style={{ fontWeight: 600 }}>{t.term}</div>
                        {t.one_liner && (
                          <p
                            className="muted"
                            style={{ margin: "4px 0 0", fontSize: 13 }}
                          >
                            {t.one_liner}
                          </p>
                        )}
                      </div>
                      <button
                        type="button"
                        className="secondary btn-small"
                        disabled={resetBusy}
                        onClick={() => onRestore(t.term)}
                      >
                        恢复
                      </button>
                    </div>
                  </li>
                )
              )}
            </ul>
          )}
        </details>

        <div className="actions">
          <button
            type="button"
            className="secondary"
            disabled={resetBusy || knownCount === 0}
            onClick={onResetKnown}
          >
            全部恢复忽略标记
          </button>
        </div>
        {!glossary?.exportConfigured && (
          <p className="muted" style={{ marginTop: "var(--s2)" }}>
            在 .env 设置 OBSIDIAN_EXPORT_DIR 后，「加入知识笔记」可用。路径含空格勿拆分。
          </p>
        )}
      </Card>

      {loading && !data ? (
        <Card title="本月成本">
          <Skeleton lines={3} />
        </Card>
      ) : (
        data && (
          <>
            <Card title="本月成本">
              {overBudget && (
                <div className="note-warn">
                  已达/超月度预算（{money(data.monthly_budget_usd)}）——请节制
                  AI 调用。
                </div>
              )}
              <div className="stat-grid">
                <Stat
                  value={money(data.month_to_date_cost_usd)}
                  label="本月预估成本"
                  tone={overBudget ? "neg" : undefined}
                />
                <Stat
                  value={
                    data.monthly_budget_usd == null
                      ? "未设置"
                      : money(data.monthly_budget_usd)
                  }
                  label="月度预算"
                />
                <Stat value={num(data.calls)} label="调用次数" />
                <Stat
                  value={`${num(data.tokens_in)} / ${num(data.tokens_out)}`}
                  label="tokens in / out"
                />
              </div>
              {data.monthly_budget_usd == null && (
                <p className="muted" style={{ marginTop: "var(--s3)" }}>
                  未设置环境变量 MONTHLY_LLM_BUDGET_USD。
                </p>
              )}
            </Card>

            <Card title="按 purpose">
              <UsageTable rows={data.by_purpose} keyLabel="purpose" />
            </Card>

            <Card title="最近 7 天">
              <UsageTable rows={last7} keyLabel="日期" />
            </Card>
          </>
        )
      )}
    </main>
  );
}
