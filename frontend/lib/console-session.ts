/** 操作台回访状态 — 纯前端，不触发 AI。
 *  键约定见 slice-06「操作台 IA 与回访恢复」。 */

const LAST_SYMBOL_KEY = "console:lastSymbol";
const PENDING_KEY = "console:pendingScans";

function todayUTC(): string {
  return new Date().toISOString().slice(0, 10);
}

/** 模块级：SPA 内导航存活 */
const pendingMemory = new Map<string, string>();

function readPendingStore(): Record<string, string> {
  if (typeof window === "undefined") return {};
  try {
    const raw = sessionStorage.getItem(PENDING_KEY);
    if (!raw) return {};
    const parsed = JSON.parse(raw) as Record<string, string>;
    return parsed && typeof parsed === "object" ? parsed : {};
  } catch {
    return {};
  }
}

function writePendingStore(map: Record<string, string>) {
  if (typeof window === "undefined") return;
  sessionStorage.setItem(PENDING_KEY, JSON.stringify(map));
}

export function getLastConsoleSymbol(): string | null {
  if (typeof window === "undefined") return null;
  const s = localStorage.getItem(LAST_SYMBOL_KEY);
  return s ? s.trim().toUpperCase() : null;
}

export function setLastConsoleSymbol(symbol: string) {
  if (typeof window === "undefined") return;
  const s = symbol.trim().toUpperCase();
  if (!s) return;
  localStorage.setItem(LAST_SYMBOL_KEY, s);
}

/** 标记：某标的已发起扫描、尚未见到当日缓存结果 */
export function markScanPending(symbol: string) {
  const sym = symbol.trim().toUpperCase();
  const day = todayUTC();
  pendingMemory.set(sym, day);
  const store = readPendingStore();
  store[sym] = day;
  writePendingStore(store);
}

export function clearScanPending(symbol: string) {
  const sym = symbol.trim().toUpperCase();
  pendingMemory.delete(sym);
  const store = readPendingStore();
  delete store[sym];
  writePendingStore(store);
}

/** 今日是否仍有「扫描已发起未见结果」标记 */
export function isScanPendingToday(symbol: string): boolean {
  const sym = symbol.trim().toUpperCase();
  const day = todayUTC();
  if (pendingMemory.get(sym) === day) return true;
  const store = readPendingStore();
  return store[sym] === day;
}
