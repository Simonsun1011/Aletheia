"use client";

import { FormEvent, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { apiGet, apiPost, apiPostLlm, JudgmentChain } from "@/lib/api";
import { TopNav, Card, Chip, Empty, Skeleton, Modal } from "@/components/ui";
import { TickerCombobox } from "@/components/ticker-combobox";
import { TypeTag } from "@/components/info";
import { toast } from "@/components/toast";
import { LabeledKvTable } from "@/components/label";
import { UnitTag, CountPill } from "@/components/badge";
import { TermRichText } from "@/components/term-rich-text";
import { money, num, dateShort, dateRelative, fixed } from "@/lib/format";
import {
  getLastConsoleSymbol,
  setLastConsoleSymbol,
  markScanPending,
  clearScanPending,
  isScanPendingToday,
} from "@/lib/console-session";

type PanelNote = { title: string; body: string } | null;

type MineEvent = {
  id?: string;
  fact_text?: string;
  event_date?: string | null;
  category?: string | null;
  scope?: string | null;
  source_url?: string | null;
};

type MineCard = {
  id?: string;
  title?: string;
  summary?: string | null;
  source?: string | null;
  published_at?: string | null;
  url?: string;
};

type NarrativePoint = {
  attributed_to: string;
  point: string;
  source_url: string;
  date?: string;
};

type ConsolePayload = {
  symbol: string;
  as_of: string;
  amount: number;
  window: number;
  search_model_configured?: boolean;
  macro: { data: Record<string, number | null> | null; note: PanelNote } | null;
  fundamental: { data: Record<string, unknown> | null; note: PanelNote } | null;
  narrative: {
    data: {
      mine: {
        events: MineEvent[];
        feed_cards: MineCard[];
        label?: string;
      };
      ai_scan:
        | ({
            id: string;
            label?: string;
            date?: string;
            payload: {
              dominant_narrative: string;
              bull_points: NarrativePoint[];
              bear_points: NarrativePoint[];
              neutral_points?: NarrativePoint[];
              recent_events?: {
                date?: string | null;
                fact: string;
                source_url: string;
              }[];
            };
          })
        | null;
      ai_scan_label?: string;
    } | null;
    note: PanelNote;
  } | null;
  technical: { data: Record<string, unknown> | null; note: PanelNote } | null;
  plan: {
    id: string;
    ladder_api?: {
      tranche: number;
      limit_price: number;
      vs_last: string;
      amount: number;
      shares: number;
      near_anchors: string;
    }[];
    time_stop?: string;
    earnings_note?: string;
    status: string;
  } | null;
  warnings: string[];
};

function NoteBlock({ note }: { note: PanelNote }) {
  if (!note) return null;
  return (
    <details className="note">
      <summary>{note.title} ▸</summary>
      <p>{note.body}</p>
    </details>
  );
}

function PointList({
  points,
  stance,
}: {
  points: NarrativePoint[];
  stance: "bull" | "bear" | "neutral";
}) {
  return (
    <ul className="item-list">
      {points.map((p) => (
        <li key={p.source_url + p.point} className="item">
          <div className={`stance stance-${stance}`}>
            <div className="info-row" style={{ marginBottom: 6 }}>
              <TypeTag type="view" />
              <span className="muted" style={{ fontFamily: "var(--mono)", fontSize: 11 }}>
                {p.date ?? "—"} · {p.attributed_to}
              </span>
            </div>
            <div>
              {p.point}{" "}
              <a href={p.source_url} target="_blank" rel="noreferrer">
                来源 ↗
              </a>
            </div>
          </div>
        </li>
      ))}
    </ul>
  );
}

type MidItem =
  | { kind: "neutral"; date: string; point: NarrativePoint }
  | {
      kind: "event";
      date: string;
      fact: string;
      source_url: string;
    };

function mergeMidColumn(
  neutrals: NarrativePoint[],
  events: { date?: string | null; fact: string; source_url: string }[]
): MidItem[] {
  const items: MidItem[] = [
    ...neutrals.map((p) => ({
      kind: "neutral" as const,
      date: p.date ?? "",
      point: p,
    })),
    ...events.map((e) => ({
      kind: "event" as const,
      date: e.date ?? "",
      fact: e.fact,
      source_url: e.source_url,
    })),
  ];
  items.sort((a, b) => (b.date || "").localeCompare(a.date || ""));
  return items;
}

function MidColumnList({ items }: { items: MidItem[] }) {
  if (items.length === 0) return <Empty>暂无中立评论或近期事实</Empty>;
  return (
    <ul className="item-list">
      {items.map((it, i) =>
        it.kind === "neutral" ? (
          <li key={"n-" + it.point.source_url + i} className="item">
            <div className="stance stance-neutral">
              <div className="info-row" style={{ marginBottom: 6 }}>
                <TypeTag type="view" />
                <span className="muted" style={{ fontFamily: "var(--mono)", fontSize: 11 }}>
                  {it.date || "—"} · {it.point.attributed_to}
                </span>
              </div>
              <div>
                {it.point.point}{" "}
                <a href={it.point.source_url} target="_blank" rel="noreferrer">
                  来源 ↗
                </a>
              </div>
            </div>
          </li>
        ) : (
          <li key={"e-" + it.source_url + i} className="item">
            <div className="stance stance-neutral">
              <div className="info-row" style={{ marginBottom: 4 }}>
                <TypeTag type="fact" />
                <span className="muted" style={{ fontFamily: "var(--mono)", fontSize: 11 }}>
                  {it.date || "—"}
                </span>
              </div>
              <div>{it.fact}</div>
              {it.source_url && (
                <a href={it.source_url} target="_blank" rel="noreferrer">
                  来源 ↗
                </a>
              )}
            </div>
          </li>
        )
      )}
    </ul>
  );
}

export default function ConsolePage() {
  const [symbol, setSymbol] = useState("AMAT");
  const [amount, setAmount] = useState("5000");
  const [windowDays, setWindowDays] = useState("5");
  const [data, setData] = useState<ConsolePayload | null>(null);
  const [loading, setLoading] = useState(false);
  const [busy, setBusy] = useState(false);
  const [text, setText] = useState("");
  const [scanBusy, setScanBusy] = useState(false);
  const [scanElapsedSec, setScanElapsedSec] = useState(0);
  const [scanNotice, setScanNotice] = useState<string | null>(null);
  const [scanPendingHint, setScanPendingHint] = useState<string | null>(null);
  const [chains, setChains] = useState<JudgmentChain[]>([]);
  const [positions, setPositions] = useState<
    { ticker: string; shares: number; avg_price: number; judgment_linked_count: number }[]
  >([]);
  const [positionsLoading, setPositionsLoading] = useState(true);
  const [fillOpen, setFillOpen] = useState(false);
  const [fillSide, setFillSide] = useState<"buy" | "sell">("buy");
  const [fillShares, setFillShares] = useState("");
  const [fillPrice, setFillPrice] = useState("");
  const [fillDate, setFillDate] = useState(
    () => new Date().toISOString().slice(0, 10)
  );
  const [fillFees, setFillFees] = useState("0");
  const [fillJudgment, setFillJudgment] = useState("");
  const [fillNote, setFillNote] = useState("");
  const [narrTab, setNarrTab] = useState<"bull" | "mid" | "bear">("bull");
  const restoredRef = useRef(false);
  const scanPollRef = useRef<number | null>(null);

  const refreshJudgments = useCallback(async (sym: string) => {
    const list = await apiGet<JudgmentChain[]>(
      `/judgments?object=${encodeURIComponent(sym)}&origin=console`
    );
    setChains(list.slice(0, 20));
  }, []);

  const refreshPositions = useCallback(async () => {
    try {
      const list = await apiGet<
        {
          ticker: string;
          shares: number;
          avg_price: number;
          judgment_linked_count: number;
        }[]
      >("/positions");
      setPositions(list);
    } catch (err) {
      toast.error(String((err as Error).message ?? err));
    } finally {
      setPositionsLoading(false);
    }
  }, []);

  const loadSymbol = useCallback(
    async (sym: string, opts?: { amount?: string; window?: string }) => {
      const ticker = sym.trim().toUpperCase();
      if (!ticker) return;
      const amt = opts?.amount ?? amount;
      const win = opts?.window ?? windowDays;
      setLoading(true);
      setScanPendingHint(null);
      try {
        const body = await apiGet<ConsolePayload>(
          `/console/${encodeURIComponent(ticker)}?amount=${amt}&window=${win}`
        );
        setSymbol(body.symbol);
        setData(body);
        setLastConsoleSymbol(body.symbol);
        await refreshJudgments(body.symbol);
        await refreshPositions();

        // 回访：若标记扫描中且今日缓存仍缺 → 提示，绝不自动 narrative-scan
        const cached = body.narrative?.data?.ai_scan;
        const hasTodayCache = !!cached?.date;
        if (isScanPendingToday(body.symbol) && !hasTodayCache) {
          setScanPendingHint(
            "后台扫描可能仍在进行或已完成——可点【使用今日缓存】刷新（不会自动重跑）。"
          );
        } else if (hasTodayCache) {
          clearScanPending(body.symbol);
        }
      } catch (err) {
        toast.error(String((err as Error).message ?? err));
      } finally {
        setLoading(false);
      }
    },
    [amount, windowDays, refreshJudgments, refreshPositions]
  );

  async function load(e?: FormEvent) {
    e?.preventDefault();
    await loadSymbol(symbol);
  }

  // 落地：持仓无条件拉取；回访：恢复上次标的（只读缓存，不扫 AI）
  useEffect(() => {
    if (restoredRef.current) return;
    restoredRef.current = true;
    refreshPositions();
    const last = getLastConsoleSymbol();
    if (last) {
      setSymbol(last);
      void loadSymbol(last);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps -- 仅挂载一次
  }, []);

  useEffect(() => {
    if (!scanBusy) return;
    setScanElapsedSec(0);
    const t0 = Date.now();
    const id = window.setInterval(() => {
      setScanElapsedSec(Math.floor((Date.now() - t0) / 1000));
    }, 250);
    return () => window.clearInterval(id);
  }, [scanBusy]);

  // 卸载时清掉扫描轮询定时器，避免泄漏
  useEffect(() => {
    return () => {
      if (scanPollRef.current !== null) {
        window.clearInterval(scanPollRef.current);
        scanPollRef.current = null;
      }
    };
  }, []);

  async function fetchLatestScan(
    sym: string
  ): Promise<{ id?: string; created_at?: string } | null> {
    try {
      return await apiGet<{ id?: string; created_at?: string }>(
        `/console/${encodeURIComponent(sym)}/narrative-scan`
      );
    } catch {
      // 404 = 今日尚无缓存，视作「还没结果」
      return null;
    }
  }

  // 扫描是长耗时 LLM 调用；单靠一个可能超时的 POST 驱动 spinner 会出现
  // “后台已结束但前端一直转”的假象。这里额外轮询 GET 结果，POST 与轮询
  // 谁先确认到结果谁就收尾；POST 超时不再当作错误，交由轮询兜底。
  async function runScan(force: boolean) {
    if (!data) return;
    const sym = data.symbol;
    setScanBusy(true);
    setScanNotice(null);
    setScanPendingHint(null);
    markScanPending(sym);

    // force 刷新时需要区分「新扫描」；记录基线 id/created_at
    const baseline = force ? await fetchLatestScan(sym) : null;
    const baselineKey = baseline
      ? `${baseline.id ?? ""}|${baseline.created_at ?? ""}`
      : "";

    let settled = false;
    const stopPoll = () => {
      if (scanPollRef.current !== null) {
        window.clearInterval(scanPollRef.current);
        scanPollRef.current = null;
      }
    };
    const finish = async (notice?: string | null) => {
      if (settled) return;
      settled = true;
      stopPoll();
      if (notice !== undefined) setScanNotice(notice);
      try {
        const body = await apiGet<ConsolePayload>(
          `/console/${encodeURIComponent(sym)}?amount=${amount}&window=${windowDays}`
        );
        setData(body);
        if (body.narrative?.data?.ai_scan) clearScanPending(sym);
      } catch {
        /* 刷新失败不覆盖已拿到的扫描结果 */
      }
      setScanBusy(false);
    };

    const startedAt = Date.now();
    const MAX_MS = 240_000;
    stopPoll();
    scanPollRef.current = window.setInterval(async () => {
      if (settled) {
        stopPoll();
        return;
      }
      if (Date.now() - startedAt > MAX_MS) {
        stopPoll();
        if (!settled) {
          settled = true;
          setScanBusy(false);
          setScanPendingHint(
            "扫描长时间未确认；后台可能仍在运行，可稍后点『使用今日缓存』刷新查看。"
          );
        }
        return;
      }
      const latest = await fetchLatestScan(sym);
      if (!latest) return;
      const key = `${latest.id ?? ""}|${latest.created_at ?? ""}`;
      const isNew = force ? key !== baselineKey : true;
      if (isNew) await finish();
    }, 4000);

    try {
      const scan = await apiPostLlm<{
        notice?: string;
        warning?: string;
        payload?: {
          dominant_narrative?: string;
          bull_points?: unknown[];
          bear_points?: unknown[];
          recent_events?: unknown[];
        };
      }>(
        `/console/${sym}/narrative-scan?force=${force ? "true" : "false"}`,
        {}
      );
      let notice: string | null = null;
      if (scan.notice) {
        notice = scan.notice;
      } else {
        const p = scan.payload;
        const empty =
          !!p &&
          !(p.bull_points?.length || p.bear_points?.length || p.recent_events?.length) &&
          (!p.dominant_narrative || p.dominant_narrative === "暂无新叙事");
        if (empty) notice = "暂无新叙事";
      }
      await finish(notice);
    } catch (err) {
      const msg = String((err as Error).message ?? err);
      if (
        msg.includes("AI_GUARD") ||
        msg.includes("AI_PARSE") ||
        msg.includes("VALIDATION_ERROR")
      ) {
        clearScanPending(sym);
        await finish("暂无新叙事");
      } else if (msg.includes("超时") || msg.includes("timeout") || msg.includes("aborted")) {
        // POST 超时：后端很可能仍在跑并会写库，交给轮询兜底，不弹错误
        if (!settled) {
          setScanPendingHint("请求较久未返回，正在后台确认扫描结果…");
        }
      } else {
        stopPoll();
        if (!settled) {
          settled = true;
          setScanBusy(false);
        }
        toast.error(msg);
      }
    }
  }

  async function submitJudgment(e: FormEvent) {
    e.preventDefault();
    if (!data?.plan?.id || !text.trim()) return;
    setBusy(true);
    try {
      const scanId = data.narrative?.data?.ai_scan?.id;
      const supporting = [
        `plan_id=${data.plan.id}`,
        scanId ? `scan_id=${scanId}` : null,
      ]
        .filter(Boolean)
        .join(";");
      await apiPost("/judgments", {
        object: data.symbol,
        jtype: "action",
        direction: "outperform",
        horizon_days: 20,
        confidence: 0.55,
        text: text.trim(),
        supporting,
        origin: "console",
      });
      setText("");
      toast.success("判断已提交");
      await refreshJudgments(data.symbol);
    } catch (err) {
      toast.error(String((err as Error).message ?? err));
    } finally {
      setBusy(false);
    }
  }

  async function submitFill() {
    if (!data?.symbol) return;
    setBusy(true);
    try {
      await apiPost("/executions", {
        ticker: data.symbol,
        side: fillSide,
        trade_date: fillDate,
        shares: Number(fillShares),
        price: Number(fillPrice),
        fees: fillFees === "" ? null : Number(fillFees),
        plan_id: data.plan?.id ?? null,
        judgment_root_id: fillJudgment || null,
        note: fillNote.trim() || null,
      });
      setFillOpen(false);
      setFillShares("");
      setFillPrice("");
      toast.success("成交已记录");
      await refreshPositions();
    } catch (err) {
      toast.error(String((err as Error).message ?? err));
    } finally {
      setBusy(false);
    }
  }

  const narr = data?.narrative?.data;
  const ai = narr?.ai_scan?.payload;
  const midItems = useMemo(
    () =>
      mergeMidColumn(ai?.neutral_points ?? [], ai?.recent_events ?? []),
    [ai?.neutral_points, ai?.recent_events]
  );

  return (
    <main>
      <TopNav />
      <h1>操作台</h1>
      <p className="page-intro">
        四板块平铺 + 执行方案。叙事区分「我的信息流所见」与「AI 独立扫描」，判断权在你。
      </p>

      <form onSubmit={load} className="inline-form">
        <div className="inline-field ticker-field">
          <label htmlFor="sym">标的</label>
          <TickerCombobox
            id="sym"
            value={symbol}
            onChange={setSymbol}
          />
        </div>
        <div className="inline-field">
          <label htmlFor="amt">预算</label>
          <input id="amt" value={amount} onChange={(e) => setAmount(e.target.value)} />
        </div>
        <div className="inline-field">
          <label htmlFor="win">窗口(日)</label>
          <input
            id="win"
            value={windowDays}
            onChange={(e) => setWindowDays(e.target.value)}
          />
        </div>
        <button type="submit" disabled={loading}>
          {loading ? "加载中…" : "加载"}
        </button>
      </form>

      {/* 持仓落地入口：始终可见，不依赖 data */}
      <Card
        title="持仓"
        aside={
          !positionsLoading && positions.length > 0 ? (
            <CountPill>{positions.length}</CountPill>
          ) : undefined
        }
        flush
      >
        <p className="muted" style={{ margin: "12px 20px 8px" }}>
          按未作废成交聚合。点击一行即可展开该标的操作页。
        </p>
        {positionsLoading ? (
          <Skeleton lines={3} />
        ) : positions.length === 0 ? (
          <Empty>暂无持仓——记录成交后在此聚合显示；也可上方输入标的加载。</Empty>
        ) : (
          <table className="numeric">
            <thead>
              <tr>
                <th>标的</th>
                <th>股数</th>
                <th>加权均价</th>
                <th>关联判断数</th>
              </tr>
            </thead>
            <tbody>
              {positions.map((p) => (
                <tr
                  key={p.ticker}
                  style={{
                    cursor: "pointer",
                    background:
                      data?.symbol === p.ticker ? "var(--subtle)" : undefined,
                  }}
                  onClick={() => {
                    setSymbol(p.ticker);
                    void loadSymbol(p.ticker);
                  }}
                >
                  <td style={{ textAlign: "left", fontFamily: "var(--mono)", fontWeight: 600 }}>
                    {p.ticker}
                  </td>
                  <td>{num(p.shares)}</td>
                  <td>{fixed(p.avg_price, 2)}</td>
                  <td>{num(p.judgment_linked_count)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Card>

      {loading && !data && (
        <div className="grid-2">
          <Card title="宏观">
            <Skeleton lines={4} />
          </Card>
          <Card title="基本面">
            <Skeleton lines={4} />
          </Card>
        </div>
      )}

      {data && (
        <>
          {/* 摘要条：只给人看的时点，不露系统 ID / 内部术语 */}
          <div
            className="card"
            style={{ padding: "16px 20px", marginBottom: "var(--s4)" }}
          >
            <div
              style={{
                display: "flex",
                flexWrap: "wrap",
                gap: "24px 40px",
                alignItems: "baseline",
              }}
            >
              <div>
                <div className="label-mono" style={{ marginBottom: 4 }}>
                  标的
                </div>
                <div
                  style={{
                    fontFamily: "var(--mono)",
                    fontSize: 22,
                    fontWeight: 600,
                    letterSpacing: "-0.01em",
                  }}
                >
                  {data.symbol}
                </div>
              </div>
              <div>
                <div className="label-mono" style={{ marginBottom: 4 }}>
                  行情日期
                </div>
                <div style={{ fontFamily: "var(--mono)", fontSize: 18, fontWeight: 500 }}>
                  {dateRelative(data.as_of)}
                </div>
              </div>
              <div>
                <div className="label-mono" style={{ marginBottom: 4 }}>
                  叙事扫描
                </div>
                <div style={{ fontFamily: "var(--mono)", fontSize: 18, fontWeight: 500 }}>
                  {narr?.ai_scan?.date
                    ? dateRelative(narr.ai_scan.date)
                    : "尚未扫描"}
                </div>
              </div>
              <div style={{ marginLeft: "auto" }}>
                <div className="label-mono" style={{ marginBottom: 4 }}>
                  执行方案
                </div>
                <div style={{ fontSize: 18, fontWeight: 500 }}>
                  {data.plan ? "已生成" : "未生成"}
                </div>
              </div>
            </div>
          </div>

          {scanPendingHint && (
            <div className="note-warn" style={{ marginBottom: "var(--s4)" }}>
              {scanPendingHint}
            </div>
          )}

          {/* 对齐 操作台.dc.html：左列宏观叠基本面，右列技术面拉高；叙事通栏 */}
          <div className="console-panels">
            <div className="console-panels-left">
              <Card title={<h2>宏观</h2>} aside={<UnitTag>VIX</UnitTag>} flush>
                <NoteBlock note={data.macro?.note ?? null} />
                <LabeledKvTable
                  data={data.macro?.data ?? null}
                  context={`${data.symbol} 操作台·宏观`}
                />
              </Card>

              <Card title={<h2>基本面</h2>} aside={<UnitTag>EPS</UnitTag>} flush>
                <NoteBlock note={data.fundamental?.note ?? null} />
                <LabeledKvTable
                  data={data.fundamental?.data ?? null}
                  context={`${data.symbol} 操作台·基本面`}
                />
              </Card>
            </div>

            <div className="console-panels-right">
              <Card title={<h2>技术面</h2>} aside={<UnitTag>ATR</UnitTag>} flush>
                <NoteBlock note={data.technical?.note ?? null} />
                {data.technical?.data ? (
                  <LabeledKvTable
                    data={data.technical.data}
                    context={`${data.symbol} 操作台·技术面`}
                    columns={2}
                  />
                ) : (
                  <Empty>暂无（需先 fetch_prices）</Empty>
                )}
              </Card>
            </div>
          </div>

          <Card title={<h2>叙事</h2>} className="narrative-wide">
              <NoteBlock note={data.narrative?.note ?? null} />

              <h3>我的信息流所见</h3>
              <p className="muted" style={{ marginBottom: "var(--s2)" }}>
                {narr?.mine?.label ??
                  "经你的信源与筛选（最近5条，优先90天内）"}
              </p>
              <div className="scroll-pane" style={{ marginBottom: "var(--s4)" }}>
                {(narr?.mine?.events?.length ?? 0) === 0 &&
                (narr?.mine?.feed_cards?.length ?? 0) === 0 ? (
                  <Empty>
                    暂无已确认事件或相关卡片——从信息流卡片记入事件。
                  </Empty>
                ) : (
                  <>
                    {(narr?.mine?.events?.length ?? 0) > 0 && (
                      <>
                        <div className="muted" style={{ marginBottom: "var(--s2)" }}>
                          已确认事件
                        </div>
                        <ul className="item-list">
                          {narr!.mine!.events.map((ev, i) => (
                            <li key={ev.id ?? `ev-${i}`} className="item">
                              <div className="muted">
                                {[ev.scope ?? ev.category, ev.event_date]
                                  .filter(Boolean)
                                  .join(" · ") || "—"}
                              </div>
                              <div>
                                <TermRichText
                                  text={ev.fact_text ?? "—"}
                                  context={`${data.symbol} 叙事·我的事件`}
                                />
                              </div>
                              {ev.source_url && (
                                <a href={ev.source_url} target="_blank" rel="noreferrer">
                                  来源 ↗
                                </a>
                              )}
                            </li>
                          ))}
                        </ul>
                      </>
                    )}
                    {(narr?.mine?.feed_cards?.length ?? 0) > 0 && (
                      <>
                        <div
                          className="muted"
                          style={{ margin: "var(--s3) 0 var(--s2)" }}
                        >
                          信息流卡片
                        </div>
                        <ul className="item-list">
                          {narr!.mine!.feed_cards.map((c, i) => (
                            <li key={c.id ?? `card-${i}`} className="item">
                              <div className="muted">
                                {[c.source, dateShort(c.published_at)]
                                  .filter(Boolean)
                                  .join(" · ") || "—"}
                              </div>
                              <div>{c.title ?? "—"}</div>
                              {c.summary && (
                                <p className="muted" style={{ margin: "var(--s1) 0 0" }}>
                                  <TermRichText
                                    text={c.summary}
                                    context={`${data.symbol} 叙事·信息流`}
                                  />
                                </p>
                              )}
                            </li>
                          ))}
                        </ul>
                      </>
                    )}
                  </>
                )}
              </div>

              <div className="card-head" style={{ margin: "16px 0 0", borderTop: "1px solid var(--hairline)" }}>
                <h3 style={{ margin: 0 }}>
                  <span style={{ display: "inline-flex", alignItems: "center", gap: 8 }}>
                    <TypeTag type="ai" />
                    AI 独立扫描
                  </span>
                </h3>
                {narr?.ai_scan?.date && (
                  <span className="chip">
                    扫描于 {dateRelative(narr.ai_scan.date)}
                  </span>
                )}
              </div>
              <div className="card-content" style={{ paddingTop: 12 }}>
              <p className="muted" style={{ marginBottom: "var(--s2)" }}>
                {narr?.ai_scan_label ??
                  "AI 独立检索；论点锚定上次财报以来；近期事件限近30天"}
              </p>
              {!data.search_model_configured && (
                <div className="note-warn">未配置搜索模型（MODEL_SEARCH）</div>
              )}
              <div className="actions" style={{ marginTop: 0 }}>
                <button
                  type="button"
                  disabled={scanBusy || !data.search_model_configured}
                  onClick={() => runScan(false)}
                >
                  {scanBusy
                    ? "扫描中…"
                    : narr?.ai_scan
                      ? "使用今日缓存"
                      : "开始扫描"}
                </button>
                <button
                  type="button"
                  className="secondary"
                  disabled={scanBusy || !data.search_model_configured}
                  onClick={() => runScan(true)}
                >
                  重新扫描
                </button>
              </div>
              {scanBusy && (
                <p className="muted" style={{ marginTop: "var(--s2)" }} aria-live="polite">
                  后台正在扫描…已用 {scanElapsedSec} 秒
                </p>
              )}
              {!scanBusy && scanNotice && (
                <p className="muted" style={{ marginTop: "var(--s2)" }}>
                  {scanNotice}
                </p>
              )}
              <div className="info-ai" style={{ marginTop: "var(--s2)" }}>
                {ai && ai.dominant_narrative !== "暂无新叙事" ? (
                  <>
                    <p style={{ marginBottom: "var(--s3)", color: "var(--ai-text)" }}>
                      {ai.dominant_narrative}
                    </p>

                    <div className="narrative-tabs">
                      <button
                        type="button"
                        className={narrTab === "bull" ? "" : "secondary"}
                        onClick={() => setNarrTab("bull")}
                      >
                        多方
                      </button>
                      <button
                        type="button"
                        className={narrTab === "mid" ? "" : "secondary"}
                        onClick={() => setNarrTab("mid")}
                      >
                        中立·事实
                      </button>
                      <button
                        type="button"
                        className={narrTab === "bear" ? "" : "secondary"}
                        onClick={() => setNarrTab("bear")}
                      >
                        空方
                      </button>
                    </div>

                    <div className="narrative-tri">
                      <div className="narrative-col">
                        <div className="narrative-col-head">
                          多方 <CountPill>{ai.bull_points?.length ?? 0}</CountPill>
                        </div>
                        <div className="narrative-col-scroll">
                          {(ai.bull_points?.length ?? 0) > 0 ? (
                            <PointList points={ai.bull_points} stance="bull" />
                          ) : (
                            <Empty>暂无</Empty>
                          )}
                        </div>
                      </div>
                      <div className="narrative-col">
                        <div className="narrative-col-head">
                          中立·事实 <CountPill>{midItems.length}</CountPill>
                        </div>
                        <div className="narrative-col-scroll">
                          <MidColumnList items={midItems} />
                        </div>
                      </div>
                      <div className="narrative-col">
                        <div className="narrative-col-head">
                          空方 <CountPill>{ai.bear_points?.length ?? 0}</CountPill>
                        </div>
                        <div className="narrative-col-scroll">
                          {(ai.bear_points?.length ?? 0) > 0 ? (
                            <PointList points={ai.bear_points} stance="bear" />
                          ) : (
                            <Empty>暂无</Empty>
                          )}
                        </div>
                      </div>
                    </div>

                    <div className="narrative-tab-pane">
                      {narrTab === "bull" &&
                        ((ai.bull_points?.length ?? 0) > 0 ? (
                          <PointList points={ai.bull_points} stance="bull" />
                        ) : (
                          <Empty>暂无多方论点</Empty>
                        ))}
                      {narrTab === "mid" && <MidColumnList items={midItems} />}
                      {narrTab === "bear" &&
                        ((ai.bear_points?.length ?? 0) > 0 ? (
                          <PointList points={ai.bear_points} stance="bear" />
                        ) : (
                          <Empty>暂无空方论点</Empty>
                        ))}
                    </div>
                  </>
                ) : (
                  <Empty>{narr?.ai_scan ? "暂无新叙事" : "尚未扫描"}</Empty>
                )}
              </div>
              </div>
          </Card>

          <Card title="执行方案（参考）">
            {data.plan?.ladder_api ? (
              <table className="numeric">
                <thead>
                  <tr>
                    <th>档</th>
                    <th>限价</th>
                    <th>距现价</th>
                    <th>金额</th>
                    <th>股数</th>
                    <th>邻近锚点</th>
                  </tr>
                </thead>
                <tbody>
                  {data.plan.ladder_api.map((r) => (
                    <tr key={r.tranche}>
                      <td style={{ textAlign: "left" }}>{r.tranche}</td>
                      <td>{fixed(r.limit_price, 2)}</td>
                      <td>{r.vs_last}</td>
                      <td>{money(r.amount, 0)}</td>
                      <td>{num(r.shares)}</td>
                      <td style={{ textAlign: "left" }}>{r.near_anchors}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            ) : (
              <Empty>方案未生成</Empty>
            )}
            {data.plan?.time_stop && (
              <p className="muted" style={{ marginTop: "var(--s3)" }}>
                {data.plan.time_stop}
              </p>
            )}
            {data.plan?.earnings_note && (
              <p className="muted">财报：{data.plan.earnings_note}</p>
            )}
            <div className="actions">
              <button
                type="button"
                className="secondary"
                onClick={() => {
                  setFillOpen(true);
                  setFillDate(new Date().toISOString().slice(0, 10));
                  setFillJudgment("");
                  setFillNote("");
                }}
              >
                记录成交
              </button>
            </div>
          </Card>

          <div className="grid-2">
            <Card title="我的判断">
              <p className="muted" style={{ marginBottom: "var(--s3)" }}>
                预填对象 {data.symbol} · 类型为行动判断。可证伪表述必填。
                {narr?.ai_scan ? " 提交时会关联本次叙事扫描。" : ""}
              </p>
              <form onSubmit={submitJudgment}>
                <div className="info-judgment" style={{ paddingTop: 4, paddingBottom: 4 }}>
                  <div className="info-row" style={{ marginBottom: 8, alignItems: "center" }}>
                    <TypeTag type="judgment" />
                    <span className="label-mono">个人判断 · append-only</span>
                  </div>
                  <textarea
                    rows={3}
                    value={text}
                    onChange={(e) => setText(e.target.value)}
                    placeholder="如：这是过度反应，两周内修复"
                  />
                </div>
                <div className="actions">
                  <button type="submit" disabled={busy || !text.trim() || !data.plan}>
                    提交判断
                  </button>
                </div>
              </form>
            </Card>

            <Card title="判断记录">
              {chains.length === 0 ? (
                <Empty>暂无判断——加载标的后显示最近 20 条。</Empty>
              ) : (
                <div className="list-scroll short" style={{ padding: "0 20px 16px" }}>
                  <ul className="item-list">
                    {chains.map((c) => {
                      const latest =
                        [...c.entries]
                          .reverse()
                          .find((e) => ["original", "revision"].includes(e.kind)) ||
                        c.entries[0];
                      return (
                        <li key={c.root_id} className="item">
                          <div className="chip-row" style={{ marginBottom: "var(--s2)" }}>
                            <Chip>{c.object}</Chip>
                            <Chip>{latest?.jtype ?? "—"}</Chip>
                          </div>
                          <div style={{ marginBottom: "var(--s1)" }}>{latest?.text}</div>
                          <div className="muted">
                            <span className="num">置信度 {latest?.confidence ?? "—"}</span>
                            {" · "}
                            {latest?.created_at?.slice(0, 16)}
                          </div>
                        </li>
                      );
                    })}
                  </ul>
                </div>
              )}
            </Card>
          </div>

          {data.warnings?.length > 0 && (
            <Card title="提示">
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
      )}

      {fillOpen && data && (
        <Modal
          title="记录成交（事实层）"
          onClose={() => setFillOpen(false)}
          footer={
            <>
              <button type="button" disabled={busy} onClick={submitFill}>
                确认录入
              </button>
              <button
                type="button"
                className="secondary"
                onClick={() => setFillOpen(false)}
              >
                取消
              </button>
            </>
          }
        >
          <p className="muted" style={{ marginBottom: "var(--s3)" }}>
            行不可改；录错请作废补新。无关联判断＝无预注册交易。
          </p>
          <div className="row">
            <div className="field">
              <label htmlFor="side">方向</label>
              <select
                id="side"
                value={fillSide}
                onChange={(e) => setFillSide(e.target.value as "buy" | "sell")}
              >
                <option value="buy">买入</option>
                <option value="sell">卖出</option>
              </select>
            </div>
            <div className="field">
              <label htmlFor="tdate">成交日</label>
              <input
                id="tdate"
                type="date"
                value={fillDate}
                onChange={(e) => setFillDate(e.target.value)}
              />
            </div>
            <div className="field">
              <label htmlFor="shares">股数</label>
              <input
                id="shares"
                value={fillShares}
                onChange={(e) => setFillShares(e.target.value)}
              />
            </div>
            <div className="field">
              <label htmlFor="price">价格</label>
              <input
                id="price"
                value={fillPrice}
                onChange={(e) => setFillPrice(e.target.value)}
              />
            </div>
            <div className="field">
              <label htmlFor="fees">费用</label>
              <input
                id="fees"
                value={fillFees}
                onChange={(e) => setFillFees(e.target.value)}
              />
            </div>
            <div className="field">
              <label htmlFor="jlink">关联判断（可选）</label>
              <select
                id="jlink"
                value={fillJudgment}
                onChange={(e) => setFillJudgment(e.target.value)}
              >
                <option value="">— 不关联 —</option>
                {chains
                  .filter((c) => c.status === "open")
                  .map((c) => {
                    const latest =
                      [...c.entries]
                        .reverse()
                        .find((e) => ["original", "revision"].includes(e.kind)) ||
                      c.entries[0];
                    return (
                      <option key={c.root_id} value={c.root_id}>
                        {(latest?.text || c.root_id).slice(0, 40)}
                      </option>
                    );
                  })}
              </select>
            </div>
          </div>
          <div className="field">
            <label htmlFor="fnote">备注</label>
            <input
              id="fnote"
              value={fillNote}
              onChange={(e) => setFillNote(e.target.value)}
            />
          </div>
          <p className="muted">
            标的 {data.symbol} · {data.plan ? "已关联当前执行方案" : "无执行方案"}
          </p>
        </Modal>
      )}
    </main>
  );
}
