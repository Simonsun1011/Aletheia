"use client";

import { FormEvent, useCallback, useEffect, useMemo, useState } from "react";
import { apiGet, apiPost, JudgmentChain, QuickNote } from "@/lib/api";
import { TopNav, Card, Chip, Empty, Skeleton, Modal } from "@/components/ui";
import { TickerCombobox } from "@/components/ticker-combobox";
import { TypeTag } from "@/components/info";
import { toast } from "@/components/toast";
import { dateRelative } from "@/lib/format";

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

type AppendKind = "amendment" | "retraction" | "review";
const KIND_LABEL: Record<AppendKind, string> = {
  amendment: "追加修正",
  retraction: "撤回",
  review: "复盘关闭",
};

export default function HomePage() {
  const [chains, setChains] = useState<JudgmentChain[]>([]);
  const [notes, setNotes] = useState<QuickNote[]>([]);
  const [loading, setLoading] = useState(true);
  const [form, setForm] = useState(emptyJudgment);
  const [noteText, setNoteText] = useState("");
  const [noteObject, setNoteObject] = useState("");
  const [busy, setBusy] = useState(false);
  const [appendFor, setAppendFor] = useState<string | null>(null);
  const [appendKind, setAppendKind] = useState<AppendKind>("amendment");
  const [appendText, setAppendText] = useState("");

  const scored = useMemo(() => SCORED.includes(form.jtype), [form.jtype]);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const [c, n] = await Promise.all([
        apiGet<JudgmentChain[]>("/judgments"),
        apiGet<QuickNote[]>("/notes?limit=50"),
      ]);
      setChains(c);
      setNotes(n);
    } catch (e) {
      toast.error(String((e as Error).message ?? e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  async function onSubmitJudgment(e: FormEvent) {
    e.preventDefault();
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
      toast.success("判断已记录");
      await refresh();
    } catch (err) {
      toast.error(String((err as Error).message ?? err));
    } finally {
      setBusy(false);
    }
  }

  async function onSubmitNote(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    try {
      const body: Record<string, unknown> = { text: noteText.trim() };
      if (noteObject.trim()) body.object = noteObject.trim();
      await apiPost("/notes", body);
      setNoteText("");
      toast.success("随感已记下");
      await refresh();
    } catch (err) {
      toast.error(String((err as Error).message ?? err));
    } finally {
      setBusy(false);
    }
  }

  async function onAppend(rootId: string) {
    setBusy(true);
    try {
      await apiPost(`/judgments/${rootId}/entries`, {
        kind: appendKind,
        text: appendText.trim(),
      });
      setAppendFor(null);
      setAppendText("");
      toast.success(`已${KIND_LABEL[appendKind]}`);
      await refresh();
    } catch (err) {
      toast.error(String((err as Error).message ?? err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <main>
      <TopNav />
      <h1>判断日志</h1>
      <p className="page-intro">
        录入 → 校验 → JSONL + SQLite → 追加式链条。原话永不改写，只能追加修正 / 撤回 / 复盘。
      </p>

      <Card title="录入判断">
        <form onSubmit={onSubmitJudgment}>
          <div className="row">
            <div className="field">
              <label htmlFor="object">对象</label>
              <TickerCombobox
                id="object"
                required
                value={form.object}
                onChange={(object) => setForm({ ...form, object })}
                placeholder="AMAT / AI-infra / MARKET"
              />
            </div>
            <div className="field">
              <label htmlFor="jtype">判断类型</label>
              <select
                id="jtype"
                value={form.jtype}
                onChange={(e) => setForm({ ...form, jtype: e.target.value as JType })}
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
              <div className="field">
                <label htmlFor="direction">方向</label>
                <select
                  id="direction"
                  required
                  value={form.direction}
                  onChange={(e) => setForm({ ...form, direction: e.target.value })}
                >
                  <option value="up">up</option>
                  <option value="down">down</option>
                  <option value="outperform">outperform</option>
                  <option value="underperform">underperform</option>
                  <option value="neutral">neutral</option>
                </select>
              </div>
              <div className="field">
                <label htmlFor="horizon">考核期（交易日）</label>
                <input
                  id="horizon"
                  type="number"
                  required
                  min={5}
                  max={120}
                  value={form.horizon_days}
                  onChange={(e) => setForm({ ...form, horizon_days: e.target.value })}
                />
              </div>
              <div className="field">
                <label htmlFor="confidence">置信度 0–1</label>
                <input
                  id="confidence"
                  type="number"
                  required
                  min={0}
                  max={1}
                  step={0.05}
                  value={form.confidence}
                  onChange={(e) => setForm({ ...form, confidence: e.target.value })}
                />
              </div>
            </div>
          )}

          <div className="field">
            <label htmlFor="text">原话（永不改写）</label>
            <textarea
              id="text"
              required
              value={form.text}
              onChange={(e) => setForm({ ...form, text: e.target.value })}
            />
          </div>
          <div className="field">
            <label htmlFor="supporting">支持证据（可选）</label>
            <textarea
              id="supporting"
              value={form.supporting}
              onChange={(e) => setForm({ ...form, supporting: e.target.value })}
            />
          </div>
          <div className="field">
            <label htmlFor="counter">反方证据（可选）</label>
            <textarea
              id="counter"
              value={form.counter}
              onChange={(e) => setForm({ ...form, counter: e.target.value })}
            />
          </div>
          <div className="field">
            <label htmlFor="falsification">证伪条件（可选）</label>
            <textarea
              id="falsification"
              value={form.falsification}
              onChange={(e) => setForm({ ...form, falsification: e.target.value })}
            />
          </div>

          <div className="actions">
            <button type="submit" disabled={busy}>
              提交判断
            </button>
          </div>
        </form>
      </Card>

      <Card title="随感">
        <form onSubmit={onSubmitNote}>
          <div className="field">
            <label htmlFor="note-object">对象（可选）</label>
            <TickerCombobox
              id="note-object"
              value={noteObject}
              onChange={setNoteObject}
              placeholder="可选 · AMAT / 主题"
            />
          </div>
          <div className="field">
            <label htmlFor="note-text">一两句</label>
            <textarea
              id="note-text"
              required
              value={noteText}
              onChange={(e) => setNoteText(e.target.value)}
            />
          </div>
          <div className="actions">
            <button type="submit" className="secondary" disabled={busy}>
              记下随感
            </button>
          </div>
        </form>
        {loading ? (
          <div style={{ marginTop: "var(--s4)" }}>
            <Skeleton lines={2} />
          </div>
        ) : notes.length === 0 ? (
          <div style={{ marginTop: "var(--s4)" }}>
            <Empty>暂无随感——记下一两句转瞬即逝的想法。</Empty>
          </div>
        ) : (
          <div style={{ marginTop: "var(--s3)" }}>
            <div className="list-count">
              <span>共 {notes.length} 条</span>
            </div>
            <div className="list-scroll short">
              <ul className="item-list">
                {notes.map((n) => (
                  <li key={n.id} className="item">
                    <div className="muted">
                      {dateRelative(n.created_at)}
                      {n.object ? ` · ${n.object}` : ""}
                    </div>
                    <div>{n.text}</div>
                  </li>
                ))}
              </ul>
            </div>
          </div>
        )}
      </Card>

      <Card title="判断链" flush>
        {loading ? (
          <Skeleton lines={4} />
        ) : chains.length === 0 ? (
          <Empty>暂无判断——在上方录入你的第一条判断。</Empty>
        ) : (
          <>
            <div className="list-count">
              <span>共 {chains.length} 条链</span>
            </div>
            <div className="list-scroll tall">
              {chains.map((chain) => (
                <div key={chain.root_id} className="chain">
                  <div className="chain-meta">
                    <strong style={{ color: "var(--ink)", fontWeight: 600 }}>
                      {chain.object}
                    </strong>
                    <Chip>{chain.status === "open" ? "进行中" : "已关闭"}</Chip>
                    {chain.entries[0]?.jtype && (
                      <Chip mono>{chain.entries[0].jtype}</Chip>
                    )}
                    {chain.entries[0]?.expires_on && (
                      <span className="badge-due">
                        到期 {dateRelative(chain.entries[0].expires_on)}
                      </span>
                    )}
                  </div>
                  <div className="chain-body info-judgment">
                    {chain.entries.map((entry) => (
                      <div
                        key={entry.id}
                        className={
                          entry.kind === "original" ? "entry" : "entry child"
                        }
                      >
                        {entry.kind === "original" ? (
                          <div
                            className="info-row"
                            style={{ marginBottom: 8, alignItems: "center" }}
                          >
                            <TypeTag type="judgment" />
                            <span className="entry-kind" style={{ margin: 0 }}>
                              ORIGINAL · 原话逐字保留
                            </span>
                          </div>
                        ) : (
                          <div className="entry-kind">{entry.kind}</div>
                        )}
                        <div className="entry-body">{entry.text}</div>
                        <div className="muted" style={{ marginTop: 6 }}>
                          {dateRelative(entry.created_at)}
                        </div>
                      </div>
                    ))}
                    {chain.status === "open" && (
                      <div className="actions" style={{ marginTop: 16 }}>
                        {(Object.keys(KIND_LABEL) as AppendKind[]).map((k) => (
                          <button
                            key={k}
                            type="button"
                            className={
                              k === "retraction"
                                ? "danger btn-small"
                                : k === "amendment"
                                  ? "ghost btn-small"
                                  : "secondary btn-small"
                            }
                            style={
                              k === "amendment"
                                ? { color: "var(--judge-fg)" }
                                : undefined
                            }
                            onClick={() => {
                              setAppendFor(chain.root_id);
                              setAppendKind(k);
                              setAppendText("");
                            }}
                          >
                            {KIND_LABEL[k]}
                          </button>
                        ))}
                      </div>
                    )}
                  </div>
                </div>
              ))}
            </div>
          </>
        )}
      </Card>

      {appendFor && (
        <Modal
          title={KIND_LABEL[appendKind]}
          onClose={() => setAppendFor(null)}
          footer={
            <>
              <button
                type="button"
                disabled={busy || !appendText.trim()}
                onClick={() => onAppend(appendFor)}
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
            </>
          }
        >
          <p className="muted" style={{ marginBottom: "var(--s2)" }}>
            追加为链条的新条目（{appendKind}），原文不会被改动。
          </p>
          <textarea
            rows={4}
            value={appendText}
            onChange={(e) => setAppendText(e.target.value)}
            autoFocus
          />
        </Modal>
      )}
    </main>
  );
}
