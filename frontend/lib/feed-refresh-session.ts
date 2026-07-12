/** 信息流「生成今日简报」会话 — 跨 SPA tab 保活，靠后端状态轮询。 */

const PENDING_KEY = "feed:refreshPending";
const STALE_MS = 3 * 60 * 1000; // 心跳超过 3 分钟仍 running → 提示可能卡住（不硬停）

export type FeedRefreshStatus = {
  running: boolean;
  phase?: string | null;
  batch_date?: string | null;
  started_at?: string | null;
  finished_at?: string | null;
  heartbeat_at?: string | null;
  message?: string | null;
  error?: string | null;
  result?: {
    batch_date: string;
    cards: number;
    fetch?: { raw?: number };
    digest?: { ok?: number; filtered?: number; cancelled?: number };
  } | null;
  accepted?: boolean;
};

function todayUTC(): string {
  return new Date().toISOString().slice(0, 10);
}

export function markFeedRefreshPending(batchDate?: string) {
  if (typeof window === "undefined") return;
  sessionStorage.setItem(
    PENDING_KEY,
    JSON.stringify({ day: batchDate || todayUTC(), at: Date.now() })
  );
}

export function clearFeedRefreshPending() {
  if (typeof window === "undefined") return;
  sessionStorage.removeItem(PENDING_KEY);
}

export function isFeedRefreshPending(): boolean {
  if (typeof window === "undefined") return false;
  try {
    const raw = sessionStorage.getItem(PENDING_KEY);
    if (!raw) return false;
    const parsed = JSON.parse(raw) as { day?: string };
    return parsed.day === todayUTC();
  } catch {
    return false;
  }
}

export function isHeartbeatStale(status: FeedRefreshStatus): boolean {
  if (!status.running || !status.heartbeat_at) return false;
  const t = Date.parse(status.heartbeat_at);
  if (Number.isNaN(t)) return false;
  return Date.now() - t > STALE_MS;
}
