import { ReactNode } from "react";

/**
 * 小标签族 —— design-language 小角标。
 * 只承载语义（单位 / 计数 / 来源 / 缺失），不做装饰。
 */

type BadgeVariant = "unit" | "count" | "source" | "missing";

export function Badge({
  variant = "unit",
  children,
  title,
}: {
  variant?: BadgeVariant;
  children: ReactNode;
  title?: string;
}) {
  return (
    <span className={`badge badge-${variant}`} title={title}>
      {children}
    </span>
  );
}

/** 面板头右上单位角标（VIX / EPS / ATR …） */
export function UnitTag({ children }: { children: ReactNode }) {
  return <Badge variant="unit">{children}</Badge>;
}

/** 计数胶囊（持仓 2 / 多方 3 …） */
export function CountPill({ children }: { children: ReactNode }) {
  return <Badge variant="count">{children}</Badge>;
}

/**
 * 缺失角标「缺」+ 可选原因。
 * 用于数据不可得（开源数据源无此字段、指标暂缺）——不是 0，也不是错误。
 */
export function MissingBadge({ reason }: { reason?: ReactNode }) {
  return (
    <span className="missing-cell">
      <Badge variant="missing" title="数据缺失 / 开源数据源不提供">
        缺
      </Badge>
      {reason ? <span className="missing-reason">{reason}</span> : null}
    </span>
  );
}
