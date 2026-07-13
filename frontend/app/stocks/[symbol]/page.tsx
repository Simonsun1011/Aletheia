"use client";

import { useParams } from "next/navigation";
import { useEffect, useState } from "react";
import { apiGet } from "@/lib/api";
import { TopNav, Card, Chip, Empty, Skeleton } from "@/components/ui";
import { TypeTag } from "@/components/info";
import { toast } from "@/components/toast";
import { LabeledKvTable } from "@/components/label";
import { TermRichText } from "@/components/term-rich-text";
import { dateRelative } from "@/lib/format";
import { ListPager, usePagedItems } from "@/components/list-pager";

type Snapshot = {
  symbol: string;
  as_of: string;
  price: Record<string, number | null>;
  anchors: Record<string, number | null>;
  risk: Record<string, number | null>;
  relative: Record<string, number | string | null>;
  warnings: string[];
};

export default function StockSnapshotPage() {
  const params = useParams();
  const symbol = String(params.symbol || "").toUpperCase();
  const [data, setData] = useState<Snapshot | null>(null);
  const [loading, setLoading] = useState(true);
  const [events, setEvents] = useState<
    { id: string; fact_text: string; event_date?: string | null; category?: string | null }[]
  >([]);

  useEffect(() => {
    if (!symbol) return;
    setLoading(true);
    apiGet<Snapshot>(`/tickers/${symbol}/snapshot`)
      .then(setData)
      .catch((e) => toast.error(String((e as Error).message ?? e)))
      .finally(() => setLoading(false));
    apiGet<
      { id: string; fact_text: string; event_date?: string | null; category?: string | null }[]
    >(`/changefeed?object=${encodeURIComponent(symbol)}`)
      .then(setEvents)
      .catch(() => setEvents([]));
  }, [symbol]);

  const eventsPage = usePagedItems(events, `${symbol}|${events.length}`);

  return (
    <main>
      <TopNav />
      <h1>{symbol} · 量化快照</h1>
      <p className="page-intro">
        数字表格 + 已确认事件（不含未确认草稿）。经典公开指标，工具只呈现事实与定位。
      </p>

      {loading && !data ? (
        <div className="grid-2">
          <Card title="价格">
            <Skeleton lines={4} />
          </Card>
          <Card title="锚点">
            <Skeleton lines={4} />
          </Card>
        </div>
      ) : (
        data && (
          <>
            <div className="chip-row" style={{ marginBottom: "var(--s4)" }}>
              <Chip>数据日期 {dateRelative(data.as_of)}</Chip>
              {data.warnings.length > 0 && (
                <span className="badge-due">{data.warnings.length} warnings</span>
              )}
            </div>

            <div className="grid-2">
              <Card title="价格" flush>
                <LabeledKvTable
                  data={{ price: data.price }}
                  context={`${symbol} 快照·价格`}
                />
              </Card>
              <Card title="锚点" flush>
                <LabeledKvTable
                  data={{ anchors: data.anchors }}
                  context={`${symbol} 快照·锚点`}
                />
              </Card>
              <Card title="风险" flush>
                <LabeledKvTable
                  data={{ risk: data.risk }}
                  context={`${symbol} 快照·风险`}
                />
              </Card>
              <Card title="相对表现" flush>
                <LabeledKvTable
                  data={{ relative: data.relative }}
                  context={`${symbol} 快照·相对`}
                />
              </Card>
            </div>

            <Card title="已确认事件" flush>
              {events.length === 0 ? (
                <Empty>暂无已确认 Change Feed 事件——从信息流卡片记入。</Empty>
              ) : (
                <>
                  <div className="list-count">
                    <span>共 {events.length} 条</span>
                  </div>
                  <div className="list-scroll">
                    <ul className="item-list" style={{ padding: "0 20px 16px" }}>
                      {eventsPage.slice.map((ev) => (
                        <li key={ev.id} className="item">
                          <div className="info-row" style={{ marginBottom: 6 }}>
                            <TypeTag type="fact" />
                            <div className="chip-row">
                              {ev.category && <Chip>{ev.category}</Chip>}
                              {ev.event_date && (
                                <span className="muted">
                                  {dateRelative(ev.event_date)}
                                </span>
                              )}
                            </div>
                          </div>
                          <div>
                            <TermRichText
                              text={ev.fact_text}
                              context={`${symbol} 快照·事件`}
                            />
                          </div>
                        </li>
                      ))}
                    </ul>
                    <div style={{ padding: "0 20px 16px" }}>
                      <ListPager
                        page={eventsPage.page}
                        pageCount={eventsPage.pageCount}
                        total={eventsPage.total}
                        onChange={eventsPage.setPage}
                      />
                    </div>
                  </div>
                </>
              )}
            </Card>

            {data.warnings.length > 0 && (
              <Card title="数据缺口提示">
                <ul className="item-list">
                  {data.warnings.map((w) => (
                    <li key={w} className="item muted">
                      {w}
                    </li>
                  ))}
                </ul>
              </Card>
            )}
          </>
        )
      )}
    </main>
  );
}
