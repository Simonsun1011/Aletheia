"use client";

/**
 * Slice 7：统一字段标签 — 禁止裸 underscore key。
 */

import { useEffect, useState } from "react";
import { Term } from "@/components/term";
import { MissingBadge } from "@/components/badge";
import {
  fieldFamily,
  fieldLabelZh,
  formatFieldValue,
  getFieldDef,
  loadFieldLabels,
  termForFamily,
  type FieldLabelDef,
} from "@/lib/field-labels";

type Registry = Record<string, FieldLabelDef>;

let sharedReg: Registry | null = null;

export function useFieldLabels(): Registry | null {
  const [reg, setReg] = useState<Registry | null>(sharedReg);
  useEffect(() => {
    if (sharedReg) {
      setReg(sharedReg);
      return;
    }
    loadFieldLabels()
      .then((r) => {
        sharedReg = r;
        setReg(r);
      })
      .catch((e) => console.warn("[field_labels] load failed", e));
  }, []);
  return reg;
}

/** 仅标签文本（已解析 zh） */
export function LabelText({ fieldKey }: { fieldKey: string }) {
  const reg = useFieldLabels();
  return <>{fieldLabelZh(fieldKey, reg)}</>;
}

type DataRowProps = {
  fieldKey: string;
  value: unknown;
  /** 同 Card 内该 family 是否已有标记（首成员为 true） */
  showFamilyMark?: boolean;
  context?: string;
};

/** 一行：标签（可挂 Term）+ 格式化值 */
export function LabeledValue({
  fieldKey,
  value,
  showFamilyMark = true,
  context,
}: DataRowProps) {
  const reg = useFieldLabels();
  const def = getFieldDef(fieldKey, reg);
  const formatted = formatFieldValue(fieldKey, value, reg);

  // 未登记且值为「缺失说明」的字段（如后端塞进数据里的 *_note 注记）：
  // 不显示底层键名，整行降级为一条缺失注记。
  if (!def && formatted.missing) {
    return (
      <div className="data-row data-row-note">
        <MissingBadge
          reason={formatted.text === "—" ? "暂无数据" : formatted.text}
        />
      </div>
    );
  }

  const zh = fieldLabelZh(fieldKey, reg);
  const family = fieldFamily(fieldKey, reg);
  const term = termForFamily(family);

  return (
    <div className="data-row">
      <span className="k">
        {term ? (
          <Term term={term} showMark={showFamilyMark} context={context}>
            {zh}
          </Term>
        ) : (
          zh
        )}
      </span>
      <span className={formatted.sign ? `v ${formatted.sign}` : "v"}>
        {formatted.missing ? (
          // 值为 null 时只挂「缺」；文本自陈暂缺时「缺 + 原文」
          <MissingBadge
            reason={formatted.text === "—" ? undefined : formatted.text}
          />
        ) : (
          formatted.text
        )}
      </span>
    </div>
  );
}

/**
 * 同质数据表：按出现顺序，同 family 仅首行 showMark。
 * 跳过 warnings 等非指标键。
 * columns=2：技术面等长表按样板内部分两列（发丝竖线分隔）。
 */
export function LabeledKvTable({
  data,
  context,
  skipKeys = ["warnings", "schema_version", "as_of", "symbol"],
  columns = 1,
}: {
  data: Record<string, unknown> | null;
  context?: string;
  skipKeys?: string[];
  columns?: 1 | 2;
}) {
  const entries = data ? flatten(data) : [];
  const filtered = entries.filter(([k]) => !skipKeys.includes(k));
  const seenFamily = new Set<string>();
  const reg = useFieldLabels();

  if (filtered.length === 0) {
    return <p className="muted">暂无数据</p>;
  }

  const rows = filtered.map(([k, v]) => {
    const fam = fieldFamily(k, reg);
    let showMark = false;
    if (fam) {
      if (!seenFamily.has(fam)) {
        seenFamily.add(fam);
        showMark = true;
      }
    }
    return (
      <LabeledValue
        key={k}
        fieldKey={k}
        value={v}
        showFamilyMark={showMark}
        context={context}
      />
    );
  });

  if (columns === 2 && rows.length > 4) {
    const mid = Math.ceil(rows.length / 2);
    return (
      <div className="kv-split">
        <div className="kv-split-col">{rows.slice(0, mid)}</div>
        <div className="kv-split-col">{rows.slice(mid)}</div>
      </div>
    );
  }

  return <div>{rows}</div>;
}

function flatten(
  data: Record<string, unknown>,
  prefix = ""
): [string, unknown][] {
  const out: [string, unknown][] = [];
  for (const [k, v] of Object.entries(data)) {
    const key = prefix ? `${prefix}.${k}` : k;
    if (v && typeof v === "object" && !Array.isArray(v)) {
      out.push(...flatten(v as Record<string, unknown>, key));
    } else {
      out.push([key, v]);
    }
  }
  return out;
}
