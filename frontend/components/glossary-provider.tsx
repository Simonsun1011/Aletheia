"use client";

/**
 * Slice 7：术语词典上下文 — 一次拉取，全站 Term 共享状态机。
 * term-matching：预编译匹配器 + 别名→canonical。
 */

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import { apiGet, apiPatch, apiPost } from "@/lib/api";
import { toast } from "@/components/toast";
import {
  buildMatcher,
  matchAt,
  type CompiledMatcher,
  type MatchHit,
} from "@/lib/glossary-match";

export type GlossaryState = "unknown" | "known" | "saved";

export type GlossaryTermSummary = {
  term: string;
  one_liner?: string | null;
  state: GlossaryState;
  category?: string;
  aliases?: string[];
};

export type GlossaryTermDetail = GlossaryTermSummary & {
  full_md?: string | null;
  sources?: unknown;
  version?: number;
};

type GlossaryContextValue = {
  ready: boolean;
  exportConfigured: boolean;
  terms: GlossaryTermSummary[];
  /** casefold → summary（含别名键指向同一 summary） */
  byTerm: Map<string, GlossaryTermSummary>;
  /** @deprecated 用 matchAt；保留兼容旧调用 */
  matchTerms: string[];
  matcher: CompiledMatcher;
  matchAt: (text: string, pos: number) => MatchHit | null;
  refresh: () => Promise<void>;
  getDetail: (term: string) => Promise<GlossaryTermDetail | null>;
  setState: (term: string, state: GlossaryState) => Promise<void>;
  exportNote: (
    term: string,
    opts?: { context?: string; note?: string }
  ) => Promise<void>;
  resetKnown: () => Promise<void>;
};

const GlossaryContext = createContext<GlossaryContextValue | null>(null);

function norm(t: string) {
  return t.trim().toLowerCase();
}

export function GlossaryProvider({ children }: { children: ReactNode }) {
  const [ready, setReady] = useState(false);
  const [exportConfigured, setExportConfigured] = useState(false);
  const [terms, setTerms] = useState<GlossaryTermSummary[]>([]);

  const refresh = useCallback(async () => {
    try {
      const body = await apiGet<{
        terms: GlossaryTermSummary[];
        export_configured: boolean;
      }>("/glossary");
      setTerms(body.terms ?? []);
      setExportConfigured(!!body.export_configured);
    } catch (e) {
      console.warn("[glossary] load failed", e);
    } finally {
      setReady(true);
    }
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  const byTerm = useMemo(() => {
    const m = new Map<string, GlossaryTermSummary>();
    for (const t of terms) {
      m.set(norm(t.term), t);
      for (const a of t.aliases ?? []) {
        const k = norm(a);
        if (k && !m.has(k)) m.set(k, t);
      }
    }
    return m;
  }, [terms]);

  const matcher = useMemo(() => buildMatcher(terms), [terms]);

  const matchTerms = useMemo(() => {
    return [...terms]
      .map((t) => t.term)
      .sort((a, b) => b.length - a.length);
  }, [terms]);

  const matchAtPos = useCallback(
    (text: string, pos: number) => matchAt(matcher, text, pos),
    [matcher]
  );

  const getDetail = useCallback(async (term: string) => {
    try {
      return await apiGet<GlossaryTermDetail>(
        `/glossary/${encodeURIComponent(term)}`
      );
    } catch {
      return null;
    }
  }, []);

  const setState = useCallback(
    async (term: string, state: GlossaryState) => {
      const row = await apiPatch<GlossaryTermDetail>(
        `/glossary/${encodeURIComponent(term)}`,
        { state }
      );
      setTerms((prev) =>
        prev.map((t) =>
          norm(t.term) === norm(row.term)
            ? {
                ...t,
                state: row.state as GlossaryState,
                aliases: row.aliases ?? t.aliases,
              }
            : t
        )
      );
    },
    []
  );

  const exportNote = useCallback(
    async (term: string, opts?: { context?: string; note?: string }) => {
      if (!exportConfigured) {
        toast.error("未配置 OBSIDIAN_EXPORT_DIR，无法导出");
        return;
      }
      const result = await apiPost<{ term: string; path: string; state: string }>(
        `/glossary/${encodeURIComponent(term)}/export`,
        {
          context: opts?.context ?? null,
          note: opts?.note?.trim() ? opts.note.trim() : null,
        }
      );
      setTerms((prev) =>
        prev.map((t) =>
          norm(t.term) === norm(result.term)
            ? { ...t, state: "saved" as GlossaryState }
            : t
        )
      );
      toast.success(`已写入知识笔记：${result.term}`);
    },
    [exportConfigured]
  );

  const resetKnown = useCallback(async () => {
    await apiPost<{ reset: number }>("/glossary/reset-known", {});
    await refresh();
    toast.success("已重置「忽略」术语标记");
  }, [refresh]);

  const value = useMemo(
    () => ({
      ready,
      exportConfigured,
      terms,
      byTerm,
      matchTerms,
      matcher,
      matchAt: matchAtPos,
      refresh,
      getDetail,
      setState,
      exportNote,
      resetKnown,
    }),
    [
      ready,
      exportConfigured,
      terms,
      byTerm,
      matchTerms,
      matcher,
      matchAtPos,
      refresh,
      getDetail,
      setState,
      exportNote,
      resetKnown,
    ]
  );

  return (
    <GlossaryContext.Provider value={value}>{children}</GlossaryContext.Provider>
  );
}

export function useGlossary(): GlossaryContextValue {
  const ctx = useContext(GlossaryContext);
  if (!ctx) {
    throw new Error("useGlossary must be used within GlossaryProvider");
  }
  return ctx;
}

/** 可选：无 Provider 时返回 null（避免硬崩） */
export function useGlossaryOptional(): GlossaryContextValue | null {
  return useContext(GlossaryContext);
}
