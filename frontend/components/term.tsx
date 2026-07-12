"use client";

/**
 * Slice 7：Term 悬停/展开 + 三态机 + Obsidian 导出。
 * 浮层经 portal 挂到 body，避免被 .card { overflow:hidden } 裁切。
 */

import {
  useCallback,
  useEffect,
  useId,
  useLayoutEffect,
  useRef,
  useState,
  type CSSProperties,
  type ReactNode,
} from "react";
import { createPortal } from "react-dom";
import {
  useGlossaryOptional,
  type GlossaryState,
  type GlossaryTermDetail,
} from "@/components/glossary-provider";
import { Modal } from "@/components/ui";
import { toast } from "@/components/toast";
import { bilingualTitle } from "@/lib/glossary-match";

type TermProps = {
  term: string;
  showMark?: boolean;
  context?: string;
  children?: ReactNode;
  className?: string;
};

type FloatBox = {
  style: CSSProperties;
  maxHeight: number;
};

function placeFloat(
  anchor: DOMRect,
  opts: {
    width: number;
    preferMaxH: number;
    gap?: number;
    prefer?: "auto" | "above" | "below";
  }
): FloatBox {
  const { width, preferMaxH, gap = 8, prefer = "auto" } = opts;
  const vw = window.innerWidth;
  const vh = window.innerHeight;
  const w = Math.min(width, vw - 16);
  let left = anchor.left;
  if (left + w > vw - 8) left = vw - w - 8;
  if (left < 8) left = 8;

  const spaceBelow = vh - anchor.bottom - gap;
  const spaceAbove = anchor.top - gap;
  let placeBelow: boolean;
  if (prefer === "below") placeBelow = true;
  else if (prefer === "above") placeBelow = false;
  else {
    placeBelow =
      spaceBelow >= Math.min(180, preferMaxH) || spaceBelow >= spaceAbove;
  }
  // 若偏好方向空间不够，翻到另一侧
  if (placeBelow && spaceBelow < 100 && spaceAbove > spaceBelow) placeBelow = false;
  if (!placeBelow && spaceAbove < 100 && spaceBelow > spaceAbove) placeBelow = true;

  if (placeBelow) {
    const maxHeight = Math.max(120, Math.min(preferMaxH, spaceBelow));
    return {
      maxHeight,
      style: {
        position: "fixed",
        top: anchor.bottom + gap,
        left,
        width: w,
        maxHeight,
        zIndex: 1000,
      },
    };
  }
  const maxHeight = Math.max(120, Math.min(preferMaxH, spaceAbove));
  return {
    maxHeight,
    style: {
      position: "fixed",
      bottom: vh - anchor.top + gap,
      left,
      width: w,
      maxHeight,
      zIndex: 1000,
    },
  };
}

