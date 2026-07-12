/**
 * Slice 7 term-matching：预编译分类匹配器（DESIGN §3.5.5）。
 * 纯函数，可供 Node 单测；Provider 编译一次后复用。
 */

export type MatchHit = {
  surface: string;
  canonical: string;
  start: number;
  end: number;
};

export type GlossaryCandidate = {
  /** 显示/匹配表面（canonical 或 alias） */
  surface: string;
  canonical: string;
};

type CompiledLatin = {
  kind: "latin";
  surface: string;
  canonical: string;
  /** 已带词边界 + sticky y；全大写缩写无 i 标志 */
  re: RegExp;
};

type CompiledCjk = {
  kind: "cjk";
  surface: string;
  canonical: string;
  surfaceLower: string;
};

export type CompiledMatcher = {
  candidates: Array<CompiledLatin | CompiledCjk>;
};

const CJK_RE = /[\u3400-\u9FFF\uF900-\uFAFF]/;
const HAS_LOWER_RE = /[a-z]/;

/** 仅 ASCII 字母数字与常见金融符号 → 拉丁候选 */
export function isLatinSurface(s: string): boolean {
  if (!s) return false;
  if (CJK_RE.test(s)) return false;
  // 允许字母数字与常见符号（& / - . + 空格等）
  return /^[\x20-\x7E]+$/.test(s);
}

/** 全大写缩写：无小写字母（PE / EPS / SEC / VWAP / HBM / 8-K） */
export function isAllCapsAbbrev(s: string): boolean {
  return isLatinSurface(s) && !HAS_LOWER_RE.test(s) && /[A-Za-z]/.test(s);
}

function escapeRegExp(s: string): string {
  return s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

/**
 * 从词条列表构建匹配器。
 * 候选 = 所有 canonical ∪ 所有 alias；按 surface 长度降序。
 */
export function buildMatcher(
  terms: { term: string; aliases?: string[] | null }[]
): CompiledMatcher {
  const raw: GlossaryCandidate[] = [];
  const seenSurface = new Set<string>();
  for (const t of terms) {
    const canonical = t.term.trim();
    if (!canonical) continue;
    const surfaces = [canonical, ...(t.aliases ?? []).map((a) => a.trim()).filter(Boolean)];
    for (const surface of surfaces) {
      const key = surface.toLowerCase();
      // 同一 surface 只保留首次（canonical 优先于后写的别名冲突——导入期已拦）
      if (seenSurface.has(key)) continue;
      seenSurface.add(key);
      raw.push({ surface, canonical });
    }
  }
  raw.sort((a, b) => b.surface.length - a.surface.length);

  const candidates: CompiledMatcher["candidates"] = [];
  for (const c of raw) {
    if (isLatinSurface(c.surface)) {
      const body = escapeRegExp(c.surface);
      // y=粘性：必须从 lastIndex 起命中，lookbehind 才能看到全文真实前字符
      const flags = isAllCapsAbbrev(c.surface) ? "y" : "iy";
      // ASCII 词边界：前后不是字母数字
      const re = new RegExp(`(?<![A-Za-z0-9])${body}(?![A-Za-z0-9])`, flags);
      candidates.push({
        kind: "latin",
        surface: c.surface,
        canonical: c.canonical,
        re,
      });
    } else {
      candidates.push({
        kind: "cjk",
        surface: c.surface,
        canonical: c.canonical,
        surfaceLower: c.surface.toLowerCase(),
      });
    }
  }
  return { candidates };
}

/** 从 pos 起，取以此处开头的最长命中（最左最长的一步）。 */
export function matchAt(
  matcher: CompiledMatcher,
  text: string,
  pos: number
): MatchHit | null {
  if (pos < 0 || pos >= text.length) return null;
  let best: MatchHit | null = null;
  for (const c of matcher.candidates) {
    if (c.kind === "latin") {
      // 全文 + sticky y：左回顾看到 text[pos-1]，勿对 slice 跑正则
      c.re.lastIndex = pos;
      const m = c.re.exec(text);
      if (!m || m.index !== pos) continue;
      const end = pos + m[0].length;
      const surface = text.slice(pos, end);
      if (!best || surface.length > best.surface.length) {
        best = { surface, canonical: c.canonical, start: pos, end };
      }
    } else {
      // 中文：大小写不敏感子串，必须从当前位置开头（无词边界）
      if (text.toLowerCase().startsWith(c.surfaceLower, pos)) {
        const end = pos + c.surface.length;
        const surface = text.slice(pos, end);
        if (!best || surface.length > best.surface.length) {
          best = { surface, canonical: c.canonical, start: pos, end };
        }
      }
    }
  }
  return best;
}

/** 扫描全文 → 命中列表（不重叠，最左最长）。 */
export function findAllMatches(
  matcher: CompiledMatcher,
  text: string
): MatchHit[] {
  const hits: MatchHit[] = [];
  let pos = 0;
  while (pos < text.length) {
    const hit = matchAt(matcher, text, pos);
    if (hit) {
      hits.push(hit);
      pos = hit.end;
    } else {
      pos += 1;
    }
  }
  return hits;
}

/** 是否含 CJK（用于双语标题选跨语言别名） */
export function hasCjk(s: string): boolean {
  return CJK_RE.test(s);
}

/**
 * 双语标题：canonical · 首个跨语言别名
 * 例：VIX · 波动率指数；布林带 · Bollinger Bands
 */
export function bilingualTitle(
  term: string,
  aliases: string[] | null | undefined
): { primary: string; secondary: string | null; display: string } {
  const primary = term.trim();
  const list = aliases ?? [];
  const wantCjk = !hasCjk(primary);
  const secondary =
    list.find((a) => (wantCjk ? hasCjk(a) : isLatinSurface(a) && !hasCjk(a))) ??
    null;
  return {
    primary,
    secondary,
    display: secondary ? `${primary} · ${secondary}` : primary,
  };
}
