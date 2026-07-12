/* Slice 6：统一数字/日期格式化。数字千分位、百分比带符号+语义色、日期双显。
   语义色只由 UI 依据 signClass 施加，此处只算文本与语义标记。 */

export type Sign = "pos" | "neg" | "";

/** 千分位整数/小数 */
export function num(
  v: number | null | undefined,
  digits = 0
): string {
  if (v == null || Number.isNaN(v)) return "—";
  return v.toLocaleString("en-US", {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
}

/** 带符号百分比文本（输入为比率，如 0.023 → +2.3%） */
export function pctText(
  v: number | null | undefined,
  digits = 2
): string {
  if (v == null || Number.isNaN(v)) return "—";
  const p = v * 100;
  const sign = p > 0 ? "+" : "";
  return `${sign}${p.toFixed(digits)}%`;
}

/** 已是百分数值（如 2.3 表示 2.3%）时的带符号文本 */
export function pctRawText(
  v: number | null | undefined,
  digits = 2
): string {
  if (v == null || Number.isNaN(v)) return "—";
  const sign = v > 0 ? "+" : "";
  return `${sign}${v.toFixed(digits)}%`;
}

/** 依据数值返回语义色 class（0 与缺失不着色） */
export function signClass(v: number | null | undefined): Sign {
  if (v == null || Number.isNaN(v) || v === 0) return "";
  return v > 0 ? "pos" : "neg";
}

/** 金额 */
export function money(v: number | null | undefined, digits = 2): string {
  if (v == null || Number.isNaN(v)) return "—";
  return `$${v.toLocaleString("en-US", {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  })}`;
}

/** 通用数值：定点千分位；禁止科学计数（slice-06：消灭 -8.95e-4） */
export function fixed(
  v: number | string | null | undefined,
  digits = 2
): string {
  if (v == null) return "—";
  if (typeof v === "string") return v;
  if (Number.isNaN(v)) return "—";
  const d = v !== 0 && Math.abs(v) < 0.01 ? Math.max(digits, 6) : digits;
  return v.toLocaleString("en-US", {
    minimumFractionDigits: digits,
    maximumFractionDigits: d,
  });
}

/** 字段名是否为涨跌幅/超额类（比率 → 百分比化） */
export function isChangeField(key: string): boolean {
  return /(?:^|[._])(chg|return|excess|drawdown)(?:_|$|\d)/i.test(key) ||
    /_chg_/i.test(key) ||
    /chg_\d/i.test(key) ||
    /drawdown/i.test(key) ||
    /excess_vs/i.test(key);
}

const MONTHS_REL_UNIT = 1000 * 60 * 60 * 24;

/** "7月11日（3天前）" 双显。接受 ISO 字符串或日期串。 */
export function dateRelative(input?: string | null): string {
  if (!input) return "—";
  const iso = input.length <= 10 ? `${input}T00:00:00` : input;
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return input;

  const label = `${d.getMonth() + 1}月${d.getDate()}日`;

  const now = new Date();
  const startOf = (x: Date) =>
    new Date(x.getFullYear(), x.getMonth(), x.getDate()).getTime();
  const diffDays = Math.round((startOf(now) - startOf(d)) / MONTHS_REL_UNIT);

  let rel: string;
  if (diffDays === 0) rel = "今天";
  else if (diffDays === 1) rel = "昨天";
  else if (diffDays === -1) rel = "明天";
  else if (diffDays > 1) rel = `${diffDays}天前`;
  else rel = `${-diffDays}天后`;

  return `${label}（${rel}）`;
}

/** 短日期 YYYY-MM-DD（用于缓存日等） */
export function dateShort(input?: string | null): string {
  if (!input) return "—";
  return input.slice(0, 10);
}