export function Term({
  term,
  showMark = true,
  context,
  children,
  className,
}: TermProps) {
  const glossary = useGlossaryOptional();
  const summary = glossary?.byTerm.get(term.trim().toLowerCase());
  const state: GlossaryState = (summary?.state as GlossaryState) || "unknown";
  const [open, setOpen] = useState(false);
  const [hover, setHover] = useState(false);
  const [exportOpen, setExportOpen] = useState(false);
  const [userNote, setUserNote] = useState("");
  const [detail, setDetail] = useState<GlossaryTermDetail | null>(null);
  const [busy, setBusy] = useState(false);
  const [panelBox, setPanelBox] = useState<FloatBox | null>(null);
  const [tipBox, setTipBox] = useState<FloatBox | null>(null);
  const [mounted, setMounted] = useState(false);
  const panelId = useId();
  const wrapRef = useRef<HTMLSpanElement>(null);
  const panelRef = useRef<HTMLDivElement>(null);

  useEffect(() => setMounted(true), []);

  const loadDetail = useCallback(async () => {
    if (!glossary) return;
    const d = await glossary.getDetail(term);
    setDetail(d);
  }, [glossary, term]);

  useEffect(() => {
    if ((hover || open) && !detail) void loadDetail();
  }, [hover, open, detail, loadDetail]);

  const reposition = useCallback(() => {
    const el = wrapRef.current;
    if (!el) return;
    const r = el.getBoundingClientRect();
    if (open) {
      setPanelBox(
        placeFloat(r, {
          width: 352,
          preferMaxH: Math.min(vhPrefer(), 420),
          prefer: "auto",
        })
      );
    }
    if (hover && !open) {
      setTipBox(
        placeFloat(r, { width: 280, preferMaxH: 160, prefer: "above" })
      );
    }
  }, [open, hover]);

  useLayoutEffect(() => {
    if (!open && !(hover && !open)) {
      setPanelBox(null);
      if (!hover) setTipBox(null);
      return;
    }
    reposition();
    window.addEventListener("resize", reposition);
    // capture scroll from nested panes
    window.addEventListener("scroll", reposition, true);
    return () => {
      window.removeEventListener("resize", reposition);
      window.removeEventListener("scroll", reposition, true);
    };
  }, [open, hover, reposition]);

  useEffect(() => {
    if (!open) return;
    function onDoc(e: MouseEvent) {
      const t = e.target as Node;
      if (wrapRef.current?.contains(t)) return;
      if (panelRef.current?.contains(t)) return;
      setOpen(false);
    }
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") setOpen(false);
    }
    document.addEventListener("mousedown", onDoc);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDoc);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  if (!glossary || !summary) {
    return <>{children ?? term}</>;
  }

  // known =「我已懂，别再打扰」：全站（操作台字段 + 信息流）均不再悬停/展开
  if (state === "known") {
    return <>{children ?? term}</>;
  }

  const markClass =
    state === "saved"
      ? "term-mark term-mark-saved"
      : "term-mark term-mark-unknown";

  async function onIgnore() {
    setBusy(true);
    try {
      await glossary!.setState(term, "known");
      setOpen(false);
      setHover(false);
      toast.success(`已忽略「${term}」——之后不再弹出解释（设置里可恢复）`);
    } catch (e) {
      toast.error(String((e as Error).message ?? e));
    } finally {
      setBusy(false);
    }
  }

  function openExportDialog() {
    setUserNote("");
    setExportOpen(true);
  }

  async function confirmExport() {
    setBusy(true);
    try {
      await glossary!.exportNote(term, {
        context,
        note: userNote.trim() || undefined,
      });
      setExportOpen(false);
      setOpen(false);
      setUserNote("");
    } catch (e) {
      toast.error(String((e as Error).message ?? e));
    } finally {
      setBusy(false);
    }
  }

  const oneLiner = detail?.one_liner ?? summary.one_liner ?? "";
  const titleInfo = bilingualTitle(
    detail?.term ?? summary.term ?? term,
    detail?.aliases ?? summary.aliases
  );

  const tip =
    mounted && hover && !open && !exportOpen && tipBox
      ? createPortal(
          <span className="term-tooltip term-float" style={tipBox.style} role="tooltip">
            <span className="term-tooltip-title">{titleInfo.display}</span>
            {oneLiner || "加载中…"}
          </span>,
          document.body
        )
      : null;

  const panel =
    mounted && open && !exportOpen && panelBox
      ? createPortal(
          <div
            ref={panelRef}
            id={panelId}
            className="term-panel term-float"
            role="dialog"
            style={panelBox.style}
          >
            <div className="term-panel-title">
              <span className="term-title-primary">{titleInfo.primary}</span>
              {titleInfo.secondary && (
                <span className="term-title-secondary">
                  {" "}
                  · {titleInfo.secondary}
                </span>
              )}
            </div>
            {detail?.category && (
              <div className="muted" style={{ marginBottom: 8, fontSize: 12 }}>
                {detail.category}
              </div>
            )}
            <p className="term-panel-one">{oneLiner}</p>
            {detail?.full_md && (
              <div className="term-panel-full">{detail.full_md}</div>
            )}
            <div className="term-panel-actions">
              <button
                type="button"
                className="secondary"
                disabled={busy}
                onClick={onIgnore}
              >
                忽略
              </button>
              <button
                type="button"
                disabled={busy || !glossary.exportConfigured}
                title={
                  glossary.exportConfigured
                    ? "写入 Obsidian vault（永不覆盖「我的笔记」）"
                    : "未配置 OBSIDIAN_EXPORT_DIR"
                }
                onClick={openExportDialog}
              >
                加入知识笔记
              </button>
            </div>
            {!glossary.exportConfigured && (
              <p className="muted" style={{ marginTop: 8, fontSize: 12 }}>
                未配置 OBSIDIAN_EXPORT_DIR，导出已禁用
              </p>
            )}
          </div>,
          document.body
        )
      : null;

  const exportModal =
    mounted && exportOpen
      ? createPortal(
          <Modal
            title={`加入知识笔记 · ${titleInfo.display}`}
            onClose={() => {
              if (!busy) setExportOpen(false);
            }}
            footer={
              <>
                <button
                  type="button"
                  className="secondary"
                  disabled={busy}
                  onClick={() => setExportOpen(false)}
                >
                  取消
                </button>
                <button type="button" disabled={busy} onClick={confirmExport}>
                  {busy ? "写入中…" : "确认写入"}
                </button>
              </>
            }
          >
            <p className="muted" style={{ marginBottom: "var(--s3)" }}>
              术语定义会写入 Obsidian。你的看法可选填，进入笔记的「我的笔记」区；工具之后不会覆盖该区已有内容。
            </p>
            <label htmlFor={`note-${panelId}`} className="label-mono">
              我的看法（可选）
            </label>
            <textarea
              id={`note-${panelId}`}
              rows={5}
              value={userNote}
              onChange={(e) => setUserNote(e.target.value)}
              placeholder="例如：在操作台看到 VIX 时想到的关联、疑问或自己的理解…"
              style={{ width: "100%", marginTop: 8 }}
              disabled={busy}
            />
          </Modal>,
          document.body
        )
      : null;

  return (
    <span
      ref={wrapRef}
      className={`term-wrap ${className ?? ""}`}
      onMouseEnter={() => setHover(true)}
      onMouseLeave={() => setHover(false)}
    >
      <button
        type="button"
        className={`term-trigger ${showMark ? markClass : ""}`}
        aria-expanded={open}
        aria-controls={panelId}
        onClick={() => setOpen((v) => !v)}
      >
        {children ?? term}
      </button>
      {tip}
      {panel}
      {exportModal}
    </span>
  );
}

function vhPrefer(): number {
  if (typeof window === "undefined") return 360;
  return window.innerHeight * 0.55;
}
