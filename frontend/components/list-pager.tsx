"use client";

import { useEffect, useMemo, useState } from "react";

export const LIST_PAGE_SIZE = 20;

/** 客户端分页：每页默认 20 条；resetKey 变化时回到第 1 页。 */
export function usePagedItems<T>(
  items: readonly T[],
  resetKey?: string | number | null,
  pageSize: number = LIST_PAGE_SIZE
) {
  const [page, setPage] = useState(0);
  const pageCount = Math.max(1, Math.ceil(items.length / pageSize) || 1);

  useEffect(() => {
    setPage(0);
  }, [resetKey, pageSize, items.length]);

  useEffect(() => {
    if (page > pageCount - 1) setPage(Math.max(0, pageCount - 1));
  }, [page, pageCount]);

  const slice = useMemo(() => {
    const start = page * pageSize;
    return items.slice(start, start + pageSize);
  }, [items, page, pageSize]);

  return { page, setPage, pageCount, slice, pageSize, total: items.length };
}

type ListPagerProps = {
  page: number;
  pageCount: number;
  total: number;
  pageSize?: number;
  onChange: (page: number) => void;
  className?: string;
};

export function ListPager({
  page,
  pageCount,
  total,
  pageSize = LIST_PAGE_SIZE,
  onChange,
  className,
}: ListPagerProps) {
  if (total <= pageSize) return null;
  const from = page * pageSize + 1;
  const to = Math.min(total, (page + 1) * pageSize);
  return (
    <div className={`list-pager${className ? ` ${className}` : ""}`}>
      <button
        type="button"
        className="secondary btn-small"
        disabled={page <= 0}
        onClick={() => onChange(page - 1)}
      >
        上一页
      </button>
      <span className="muted list-pager-meta">
        {from}–{to} / {total} · 第 {page + 1}/{pageCount} 页
      </span>
      <button
        type="button"
        className="secondary btn-small"
        disabled={page >= pageCount - 1}
        onClick={() => onChange(page + 1)}
      >
        下一页
      </button>
    </div>
  );
}
