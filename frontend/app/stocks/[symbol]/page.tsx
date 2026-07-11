"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";
import { apiGet } from "@/lib/api";

type Snapshot = {
  symbol: string;
  as_of: string;
  price: Record<string, number | null>;
  anchors: Record<string, number | null>;
  risk: Record<string, number | null>;
  relative: Record<string, number | string | null>;
  warnings: string[];
};

function fmt(v: number | string | null | undefined, digits = 4): string {
  if (v === null || v === undefined) return "—";
  if (typeof v === "string") return v;
  if (Math.abs(v) < 0.01 && v !== 0) return v.toExponential(2);
  return v.toFixed(digits);
}

function pct(v: number | null | undefined): string {
  if (v === null || v === undefined) return "—";
  return `${(v * 100).toFixed(2)}%`;
}

function Table({
  title,
  rows,
}: {
  title: string;
  rows: [string, string][];
}) {
  return (
    <section>
      <h2>{title}</h2>
      <table>
        <tbody>
          {rows.map(([k, v]) => (
            <tr key={k}>
              <th>{k}</th>
              <td>{v}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}

export default function StockSnapshotPage() {
  const params = useParams();
  const symbol = String(params.symbol || "").toUpperCase();
  const [data, setData] = useState<Snapshot | null>(null);
  const [events, setEvents] = useState<
    { id: string; fact_text: string; event_date?: string | null; category?: string | null }[]
  >([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!symbol) return;
    apiGet<Snapshot>(`/tickers/${symbol}/snapshot`)
      .then(setData)
      .catch((e) => setError(String(e.message ?? e)));
    apiGet<{ id: string; fact_text: string; event_date?: string | null; category?: string | null }[]>(
      `/changefeed?object=${encodeURIComponent(symbol)}`
    )
      .then(setEvents)
      .catch(() => setEvents([]));
  }, [symbol]);

  return (
    <main>
      <p>
        <Link href="/">← 判断日志</Link>
        {" · "}
        <Link href="/feed">信息流</Link>
      </p>
      <h1>{symbol} · 量化快照</h1>
      <p className="muted">Slice 2+3：数字表格 + 已确认事件（无未确认草稿）。</p>
      {error && <p className="error">{error}</p>}
      {!error && !data && <p className="muted">加载中…</p>}
      {data && (
        <>
          <p className="muted">
            as_of {data.as_of}
            {data.warnings.length > 0
              ? ` · ${data.warnings.length} warnings`
              : ""}
          </p>
          <Table
            title="价格"
            rows={[
              ["last", fmt(data.price.last, 2)],
              ["chg_1d", pct(data.price.chg_1d as number | null)],
              ["chg_5d", pct(data.price.chg_5d as number | null)],
              ["chg_20d", pct(data.price.chg_20d as number | null)],
              ["chg_60d", pct(data.price.chg_60d as number | null)],
            ]}
          />
          <Table
            title="锚点"
            rows={Object.entries(data.anchors).map(([k, v]) => [
              k,
              k === "drawdown_52w" ? pct(v) : fmt(v, 2),
            ])}
          />
          <Table
            title="风险"
            rows={[
              ["atr14", fmt(data.risk.atr14, 2)],
              ["rsi14", fmt(data.risk.rsi14, 1)],
              ["vol_20d_ann", pct(data.risk.vol_20d_ann as number | null)],
            ]}
          />
          <Table
            title="相对表现"
            rows={[
              ["sector_etf", String(data.relative.sector_etf ?? "—")],
              ["vs_qqq_20d", pct(data.relative.vs_qqq_20d as number | null)],
              ["vs_qqq_60d", pct(data.relative.vs_qqq_60d as number | null)],
              [
                "vs_sector_20d",
                pct(data.relative.vs_sector_20d as number | null),
              ],
              [
                "vs_sector_60d",
                pct(data.relative.vs_sector_60d as number | null),
              ],
            ]}
          />
          <section>
            <h2>已确认事件</h2>
            {events.length === 0 && (
              <p className="muted">暂无已确认 Change Feed 事件</p>
            )}
            {events.map((ev) => (
              <div key={ev.id} className="note-item">
                <div className="muted">
                  {ev.category ?? "—"} · {ev.event_date ?? "—"}
                </div>
                <div>{ev.fact_text}</div>
              </div>
            ))}
          </section>
          {data.warnings.length > 0 && (
            <section>
              <h2>warnings</h2>
              <ul>
                {data.warnings.map((w) => (
                  <li key={w}>{w}</li>
                ))}
              </ul>
            </section>
          )}
        </>
      )}
    </main>
  );
}
