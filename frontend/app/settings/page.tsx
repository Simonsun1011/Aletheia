"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";
import { apiGet } from "@/lib/api";

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

function money(v: number | null | undefined): string {
  if (v == null || Number.isNaN(v)) return "—";
  return `$${v.toFixed(4)}`;
}

export default function SettingsPage() {
  const [data, setData] = useState<UsageResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    const body = await apiGet<UsageResponse>("/usage?period=month");
    setData(body);
  }, []);

  useEffect(() => {
    refresh().catch((e) => setError(String((e as Error).message ?? e)));
  }, [refresh]);

  const last7 = useMemo(() => {
    if (!data?.by_day?.length) return [];
    return [...data.by_day].sort((a, b) => a.key.localeCompare(b.key)).slice(-7);
  }, [data]);

  const overBudget =
    data?.monthly_budget_usd != null &&
    data.month_to_date_cost_usd >= data.monthly_budget_usd;

  return (
    <main>
      <p className="nav">
        <Link href="/">← 判断日志</Link>
        {" · "}
        <Link href="/feed">信息流</Link>
        {" · "}
        <Link href="/console">操作台</Link>
        {" · "}
        <Link href="/settings">设置</Link>
      </p>
      <h1>设置</h1>
      <p className="muted">LLM 用量（本月 UTC）</p>

      {error && <p className="error">{error}</p>}

      {data && (
        <section>
          <h2>本月成本</h2>
          <table>
            <tbody>
              <tr>
                <th>预估成本</th>
                <td>{money(data.month_to_date_cost_usd)}</td>
              </tr>
              <tr>
                <th>月度预算</th>
                <td>
                  {data.monthly_budget_usd == null
                    ? "未设置 MONTHLY_LLM_BUDGET_USD"
                    : money(data.monthly_budget_usd)}
                  {overBudget ? " （已超限）" : ""}
                </td>
              </tr>
              <tr>
                <th>调用次数</th>
                <td>{data.calls}</td>
              </tr>
              <tr>
                <th>tokens in / out</th>
                <td>
                  {data.tokens_in} / {data.tokens_out}
                </td>
              </tr>
            </tbody>
          </table>

          <h2>按 purpose</h2>
          <table>
            <thead>
              <tr>
                <th>purpose</th>
                <th>calls</th>
                <th>tokens in</th>
                <th>tokens out</th>
                <th>est cost</th>
              </tr>
            </thead>
            <tbody>
              {data.by_purpose.map((r) => (
                <tr key={r.key}>
                  <td>{r.key}</td>
                  <td>{r.calls}</td>
                  <td>{r.tokens_in}</td>
                  <td>{r.tokens_out}</td>
                  <td>{money(r.est_cost_usd)}</td>
                </tr>
              ))}
              {!data.by_purpose.length && (
                <tr>
                  <td colSpan={5} className="muted">
                    本月尚无调用
                  </td>
                </tr>
              )}
            </tbody>
          </table>

          <h2>最近 7 天</h2>
          <table>
            <thead>
              <tr>
                <th>日期</th>
                <th>calls</th>
                <th>tokens in</th>
                <th>tokens out</th>
                <th>est cost</th>
              </tr>
            </thead>
            <tbody>
              {last7.map((r) => (
                <tr key={r.key}>
                  <td>{r.key}</td>
                  <td>{r.calls}</td>
                  <td>{r.tokens_in}</td>
                  <td>{r.tokens_out}</td>
                  <td>{money(r.est_cost_usd)}</td>
                </tr>
              ))}
              {!last7.length && (
                <tr>
                  <td colSpan={5} className="muted">
                    无数据
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </section>
      )}
    </main>
  );
}
