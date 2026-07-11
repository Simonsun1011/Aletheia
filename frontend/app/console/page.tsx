"use client";

import Link from "next/link";
import { FormEvent, ReactNode, useCallback, useEffect, useState } from "react";
import { apiGet, apiPost, apiPostLlm, JudgmentChain } from "@/lib/api";

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
  const [open, setOpen] = useState(false);
  if (!note) return null;
  return (
    <details
      open={open}
      onToggle={(e) => setOpen((e.target as HTMLDetailsElement).open)}
      style={{ marginBottom: "0.75rem" }}
    >
      <summary className="muted" style={{ cursor: "pointer" }}>
        {note.title} {open ? "▾" : "▸"}
      </summary>
      <p className="muted" style={{ fontSize: "0.9rem", lineHeight: 1.5 }}>
        {note.body}
      </p>
    </details>
  );
}

function ScrollPane({ children }: { children: ReactNode }) {
  return <div className="scroll-pane">{children}</div>;
}

export default function ConsolePage() {
  const [symbol, setSymbol] = useState("AMAT");
  const [amount, setAmount] = useState("5000");
  const [windowDays, setWindowDays] = useState("5");
  const [data, setData] = useState<ConsolePayload | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [text, setText] = useState("");
  const [tip, setTip] = useState<string | null>(null);
  const [scanBusy, setScanBusy] = useState(false);
  const [scanElapsedSec, setScanElapsedSec] = useState(0);
  const [scanNotice, setScanNotice] = useState<string | null>(null);
  const [chains, setChains] = useState<JudgmentChain[]>([]);
  const [positions, setPositions] = useState<
    { ticker: string; shares: number; avg_price: number; judgment_linked_count: number }[]
  >([]);
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

  const refreshJudgments = useCallback(async (sym: string) => {
    const list = await apiGet<JudgmentChain[]>(
      `/judgments?object=${encodeURIComponent(sym)}&origin=console`
    );
    setChains(list.slice(0, 20));
  }, []);

  const refreshPositions = useCallback(async () => {
    const list = await apiGet<
      {
        ticker: string;
        shares: number;
        avg_price: number;
        judgment_linked_count: number;
      }[]
    >("/positions");
    setPositions(list);
  }, []);

  async function load(e?: FormEvent) {
    e?.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const body = await apiGet<ConsolePayload>(
        `/console/${encodeURIComponent(symbol.trim())}?amount=${amount}&window=${windowDays}`
      );
      setData(body);
      await refreshJudgments(body.symbol);
      await refreshPositions();
    } catch (err) {
      setError(String((err as Error).message ?? err));
    } finally {
      setBusy(false);
    }
  }

  useEffect(() => {
    if (!scanBusy) return;
    setScanElapsedSec(0);
    const t0 = Date.now();
    const id = window.setInterval(() => {
      setScanElapsedSec(Math.floor((Date.now() - t0) / 1000));
    }, 250);
    return () => window.clearInterval(id);
  }, [scanBusy]);

  async function onHoverTerm(term: string) {
    try {
      const g = await apiGet<{ one_liner: string }>(
        `/glossary/${encodeURIComponent(term)}`
      );
      setTip(`${term}: ${g.one_liner}`);
    } catch {
      setTip(null);
    }
  }

  async function runScan(force: boolean) {
    if (!data) return;
    setScanBusy(true);
    setError(null);
    setScanNotice(null);
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
        `/console/${data.symbol}/narrative-scan?force=${force ? "true" : "false"}`,
        {}
      );
      if (scan.notice) {
        setScanNotice(scan.notice);
      } else {
        const p = scan.payload;
        const empty =
          !!p &&
          !(p.bull_points?.length || p.bear_points?.length || p.recent_events?.length) &&
          (!p.dominant_narrative || p.dominant_narrative === "暂无新叙事");
        if (empty) setScanNotice("暂无新叙事");
      }
      const body = await apiGet<ConsolePayload>(
        `/console/${encodeURIComponent(data.symbol)}?amount=${amount}&window=${windowDays}`
      );
      setData(body);
    } catch (err) {
      const msg = String((err as Error).message ?? err);
      // Soft soft-fail leftovers: never look like a broken system for empty news
      if (
        msg.includes("AI_GUARD") ||
        msg.includes("AI_PARSE") ||
        msg.includes("VALIDATION_ERROR")
      ) {
        setScanNotice("暂无新叙事");
      } else {
        setError(msg);
      }
    } finally {
      setScanBusy(false);
    }
  }

  async function submitJudgment(e: FormEvent) {
    e.preventDefault();
    if (!data?.plan?.id || !text.trim()) return;
    setBusy(true);
    setError(null);
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
      setTip("判断已提交");
      await refreshJudgments(data.symbol);
    } catch (err) {
      setError(String((err as Error).message ?? err));
    } finally {
      setBusy(false);
    }
  }

  const narr = data?.narrative?.data;
  const ai = narr?.ai_scan?.payload;

  return (
    <main>
      <p>
        <Link href="/">← 判断日志</Link>
        {" · "}
        <Link href="/feed">信息流</Link>
        {" · "}
        <Link href="/settings">设置</Link>
      </p>
      <h1>操作台</h1>
      <p className="muted">
        模式B：四板块平铺 + 执行方案。叙事区分「我的信息流」与「AI独立扫描」。
      </p>

      <form onSubmit={load} className="actions" style={{ flexWrap: "wrap" }}>
        <label>
          标的{" "}
          <input
            value={symbol}
            onChange={(e) => setSymbol(e.target.value.toUpperCase())}
          />
        </label>
        <label>
          预算{" "}
          <input value={amount} onChange={(e) => setAmount(e.target.value)} />
        </label>
        <label>
          窗口(日){" "}
          <input
            value={windowDays}
            onChange={(e) => setWindowDays(e.target.value)}
          />
        </label>
        <button type="submit" disabled={busy}>
          加载
        </button>
      </form>

      {error && <p className="error">{error}</p>}
      {tip && <p className="muted">{tip}</p>}

      {data && (
        <>
          <p className="muted">
            {data.symbol} · as_of {data.as_of} · plan {data.plan?.id ?? "—"}
          </p>

          <section>
            <h2>
              宏观{" "}
              <button
                type="button"
                className="secondary"
                onMouseEnter={() => onHoverTerm("VIX")}
              >
                VIX
              </button>
            </h2>
            <NoteBlock note={data.macro?.note ?? null} />
            {data.macro?.data ? (
              <pre style={{ whiteSpace: "pre-wrap" }}>
                {JSON.stringify(data.macro.data, null, 2)}
              </pre>
            ) : (
              <p className="muted">暂无</p>
            )}
          </section>

          <section>
            <h2>
              基本面{" "}
              <button
                type="button"
                className="secondary"
                onMouseEnter={() => onHoverTerm("EPS")}
              >
                EPS
              </button>
            </h2>
            <NoteBlock note={data.fundamental?.note ?? null} />
            {data.fundamental?.data ? (
              <pre style={{ whiteSpace: "pre-wrap" }}>
                {JSON.stringify(data.fundamental.data, null, 2)}
              </pre>
            ) : (
              <p className="muted">暂无</p>
            )}
          </section>

          <section>
            <h2>叙事</h2>
            <NoteBlock note={data.narrative?.note ?? null} />
            <div className="narrative-grid">
              <div className="narrative-col">
                <h3>我的信息流所见</h3>
                <p className="muted narrative-sub">
                  {narr?.mine?.label ??
                    "经你的信源与筛选（最近5条，优先90天内；稀疏时显示更早条目）"}
                </p>
                <ScrollPane>
                  {(narr?.mine?.events?.length ?? 0) === 0 &&
                    (narr?.mine?.feed_cards?.length ?? 0) === 0 && (
                      <p className="muted">暂无已确认事件或相关卡片</p>
                    )}
                  {(narr?.mine?.events?.length ?? 0) > 0 && (
                    <div className="narrative-block">
                      <div className="narrative-block-title">已确认事件</div>
                      <ul className="narrative-list">
                        {narr!.mine!.events.map((ev, i) => (
                          <li key={ev.id ?? `ev-${i}`}>
                            <div className="muted">
                              {[ev.scope ?? ev.category, ev.event_date]
                                .filter(Boolean)
                                .join(" · ") || "—"}
                            </div>
                            <div>{ev.fact_text ?? "—"}</div>
                            {ev.source_url && (
                              <a
                                href={ev.source_url}
                                target="_blank"
                                rel="noreferrer"
                              >
                                来源
                              </a>
                            )}
                          </li>
                        ))}
                      </ul>
                    </div>
                  )}
                  {(narr?.mine?.feed_cards?.length ?? 0) > 0 && (
                    <div className="narrative-block">
                      <div className="narrative-block-title">信息流卡片</div>
                      <ul className="narrative-list">
                        {narr!.mine!.feed_cards.map((c, i) => (
                          <li key={c.id ?? `card-${i}`}>
                            <div className="muted">
                              {[c.source, c.published_at?.slice(0, 10)]
                                .filter(Boolean)
                                .join(" · ") || "—"}
                            </div>
                            <div>{c.title ?? "—"}</div>
                            {c.summary && (
                              <p className="muted" style={{ margin: "0.25rem 0 0" }}>
                                {c.summary}
                              </p>
                            )}
                          </li>
                        ))}
                      </ul>
                    </div>
                  )}
                </ScrollPane>
              </div>

              <div className="narrative-col">
                <h3>AI独立扫描</h3>
                <p className="muted narrative-sub">
                  {narr?.ai_scan_label ??
                    "AI独立检索；主导叙事/论点锚定上次财报以来；近期事件限近30天"}
                  {narr?.ai_scan?.date ? ` · 缓存日 ${narr.ai_scan.date}` : ""}
                </p>
                {!data.search_model_configured && (
                  <p className="error">未配置搜索模型（MODEL_SEARCH）</p>
                )}
                <div className="actions">
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
                  <p className="muted" style={{ marginTop: "0.5rem" }} aria-live="polite">
                    后台正在扫描…已用 {scanElapsedSec} 秒
                  </p>
                )}
                {error && (
                  <p className="error" style={{ marginTop: "0.5rem" }}>
                    {error}
                  </p>
                )}
                {!error && !scanBusy && scanNotice && (
                  <p className="muted" style={{ marginTop: "0.5rem" }}>
                    {scanNotice}
                  </p>
                )}
                <ScrollPane>
                  {ai && ai.dominant_narrative !== "暂无新叙事" ? (
                    <>
                      <p className="narrative-dominant">
                        {ai.dominant_narrative}
                      </p>
                      {(ai.bull_points?.length ?? 0) > 0 && (
                        <div className="narrative-block">
                          <div className="narrative-block-title">多方论点</div>
                          <ul className="narrative-list">
                            {ai.bull_points.map((p) => (
                              <li key={p.source_url + p.point}>
                                <div className="muted">
                                  {p.date ?? "—"} · [{p.attributed_to}]
                                </div>
                                <div>
                                  {p.point}{" "}
                                  <a
                                    href={p.source_url}
                                    target="_blank"
                                    rel="noreferrer"
                                  >
                                    来源
                                  </a>
                                </div>
                              </li>
                            ))}
                          </ul>
                        </div>
                      )}
                      {(ai.bear_points?.length ?? 0) > 0 && (
                        <div className="narrative-block">
                          <div className="narrative-block-title">空方论点</div>
                          <ul className="narrative-list">
                            {ai.bear_points.map((p) => (
                              <li key={p.source_url + p.point}>
                                <div className="muted">
                                  {p.date ?? "—"} · [{p.attributed_to}]
                                </div>
                                <div>
                                  {p.point}{" "}
                                  <a
                                    href={p.source_url}
                                    target="_blank"
                                    rel="noreferrer"
                                  >
                                    来源
                                  </a>
                                </div>
                              </li>
                            ))}
                          </ul>
                        </div>
                      )}
                      {(ai.recent_events?.length ?? 0) > 0 && (
                        <div className="narrative-block">
                          <div className="narrative-block-title">近期事件</div>
                          <ul className="narrative-list">
                            {ai.recent_events!.map((e, i) => (
                              <li key={(e.source_url || "") + i}>
                                <div className="muted">{e.date || "—"}</div>
                                <div>{e.fact}</div>
                                {e.source_url && (
                                  <a
                                    href={e.source_url}
                                    target="_blank"
                                    rel="noreferrer"
                                  >
                                    来源
                                  </a>
                                )}
                              </li>
                            ))}
                          </ul>
                        </div>
                      )}
                    </>
                  ) : (
                    <p className="muted">
                      {narr?.ai_scan ? "暂无新叙事" : "尚未扫描"}
                    </p>
                  )}
                </ScrollPane>
              </div>
            </div>
          </section>

          <section>
            <h2>
              技术面{" "}
              <button
                type="button"
                className="secondary"
                onMouseEnter={() => onHoverTerm("ATR")}
              >
                ATR
              </button>
            </h2>
            <NoteBlock note={data.technical?.note ?? null} />
            {data.technical?.data ? (
              <pre style={{ whiteSpace: "pre-wrap" }}>
                {JSON.stringify(data.technical.data, null, 2)}
              </pre>
            ) : (
              <p className="muted">暂无（需先 fetch_prices）</p>
            )}
          </section>

          <section>
            <h2>执行方案（参考）</h2>
            {data.plan?.ladder_api ? (
              <table>
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
                      <td>{r.tranche}</td>
                      <td>{r.limit_price}</td>
                      <td>{r.vs_last}</td>
                      <td>{r.amount}</td>
                      <td>{r.shares}</td>
                      <td>{r.near_anchors}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            ) : (
              <p className="muted">方案未生成</p>
            )}
            <p className="muted">{data.plan?.time_stop}</p>
            <p className="muted">财报：{data.plan?.earnings_note}</p>
            <div className="actions">
              <button
                type="button"
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
            {fillOpen && (
              <div className="fill-modal">
                <h3 style={{ fontSize: "1rem", marginTop: "0.75rem" }}>
                  记录成交（事实层）
                </h3>
                <p className="muted">
                  行不可改；录错请作废补新。无关联判断=无预注册交易。
                </p>
                <div className="fill-grid">
                  <label>
                    方向
                    <select
                      value={fillSide}
                      onChange={(e) =>
                        setFillSide(e.target.value as "buy" | "sell")
                      }
                    >
                      <option value="buy">买入</option>
                      <option value="sell">卖出</option>
                    </select>
                  </label>
                  <label>
                    成交日
                    <input
                      type="date"
                      value={fillDate}
                      onChange={(e) => setFillDate(e.target.value)}
                    />
                  </label>
                  <label>
                    股数
                    <input
                      value={fillShares}
                      onChange={(e) => setFillShares(e.target.value)}
                    />
                  </label>
                  <label>
                    价格
                    <input
                      value={fillPrice}
                      onChange={(e) => setFillPrice(e.target.value)}
                    />
                  </label>
                  <label>
                    费用
                    <input
                      value={fillFees}
                      onChange={(e) => setFillFees(e.target.value)}
                    />
                  </label>
                  <label>
                    关联判断（可选）
                    <select
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
                              .find((e) =>
                                ["original", "revision"].includes(e.kind)
                              ) || c.entries[0];
                          return (
                            <option key={c.root_id} value={c.root_id}>
                              {(latest?.text || c.root_id).slice(0, 40)}
                            </option>
                          );
                        })}
                    </select>
                  </label>
                </div>
                <label>
                  备注
                  <input
                    value={fillNote}
                    onChange={(e) => setFillNote(e.target.value)}
                  />
                </label>
                <p className="muted">
                  plan_id={data.plan?.id ?? "—"} · ticker={data.symbol}
                </p>
                <div className="actions">
                  <button
                    type="button"
                    disabled={busy}
                    onClick={async () => {
                      if (!data.symbol) return;
                      setBusy(true);
                      setError(null);
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
                        setTip("成交已记录");
                        await refreshPositions();
                      } catch (err) {
                        setError(String((err as Error).message ?? err));
                      } finally {
                        setBusy(false);
                      }
                    }}
                  >
                    确认录入
                  </button>
                  <button
                    type="button"
                    className="secondary"
                    onClick={() => setFillOpen(false)}
                  >
                    取消
                  </button>
                </div>
              </div>
            )}
          </section>

          <section>
            <h2>持仓</h2>
            <p className="muted">按未作废成交聚合（股数加权买入均价）。</p>
            {positions.length === 0 ? (
              <p className="muted">暂无持仓</p>
            ) : (
              <table>
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
                    <tr key={p.ticker}>
                      <td>{p.ticker}</td>
                      <td>{p.shares}</td>
                      <td>{p.avg_price}</td>
                      <td>{p.judgment_linked_count}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </section>

          <section>
            <h2>我的判断</h2>
            <p className="muted">
              预填 object={data.symbol} / jtype=action。可证伪表述必填。
              {narr?.ai_scan?.id
                ? ` 将关联 scan_id=${narr.ai_scan.id}`
                : ""}
            </p>
            <form onSubmit={submitJudgment}>
              <textarea
                rows={3}
                value={text}
                onChange={(e) => setText(e.target.value)}
                placeholder="如：这是过度反应，两周内修复"
                style={{ width: "100%" }}
              />
              <div className="actions">
                <button
                  type="submit"
                  disabled={busy || !text.trim() || !data.plan}
                >
                  提交判断
                </button>
              </div>
            </form>
          </section>

          <section>
            <h2>判断记录</h2>
            <div
              style={{
                display: "flex",
                gap: "0.75rem",
                overflowX: "auto",
                paddingBottom: "0.5rem",
              }}
            >
              {chains.map((c) => {
                const latest =
                  [...c.entries].reverse().find((e) =>
                    ["original", "revision"].includes(e.kind)
                  ) || c.entries[0];
                return (
                  <div
                    key={c.root_id}
                    style={{
                      minWidth: "220px",
                      border: "1px solid #ccc",
                      padding: "0.75rem",
                      flexShrink: 0,
                    }}
                  >
                    <div className="muted">
                      {c.object} · {latest?.jtype ?? "—"}
                    </div>
                    <div>{latest?.text}</div>
                    <div className="muted">
                      置信度 {latest?.confidence ?? "—"} ·{" "}
                      {latest?.created_at?.slice(0, 16)}
                    </div>
                  </div>
                );
              })}
              {chains.length === 0 && (
                <p className="muted">暂无判断（加载标的后显示最近20条）</p>
              )}
            </div>
          </section>

          {data.warnings?.length > 0 && (
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
