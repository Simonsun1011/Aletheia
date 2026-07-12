/** 操作台标的列表：默认美股 AI 科技 + 核心上游，可本地增删。 */

export type TickerOption = {
  symbol: string;
  name: string;
};

const STORAGE_KEY = "aletheia.tickers.v1";

/** 默认约 10 只：AI 平台 / 算力 + 半导体制造与设备上游 */
export const DEFAULT_TICKERS: TickerOption[] = [
  { symbol: "NVDA", name: "Nvidia · GPU/CUDA" },
  { symbol: "AVGO", name: "Broadcom · 定制ASIC/网络" },
  { symbol: "AMD", name: "AMD · GPU/CPU" },
  { symbol: "MSFT", name: "Microsoft · 云/AI平台" },
  { symbol: "GOOGL", name: "Alphabet · 云/模型" },
  { symbol: "TSM", name: "TSMC · 晶圆代工（上游）" },
  { symbol: "ASML", name: "ASML · 光刻（上游）" },
  { symbol: "AMAT", name: "Applied Materials · 设备（上游）" },
  { symbol: "LRCX", name: "Lam Research · 刻蚀沉积（上游）" },
  { symbol: "MU", name: "Micron · HBM/存储（上游）" },
];

function normalizeSymbol(s: string): string {
  return s.trim().toUpperCase().replace(/[^A-Z0-9.-]/g, "");
}

function sanitize(list: unknown): TickerOption[] {
  if (!Array.isArray(list)) return [];
  const seen = new Set<string>();
  const out: TickerOption[] = [];
  for (const row of list) {
    if (!row || typeof row !== "object") continue;
    const symbol = normalizeSymbol(String((row as TickerOption).symbol ?? ""));
    if (!symbol || seen.has(symbol)) continue;
    seen.add(symbol);
    const name = String((row as TickerOption).name ?? symbol).trim() || symbol;
    out.push({ symbol, name });
  }
  return out;
}

export function loadTickers(): TickerOption[] {
  if (typeof window === "undefined") return [...DEFAULT_TICKERS];
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (!raw) return [...DEFAULT_TICKERS];
    const parsed = sanitize(JSON.parse(raw));
    return parsed.length > 0 ? parsed : [...DEFAULT_TICKERS];
  } catch {
    return [...DEFAULT_TICKERS];
  }
}

function persist(list: TickerOption[]) {
  if (typeof window === "undefined") return;
  window.localStorage.setItem(STORAGE_KEY, JSON.stringify(list));
}

export function addTicker(
  list: TickerOption[],
  symbol: string,
  name?: string
): TickerOption[] {
  const sym = normalizeSymbol(symbol);
  if (!sym) return list;
  if (list.some((t) => t.symbol === sym)) return list;
  const next = [...list, { symbol: sym, name: (name ?? sym).trim() || sym }];
  persist(next);
  return next;
}

export function removeTicker(
  list: TickerOption[],
  symbol: string
): TickerOption[] {
  const sym = normalizeSymbol(symbol);
  const next = list.filter((t) => t.symbol !== sym);
  persist(next);
  return next;
}

export function resetTickers(): TickerOption[] {
  const next = [...DEFAULT_TICKERS];
  persist(next);
  return next;
}
