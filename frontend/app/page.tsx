"use client";

import { FormEvent, useCallback, useEffect, useMemo, useState } from "react";
import {
  apiGet,
  apiPost,
  JudgmentChain,
  QuickNote,
} from "@/lib/api";

type JType = "fact" | "market_reaction" | "causal" | "action";

const SCORED: JType[] = ["market_reaction", "action"];

const emptyJudgment = {
  object: "",
  jtype: "action" as JType,
  direction: "outperform",
  horizon_days: "40",
  confidence: "0.6",
  text: "",
  supporting: "",
  counter: "",
  falsification: "",
};

export default function HomePage() {
  const [chains, setChains] = useState<JudgmentChain[]>([]);
  const [notes, setNotes] = useState<QuickNote[]>([]);
  const [form, setForm] = useState(emptyJudgment);
  const [noteText, setNoteText] = useState("");
  const [noteObject, setNoteObject] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [appendFor, setAppendFor] = useState<string | null>(null);
  const [appendKind, setAppendKind] = useState<"amendment" | "retraction" | "review">(
    "amendment"
  );
  const [appendText, setAppendText] = useState("");

  const scored = useMemo(() => SCORED.includes(form.jtype), [form.jtype]);

  const refresh = useCallback(async () => {
    const [c, n] = await Promise.all([
      apiGet<JudgmentChain[]>("/judgments"),
      apiGet<QuickNote[]>("/notes?limit=50"),
    ]);
    setChains(c);
    setNotes(n);
  }, []);

  useEffect(() => {
    refresh().catch((e) => setError(String(e.message ?? e)));
  }, [refresh]);

  async function onSubmitJudgment(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      const body: Record<string, unknown> = {
        object: form.object.trim(),
        jtype: form.jtype,
        text: form.text.trim(),
      };
      if (form.supporting.trim()) body.supporting = form.supporting.trim();
      if (form.counter.trim()) body.counter = form.counter.trim();
      if (form.falsification.trim()) body.falsification = form.falsification.trim();
      if (scored) {
        body.direction = form.direction;
        body.horizon_days = Number(form.horizon_days);
        body.confidence = Number(form.confidence);
      }
      await apiPost("/judgments", body);
      setForm({ ...emptyJudgment, jtype: form.jtype });
      await refresh();
    } catch (err) {
      setError(String((err as Error).message ?? err));
    } finally {
      setBusy(false);
    }
  }

  async function onSubmitNote(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      const body: Record<string, unknown> = { text: noteText.trim() };
      if (noteObject.trim()) body.object = noteObject.trim();
      await apiPost("/notes", body);
      setNoteText("");
      await refresh();
    } catch (err) {
      setError(String((err as Error).message ?? err));
    } finally {
      setBusy(false);
    }
  }

  async function onAppend(rootId: string) {
    setError(null);
    setBusy(true);
    try {
      await apiPost(`/judgments/${rootId}/entries`, {
        kind: appendKind,
        text: appendText.trim(),
      });
      setAppendFor(null);
      setAppendText("");
      await refresh();
    } catch (err) {
      setError(String((err as Error).message ?? err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <main>
      <h1>Aletheia · 判断日志</h1>
      <p className="muted">
        Slice 1：录入 → 校验 → JSONL+SQLite → 列表。{" "}
        <a href="/stocks/AMAT">AMAT 快照 →</a>
        {" · "}
        <a href="/feed">信息流简报 →</a>
        {" · "}
        <a href="/console">操作台 →</a>
        {" · "}
        <a href="/settings">设置 →</a>
      </p>

      {error && <p className="error">{error}</p>}

      <section>
        <h2>录入判断</h2>
        <form onSubmit={onSubmitJudgment}>
          <div className="row">
            <div>
              <label htmlFor="object">对象</label>
              <input
                id="object"
                required
                value={form.object}
                onChange={(e) => setForm({ ...form, object: e.target.value })}
                placeholder="AMAT / AI-infra / MARKET"
              />
            </div>
            <div>
              <label htmlFor="jtype">判断类型</label>
              <select
                id="jtype"
                value={form.jtype}
                onChange={(e) =>
                  setForm({ ...form, jtype: e.target.value as JType })
                }
              >
                <option value="fact">fact 事实</option>
                <option value="market_reaction">market_reaction 市场反应</option>
                <option value="causal">causal 因果</option>
                <option value="action">action 投资动作</option>
              </select>
            </div>
          </div>

          {scored && (
            <div className="row-3">
              <div>
                <label htmlFor="direction">方向</label>
                <select
                  id="direction"
                  required
                  value={form.direction}
                  onChange={(e) =>
                    setForm({ ...form, direction: e.target.value })
                  }
                >
                  <option value="up">up</option>
                  <option value="down">down</option>
                  <option value="outperform">outperform</option>
                  <option value="underperform">underperform</option>
                  <option value="neutral">neutral</option>
                </select>
              </div>
              <div>
                <label htmlFor="horizon">考核期（交易日）</label>
                <input
                  id="horizon"
                  type="number"
                  required
                  min={5}
                  max={120}
                  value={form.horizon_days}
                  onChange={(e) =>
                    setForm({ ...form, horizon_days: e.target.value })
                  }
                />
              </div>
              <div>
                <label htmlFor="confidence">置信度 0–1</label>
                <input
                  id="confidence"
                  type="number"
                  required
                  min={0}
                  max={1}
                  step={0.05}
                  value={form.confidence}
                  onChange={(e) =>
                    setForm({ ...form, confidence: e.target.value })
                  }
                />
              </div>
            </div>
          )}

          <label htmlFor="text">原话（永不改写）</label>
          <textarea
            id="text"
            required
            value={form.text}
            onChange={(e) => setForm({ ...form, text: e.target.value })}
          />

          <label htmlFor="supporting">支持证据（可选）</label>
          <textarea
            id="supporting"
            value={form.supporting}
            onChange={(e) => setForm({ ...form, supporting: e.target.value })}
          />

          <label htmlFor="counter">反方证据（可选）</label>
          <textarea
            id="counter"
            value={form.counter}
            onChange={(e) => setForm({ ...form, counter: e.target.value })}
          />

          <label htmlFor="falsification">证伪条件（可选）</label>
          <textarea
            id="falsification"
            value={form.falsification}
            onChange={(e) =>
              setForm({ ...form, falsification: e.target.value })
            }
          />

          <button type="submit" disabled={busy}>
            提交判断
          </button>
        </form>
      </section>

      <section>
        <h2>随感</h2>
        <form onSubmit={onSubmitNote}>
          <div className="row">
            <div>
              <label htmlFor="note-object">对象（可选）</label>
              <input
                id="note-object"
                value={noteObject}
                onChange={(e) => setNoteObject(e.target.value)}
              />
            </div>
          </div>
          <label htmlFor="note-text">一两句</label>
          <textarea
            id="note-text"
            required
            value={noteText}
            onChange={(e) => setNoteText(e.target.value)}
          />
          <button type="submit" disabled={busy}>
            记下随感
          </button>
        </form>
        {notes.map((n) => (
          <div key={n.id} className="note-item">
            <span className="muted">
              {n.created_at}
              {n.object ? ` · ${n.object}` : ""}
            </span>
            <div>{n.text}</div>
          </div>
        ))}
      </section>

      <section>
        <h2>判断链</h2>
        {chains.length === 0 && <p className="muted">暂无判断</p>}
        {chains.map((chain) => (
          <div key={chain.root_id} className="chain">
            <div className="chain-meta">
              {chain.object} · {chain.status}
              {chain.entries[0]?.jtype ? ` · ${chain.entries[0].jtype}` : ""}
              {chain.entries[0]?.expires_on
                ? ` · 到期 ${chain.entries[0].expires_on}`
                : ""}
            </div>
            {chain.entries.map((entry) => (
              <div
                key={entry.id}
                className={
                  entry.kind === "original" ? "entry" : "entry child"
                }
              >
                <div className="entry-kind">{entry.kind}</div>
                <div>{entry.text}</div>
                <div className="muted">{entry.created_at}</div>
              </div>
            ))}
            {chain.status === "open" && (
              <div className="actions">
                <button
                  type="button"
                  className="secondary"
                  onClick={() => {
                    setAppendFor(chain.root_id);
                    setAppendKind("amendment");
                    setAppendText("");
                  }}
                >
                  追加修正
                </button>
                <button
                  type="button"
                  className="secondary"
                  onClick={() => {
                    setAppendFor(chain.root_id);
                    setAppendKind("retraction");
                    setAppendText("");
                  }}
                >
                  撤回
                </button>
                <button
                  type="button"
                  className="secondary"
                  onClick={() => {
                    setAppendFor(chain.root_id);
                    setAppendKind("review");
                    setAppendText("");
                  }}
                >
                  复盘关闭
                </button>
              </div>
            )}
            {appendFor === chain.root_id && (
              <div className="append-box">
                <label>追加（{appendKind}）</label>
                <textarea
                  value={appendText}
                  onChange={(e) => setAppendText(e.target.value)}
                  required
                />
                <div className="actions">
                  <button
                    type="button"
                    disabled={busy || !appendText.trim()}
                    onClick={() => onAppend(chain.root_id)}
                  >
                    确认追加
                  </button>
                  <button
                    type="button"
                    className="secondary"
                    onClick={() => setAppendFor(null)}
                  >
                    取消
                  </button>
                </div>
              </div>
            )}
          </div>
        ))}
      </section>
    </main>
  );
}
