/** Slice 7：字段标签注册表 + 按 format 格式化。禁止界面裸 key。 */

import { apiGet } from "@/lib/api";
import {
  dateRelative,
  fixed,
  money,
  pctRawText,
  pctText,
  signClass,
  type Sign,
} from "@/lib/format";

export type FieldFormat =
  | "percent"
  | "percent_point"
  | "price"
  | "number"
  | "ratio"
  | "date"
  | "text";

export type FieldLabelDef = {
  en: string;
  zh: string;
  format: FieldFormat | string;
  family: string | null;
};

type Registry = Record<string, FieldLabelDef>;

let cache: Registry | null = null;
let loadPromise: Promise<Registry> | null = null;
const warned = new Set<string>();

function isDef(v: unknown): v is FieldLabelDef {
  return (
    !!v &&
    typeof v === "object" &&
    typeof (v as FieldLabelDef).zh === "string" &&
    typeof (v as FieldLabelDef).format === "string"
  );
}

export async function loadFieldLabels(): Promise<Registry> {
  if (cache) return cache;
  if (!loadPromise) {
    loadPromise = apiGet<Record<string, unknown>>("/meta/field-labels")
      .then((raw) => {
        const reg: Registry = {};
        for (const [k, v] of Object.entries(raw)) {
          if (k.startsWith("_")) continue;
          if (isDef(v)) reg[k] = v;
        }
        cache = reg;
        return reg;
      })
      .catch((e) => {
        loadPromise = null;
        throw e;
      });
  }
  return loadPromise;
}

/** 解析注册键：精确 → 叶名匹配（forward_eps → fundamental.forward_eps） */
export function resolveFieldKey(key: string, reg: Registry): string | null {
  if (reg[key]) return key;
  const leaf = key.includes(".") ? key.slice(key.lastIndexOf(".") + 1) : key;
  const hits = Object.keys(reg).filter(
    (k) => k === leaf || k.endsWith(`.${leaf}`) || k.endsWith(`.${key}`)
  );
  if (hits.length === 1) return hits[0];
  // 优先更长/更具体的（带 panel 前缀）
  if (hits.length > 1) {
    hits.sort((a, b) => b.length - a.length);
    return hits[0];
  }
  return null;
}

export function getFieldDef(
  key: string,
  reg: Registry | null
): FieldLabelDef | null {
  if (!reg) return null;
  const resolved = resolveFieldKey(key, reg);
  return resolved ? reg[resolved] : null;
}

export function fieldLabelZh(key: string, reg: Registry | null): string {
  const def = getFieldDef(key, reg);
  if (def) return def.zh;
  if (typeof window !== "undefined" && !warned.has(key)) {
    warned.add(key);
    console.warn(`[field_labels] unregistered key: ${key}`);
  }
  return key;
}

export function fieldFamily(
  key: string,
  reg: Registry | null
): string | null {
  return getFieldDef(key, reg)?.family ?? null;
}

export type FormattedValue = {
  text: string;
  sign: Sign;
  format: string;
  /** 数据不可得（null / 空数组 / 文本明示暂缺）——UI 应改挂「缺」角标 */
  missing: boolean;
};

/** 文本是否为「数据不可得」的自陈（开源数据源无此数据、暂缺、N/A…） */
const UNAVAILABLE_RE =
  /(暂缺|暂无数据|无此数据|不可用|数据缺失|开源数据源|免费源|not available|n\/?a|no data)/i;

export function isUnavailableText(s: string): boolean {
  return UNAVAILABLE_RE.test(s.trim());
}

/** 按注册 format 格式化；未注册时兜底 fixed/原样。 */
export function formatFieldValue(
  key: string,
  value: unknown,
  reg: Registry | null
): FormattedValue {
  const def = getFieldDef(key, reg);
  const format = def?.format ?? "text";

  if (value == null) return { text: "—", sign: "", format, missing: true };

  if (typeof value === "number") {
    if (format === "percent") {
      return { text: pctText(value), sign: signClass(value), format, missing: false };
    }
    if (format === "percent_point") {
      // 利率类：原值即百分点，不 ×100
      return { text: pctRawText(value), sign: signClass(value), format, missing: false };
    }
    if (format === "price") {
      return { text: money(value), sign: "", format, missing: false };
    }
    if (format === "number" || format === "ratio") {
      return { text: fixed(value, 2), sign: "", format, missing: false };
    }
    return { text: fixed(value, 2), sign: "", format, missing: false };
  }

  if (format === "date" && typeof value === "string") {
    return { text: dateRelative(value), sign: "", format, missing: false };
  }

  if (Array.isArray(value)) {
    return {
      text: value.length ? value.join(", ") : "—",
      sign: "",
      format,
      missing: value.length === 0,
    };
  }

  const text = String(value);
  return { text, sign: "", format, missing: isUnavailableText(text) };
}

/**
 * family → glossary 术语名（验收：chg 族挂术语；同 Card 内仅首成员显标记）。
 * 映射以 glossary_seed 已有词条为准。
 */
export const FAMILY_TERM: Record<string, string> = {
  vix: "VIX",
  yield: "10年期美债收益率",
  chg: "动量",
  sma: "SMA",
  bollinger: "布林带",
  vwap: "VWAP",
  swing_low: "摆动低点",
  high_52w: "支撑与阻力",
  drawdown: "回撤",
  atr: "ATR",
  rsi: "RSI",
  volatility: "年化波动率",
  relative_return: "相对基准",
  eps: "EPS",
  eps_revision: "盈利预期修正",
  pe: "Forward PE",
  analyst_rating: "分析师评级",
  earnings: "财报季",
  limit_order: "限价单",
  tranche: "分批建仓",
  time_stop: "时间止损",
};

export function termForFamily(family: string | null | undefined): string | null {
  if (!family) return null;
  return FAMILY_TERM[family] ?? null;
}
