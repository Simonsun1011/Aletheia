const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE ?? "http://localhost:8000/api";

export type JudgmentEntry = {
  id: string;
  root_id: string;
  kind: "original" | "amendment" | "retraction" | "review";
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

async function parseError(res: Response): Promise<string> {
  try {
    const body = await res.json();
    return body?.error?.message ?? JSON.stringify(body);
  } catch {
    return res.statusText;
  }
}

export async function apiGet<T>(path: string): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, { cache: "no-store" });
  if (!res.ok) throw new Error(await parseError(res));
  return res.json();
}

export async function apiPost<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(await parseError(res));
  return res.json();
}
