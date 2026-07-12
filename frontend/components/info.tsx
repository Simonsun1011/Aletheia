import { ReactNode } from "react";

/** 六类信息编码 — DESIGN.md §2.1 / design-language.html §03
 *  只在异质混排处出场；同质区整区安静（无标签）。 */

export type InfoType =
  | "fact"
  | "data"
  | "ai"
  | "view"
  | "judgment"
  | "assumption";

const META: Record<
  InfoType,
  { label: string; className: string; dot?: boolean }
> = {
  fact: { label: "事实", className: "type-fact" },
  data: { label: "数据", className: "type-data" },
  ai: { label: "AI 摘要", className: "type-ai", dot: true },
  view: { label: "观点", className: "type-view" },
  judgment: { label: "我", className: "type-judge" },
  assumption: { label: "假设", className: "type-assume" },
};

export function TypeTag({ type }: { type: InfoType }) {
  const m = META[type];
  return (
    <span className={`type-tag ${m.className}`}>
      {m.dot && <span className="dot" aria-hidden />}
      {m.label}
    </span>
  );
}

/** 混排行：标签 + 内容 */
export function InfoRow({
  type,
  children,
  className,
}: {
  type: InfoType;
  children: ReactNode;
  className?: string;
}) {
  const wrap =
    type === "ai"
      ? "info-row info-ai"
      : type === "judgment"
        ? "info-row info-judgment"
        : type === "assumption"
          ? "info-row info-assumption"
          : "info-row";
  return (
    <div className={className ? `${wrap} ${className}` : wrap}>
      <TypeTag type={type} />
      <div style={{ flex: 1, minWidth: 0 }}>{children}</div>
    </div>
  );
}

/** AI 区块外壳（同质 AI 区：紫底，可无逐条标签） */
export function AiBlock({
  children,
  tagged = true,
}: {
  children: ReactNode;
  tagged?: boolean;
}) {
  return (
    <div className="info-ai">
      {tagged ? (
        <div className="info-row" style={{ margin: 0 }}>
          <TypeTag type="ai" />
          <div style={{ flex: 1, minWidth: 0 }}>{children}</div>
        </div>
      ) : (
        children
      )}
    </div>
  );
}

/** 判断区块外壳（蓝色左栏） */
export function JudgmentBlock({
  children,
  tagged = true,
}: {
  children: ReactNode;
  tagged?: boolean;
}) {
  return (
    <div className="info-judgment">
      {tagged ? (
        <div className="info-row" style={{ margin: 0 }}>
          <TypeTag type="judgment" />
          <div style={{ flex: 1, minWidth: 0 }}>{children}</div>
        </div>
      ) : (
        children
      )}
    </div>
  );
}
