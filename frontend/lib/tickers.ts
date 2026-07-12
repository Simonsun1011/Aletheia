/**
 * Slice 8b: watchlist 为公司清单唯一权威。
 * DEFAULT_TICKERS 仅作一次性迁入种子（后端 GET /watchlist 空库时也会种子）；
 * localStorage 不再是数据源，仅在前端启动时尝试一次性迁入后清除。
 */

import { apiGet, apiPost } from "@/lib/api";

export type TickerOption = {
  symbol: string;
  name: string;
};

const STORAGE_KEY = "aletheia.tickers.v1";
const MIGRATED_KEY = "aletheia.tickers.migrated.v1";

/** 默认约 10 只：与后端 DEFAULT_WATCHLIST_SEED 对齐（文档/迁入用） */
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

type WatchlistItem = {
  ticker: string;
  add_reason: string;
  status: string;
  tier: string;
};

type WatchlistResponse = {
  active: WatchlistItem[];
  shadow: WatchlistItem[];
};

const TIER_ORDER: Record<string, number> = {
  focus: 0,
  base: 1,
  muted: 2,
};

function normalizeSymbol(s: string): string {
  return s.trim().toUpperCase().replace(/[^A-Z0-9.-]/g, "");
}

function readLegacyLocalStorage(): TickerOption[] {
  if (typeof window === "undefined") return [];
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    if (!Array.isArray(parsed)) return [];
    const out: TickerOption[] = [];
    const seen = new Set<string>();
    for (const row of parsed) {
      if (!row || typeof row !== "object") continue;
      const symbol = normalizeSymbol(String((row as TickerOption).symbol ?? ""));
      if (!symbol || seen.has(symbol)) continue;
      seen.add(symbol);
      const name = String((row as TickerOption).name ?? symbol).trim() || symbol;
      out.push({ symbol, name });
    }
    return out;
  } catch {
    return [];
  }
}

function clearLegacyLocalStorage() {
  if (typeof window === "undefined") return;
  window.localStorage.removeItem(STORAGE_KEY);
  window.localStorage.setItem(MIGRATED_KEY, "1");
}

function alreadyMigrated(): boolean {
  if (typeof window === "undefined") return true;
  return window.localStorage.getItem(MIGRATED_KEY) === "1";
}

function toOptions(wl: WatchlistResponse): TickerOption[] {
  const rows = [...wl.active].sort((a, b) => {
    const ta = TIER_ORDER[a.tier] ?? 9;
    const tb = TIER_ORDER[b.tier] ?? 9;
    if (ta !== tb) return ta - tb;
    return a.ticker.localeCompare(b.ticker);
  });
  return rows.map((r) => ({
    symbol: r.ticker,
    name: r.add_reason?.replace(/^slice8b default seed:\s*/i, "") || r.ticker,
  }));
}

/** 拉取 watchlist active；必要时一次性迁入旧 localStorage。 */
export async function fetchWatchlistTickers(): Promise<TickerOption[]> {
  let wl = await apiGet<WatchlistResponse>("/watchlist");

  if (!alreadyMigrated()) {
    const legacy = readLegacyLocalStorage();
    const have = new Set(wl.active.map((x) => x.ticker.toUpperCase()));
    for (const t of legacy) {
      if (have.has(t.symbol)) continue;
      try {
        await apiPost("/watchlist", {
          ticker: t.symbol,
          add_reason: `migrated from localStorage: ${t.name}`,
          tier: "base",
        });
        have.add(t.symbol);
      } catch {
        /* skip conflicts / offline */
      }
    }
    clearLegacyLocalStorage();
    wl = await apiGet<WatchlistResponse>("/watchlist");
  }

  return toOptions(wl);
}

export async function addWatchlistTicker(
  symbol: string,
  name?: string
): Promise<TickerOption[]> {
  const sym = normalizeSymbol(symbol);
  if (!sym) return fetchWatchlistTickers();
  await apiPost("/watchlist", {
    ticker: sym,
    add_reason: (name ?? sym).trim() || sym,
    tier: "base",
  });
  return fetchWatchlistTickers();
}

export async function archiveWatchlistTicker(
  symbol: string,
  reason = "removed from combobox"
): Promise<TickerOption[]> {
  const sym = normalizeSymbol(symbol);
  if (!sym) return fetchWatchlistTickers();
  await apiPost(`/watchlist/${encodeURIComponent(sym)}/archive`, {
    archive_reason: reason,
  });
  return fetchWatchlistTickers();
}
