"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { ReactNode, useEffect, useMemo } from "react";

/* ---------- 顶部导航（下划线 · design-language §04） ---------- */
/* 信息流置首：每日必看入口 */
const NAV = [
  { href: "/feed", label: "信息流" },
  { href: "/", label: "判断日志" },
  { href: "/console", label: "操作台" },
  { href: "/reviews", label: "复盘" },
  { href: "/reviews/calibration", label: "校准" },
  { href: "/settings", label: "设置" },
];

export function TopNav() {
  const pathname = usePathname();
  const today = useMemo(() => {
    const d = new Date();
    const y = d.getFullYear();
    const m = String(d.getMonth() + 1).padStart(2, "0");
    const day = String(d.getDate()).padStart(2, "0");
    return `${y}-${m}-${day}`;
  }, []);

  return (
    <nav className="topnav">
      {/* 与 操作台.dc.html 一致：品牌+副标+tabs 整组靠左紧挨，日期单独贴右 */}
      <div className="topnav-left">
        <Link href="/feed" className="topnav-brand">
          <span className="mark">ALETHEIA</span>
          <span className="sub">交易辅助工具</span>
        </Link>
        <div className="topnav-links">
          {NAV.map((n) => {
            const active =
              n.href === "/" ? pathname === "/" : pathname === n.href;
            return (
              <Link
                key={n.href}
                href={n.href}
                className={active ? "active" : undefined}
              >
                {n.label}
              </Link>
            );
          })}
        </div>
      </div>
      <span className="topnav-date">{today}</span>
    </nav>
  );
}

/* ---------- Card ---------- */
export function Card({
  title,
  aside,
  className,
  children,
  flush,
}: {
  title?: ReactNode;
  aside?: ReactNode;
  className?: string;
  children: ReactNode;
  /** 无内边距——表格 / 判断链等自管布局 */
  flush?: boolean;
}) {
  return (
    <section className={className ? `card ${className}` : "card"}>
      {(title || aside) && (
        <div className="card-head">
          {typeof title === "string" ? <h2>{title}</h2> : title}
          {aside}
        </div>
      )}
      {flush ? children : <div className="card-content">{children}</div>}
    </section>
  );
}

/* ---------- Chip ---------- */
export function Chip({
  children,
  mono,
}: {
  children: ReactNode;
  mono?: boolean;
}) {
  if (children == null || children === "") return null;
  return <span className={mono ? "chip mono" : "chip"}>{children}</span>;
}

/* ---------- Stat ---------- */
export function Stat({
  value,
  label,
  tone,
}: {
  value: ReactNode;
  label: ReactNode;
  tone?: "pos" | "neg" | "warn";
}) {
  return (
    <div className="stat">
      <div className={tone ? `stat-value ${tone}` : "stat-value"}>{value}</div>
      <div className="stat-label">{label}</div>
    </div>
  );
}

/* ---------- 空态 ---------- */
export function Empty({
  children,
  icon = "○",
}: {
  children: ReactNode;
  icon?: string;
}) {
  return (
    <div className="empty">
      <div className="empty-icon">{icon}</div>
      <div>{children}</div>
    </div>
  );
}

/* ---------- 骨架屏 ---------- */
export function Skeleton({ lines = 3 }: { lines?: number }) {
  return (
    <div aria-hidden style={{ padding: 20 }}>
      {Array.from({ length: lines }).map((_, i) => (
        <div
          key={i}
          className={`skeleton skeleton-line ${
            i === lines - 1 ? "short" : i % 2 ? "mid" : ""
          }`}
        />
      ))}
    </div>
  );
}

export function SkeletonCard({ lines = 3 }: { lines?: number }) {
  return (
    <div className="card">
      <div className="card-head">
        <div
          className="skeleton skeleton-line mid"
          style={{ height: 14, margin: 0, width: "40%" }}
          aria-hidden
        />
      </div>
      <Skeleton lines={lines} />
    </div>
  );
}

/* ---------- Modal ---------- */
export function Modal({
  title,
  onClose,
  children,
  footer,
}: {
  title: ReactNode;
  onClose: () => void;
  children: ReactNode;
  footer?: ReactNode;
}) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      window.removeEventListener("keydown", onKey);
      document.body.style.overflow = prev;
    };
  }, [onClose]);

  return (
    <div
      className="modal-overlay"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div className="modal" role="dialog" aria-modal="true">
        <div className="modal-head">
          <h3>{title}</h3>
          <button
            type="button"
            className="modal-close"
            aria-label="关闭"
            onClick={onClose}
          >
            ×
          </button>
        </div>
        {children}
        {footer && <div className="actions">{footer}</div>}
      </div>
    </div>
  );
}
