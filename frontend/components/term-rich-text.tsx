"use client";

/**
 * Slice 7：在自由文本中匹配词典术语并包上 Term（信息流摘要等）。
 * 最左最长 + 别名→canonical（slice-07-term-matching）。
 */

import { Fragment, type ReactNode } from "react";
import { Term } from "@/components/term";
import { useGlossaryOptional } from "@/components/glossary-provider";

type Props = {
  text: string;
  context?: string;
  /** 同段文本内同术语只标一次（按 canonical） */
  oncePerTerm?: boolean;
};

export function TermRichText({
  text,
  context,
  oncePerTerm = true,
}: Props) {
  const glossary = useGlossaryOptional();
  if (!text) return null;
  if (!glossary?.ready || glossary.matcher.candidates.length === 0) {
    return <>{text}</>;
  }

  const parts: ReactNode[] = [];
  let pos = 0;
  let key = 0;
  const used = new Set<string>();

  while (pos < text.length) {
    const hit = glossary.matchAt(text, pos);
    if (!hit) {
      // 前进一字符；合并连续未命中为一段
      let end = pos + 1;
      while (end < text.length && !glossary.matchAt(text, end)) {
        end += 1;
      }
      parts.push(<Fragment key={key++}>{text.slice(pos, end)}</Fragment>);
      pos = end;
      continue;
    }
    if (hit.start > pos) {
      parts.push(
        <Fragment key={key++}>{text.slice(pos, hit.start)}</Fragment>
      );
    }
    const fold = hit.canonical.toLowerCase();
    const already = used.has(fold);
    if (oncePerTerm) used.add(fold);
    parts.push(
      <Term
        key={key++}
        term={hit.canonical}
        showMark={!already}
        context={context}
      >
        {hit.surface}
      </Term>
    );
    pos = hit.end;
  }

  return <>{parts}</>;
}
