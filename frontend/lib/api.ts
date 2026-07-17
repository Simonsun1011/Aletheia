const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE ?? "http://localhost:8000/api";

/** 默认偏短；扫描/promote 等 LLM 调用用长超时 */
const FETCH_TIMEOUT_MS = 15_000;
const LLM_FETCH_TIMEOUT_MS = 120_000;

/** Drive-by CSRF soft gate — backend RequireClientHeaderMiddleware */
const CLIENT_HEADERS: Record<string, string> = {
  "X-Aletheia-Client": "1",
};

function withTimeout(
  init: RequestInit = {},
  timeoutMs: number = FETCH_TIMEOUT_MS
): RequestInit {
  const signal =
    typeof AbortSignal !== "undefined" && "timeout" in AbortSignal
      ? AbortSignal.timeout(timeoutMs)
      : undefined;
  return signal ? { ...init, signal } : init;
}

export type JudgmentEntry = {
  id: string;
  root_id: string;
  kind: "original" | "revision" | "amendment" | "retraction" | "review";
  created_at: string;
  object: string;
  jtype?: string | null;
  direction?: string | null;
  horizon_days?: number | null;
  confidence?: number | null;
  text: string;
  expires_on?: string | null;
  status: "open" | "closed";
};

export type JudgmentChain = {
  root_id: string;
  object: string;
  status: "open" | "closed";
  entries: JudgmentEntry[];
};

export type QuickNote = {
  id: string;
  created_at: string;
  text: string;
  object?: string | null;
};

/** Exported for unit tests — contract §1 flat envelope only. */
export async function parseError(res: Response): Promise<string> {
  try {
    const body = await res.json();
    const code = body?.error?.code;
    const msg = body?.error?.message;
    if (typeof msg === "string" && msg.length > 0) {
      return code ? `[${code}] ${msg}` : msg;
    }
    return res.statusText || "request failed";
  } catch {
    return res.statusText;
  }
}

function friendlyFetchError(err: unknown, kind: "read" | "llm" = "read"): Error {
  if (err instanceof DOMException && err.name === "TimeoutError") {
    if (kind === "llm") {
      return new Error(
        "请求超时：扫描等 AI 调用可能需数十秒；请稍后重试，并确认后端在跑"
      );
    }
    return new Error(
      "读取超时：默认应秒级返回。若正在「生成简报」，可先停止生成或稍后重试"
    );
  }
  if (err instanceof TypeError) {
    return new Error(
      "无法连接后端：请确认 uvicorn 在跑，且端口与 .env.local 一致"
    );
  }
  return err instanceof Error ? err : new Error(String(err));
}

export async function apiGet<T>(path: string): Promise<T> {
  try {
    const res = await fetch(
      `${API_BASE}${path}`,
      withTimeout({ cache: "no-store" })
    );
    if (!res.ok) throw new Error(await parseError(res));
    return res.json();
  } catch (err) {
    throw friendlyFetchError(err, "read");
  }
}

export async function apiPost<T>(
  path: string,
  body: unknown,
  opts?: { timeoutMs?: number }
): Promise<T> {
  try {
    const res = await fetch(
      `${API_BASE}${path}`,
      withTimeout(
        {
          method: "POST",
          headers: { "Content-Type": "application/json", ...CLIENT_HEADERS },
          body: JSON.stringify(body),
        },
        opts?.timeoutMs ?? FETCH_TIMEOUT_MS
      )
    );
    if (!res.ok) throw new Error(await parseError(res));
    return res.json();
  } catch (err) {
    throw friendlyFetchError(err, "read");
  }
}

export async function apiPatch<T>(path: string, body: unknown): Promise<T> {
  try {
    const res = await fetch(
      `${API_BASE}${path}`,
      withTimeout({
        method: "PATCH",
        headers: { "Content-Type": "application/json", ...CLIENT_HEADERS },
        body: JSON.stringify(body),
      })
    );
    if (!res.ok) throw new Error(await parseError(res));
    return res.json();
  } catch (err) {
    throw friendlyFetchError(err, "read");
  }
}

/** LLM 交互（扫描 / promote 等）— 更长超时 */
export async function apiPostLlm<T>(path: string, body: unknown): Promise<T> {
  try {
    const res = await fetch(
      `${API_BASE}${path}`,
      withTimeout(
        {
          method: "POST",
          headers: { "Content-Type": "application/json", ...CLIENT_HEADERS },
          body: JSON.stringify(body),
        },
        LLM_FETCH_TIMEOUT_MS
      )
    );
    if (!res.ok) throw new Error(await parseError(res));
    return res.json();
  } catch (err) {
    throw friendlyFetchError(err, "llm");
  }
}
