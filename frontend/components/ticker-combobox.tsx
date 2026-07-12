"use client";

import {
  KeyboardEvent,
  MouseEvent as ReactMouseEvent,
  useCallback,
  useEffect,
  useId,
  useMemo,
  useRef,
  useState,
} from "react";
import {
  addWatchlistTicker,
  archiveWatchlistTicker,
  fetchWatchlistTickers,
  TickerOption,
} from "@/lib/tickers";
import { toast } from "@/components/toast";

type Props = {
  id?: string;
  value: string;
  onChange: (symbol: string) => void;
  required?: boolean;
  placeholder?: string;
};

export function TickerCombobox({
  id,
  value,
  onChange,
  required,
  placeholder = "NVDA / AMAT",
}: Props) {
  const autoId = useId();
  const inputId = id ?? autoId;
  const rootRef = useRef<HTMLDivElement>(null);
  const [open, setOpen] = useState(false);
  const [tickers, setTickers] = useState<TickerOption[]>([]);
  const [busy, setBusy] = useState(false);
  const [highlight, setHighlight] = useState(0);
  /** 点 ▾ 展开时看全表；在输入框打字时才按关键字过滤 */
  const [filterActive, setFilterActive] = useState(false);

  const refresh = useCallback(async () => {
    try {
      const list = await fetchWatchlistTickers();
      setTickers(list);
    } catch (e) {
      toast.error(String((e as Error).message ?? e));
    }
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  useEffect(() => {
    if (!open) return;
    const onDoc = (e: Event) => {
      if (!rootRef.current?.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, [open]);

  const filtered = useMemo(() => {
    if (!filterActive) return tickers;
    const q = value.trim().toUpperCase();
    if (!q) return tickers;
    return tickers.filter(
      (t) =>
        t.symbol.includes(q) || t.name.toUpperCase().includes(q)
    );
  }, [tickers, value, filterActive]);

  const canAdd =
    !!value.trim() &&
    !tickers.some((t) => t.symbol === value.trim().toUpperCase());

  function select(sym: string) {
    onChange(sym);
    setOpen(false);
  }

  async function onAdd() {
    setBusy(true);
    try {
      const next = await addWatchlistTicker(value);
      setTickers(next);
      onChange(value.trim().toUpperCase());
      toast.success(`已加入关注：${value.trim().toUpperCase()}`);
    } catch (e) {
      toast.error(String((e as Error).message ?? e));
    } finally {
      setBusy(false);
    }
  }

  async function onRemove(sym: string, e: ReactMouseEvent) {
    e.stopPropagation();
    e.preventDefault();
    setBusy(true);
    try {
      const next = await archiveWatchlistTicker(
        sym,
        "archived from ticker combobox"
      );
      setTickers(next);
      if (value.toUpperCase() === sym) onChange("");
      toast.success(`已归档：${sym}`);
    } catch (err) {
      toast.error(String((err as Error).message ?? err));
    } finally {
      setBusy(false);
    }
  }

  function onKeyDown(e: KeyboardEvent<HTMLInputElement>) {
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setOpen(true);
      setHighlight((h) => Math.min(h + 1, Math.max(filtered.length - 1, 0)));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setHighlight((h) => Math.max(h - 1, 0));
    } else if (e.key === "Enter" && open && filtered[highlight]) {
      e.preventDefault();
      select(filtered[highlight].symbol);
    } else if (e.key === "Escape") {
      setOpen(false);
    }
  }

  return (
    <div className="ticker-combo" ref={rootRef}>
      <div className="ticker-combo-row">
        <input
          id={inputId}
          value={value}
          required={required}
          autoComplete="off"
          spellCheck={false}
          placeholder={placeholder}
          onChange={(e) => {
            onChange(e.target.value.toUpperCase());
            setFilterActive(true);
            setOpen(true);
            setHighlight(0);
          }}
          onFocus={() => {
            setFilterActive(false);
            setOpen(true);
          }}
          onKeyDown={onKeyDown}
          aria-expanded={open}
          aria-autocomplete="list"
          role="combobox"
        />
        <button
          type="button"
          className="ticker-combo-toggle"
          aria-label="打开标的列表"
          onClick={() => {
            setFilterActive(false);
            setOpen((o) => !o);
          }}
        >
          {open ? "▴" : "▾"}
        </button>
      </div>

      {open && (
        <div className="ticker-combo-menu" role="listbox">
          {filtered.length === 0 ? (
            <div className="ticker-combo-empty">
              {busy ? "加载中…" : "无匹配标的（可输入后加入关注）"}
            </div>
          ) : (
            filtered.map((t, i) => (
              <div
                key={t.symbol}
                className={
                  i === highlight
                    ? "ticker-combo-item active"
                    : "ticker-combo-item"
                }
                role="option"
                aria-selected={value === t.symbol}
                onMouseEnter={() => setHighlight(i)}
                onMouseDown={(e) => {
                  e.preventDefault();
                  select(t.symbol);
                }}
                style={{ cursor: "pointer" }}
              >
                <span className="ticker-combo-sym">{t.symbol}</span>
                <span className="ticker-combo-name">{t.name}</span>
                <button
                  type="button"
                  className="ticker-combo-del"
                  aria-label={`归档 ${t.symbol}`}
                  title="从关注列表归档（非硬删）"
                  disabled={busy}
                  onMouseDown={(e) => onRemove(t.symbol, e)}
                >
                  ×
                </button>
              </div>
            ))
          )}
          <div className="ticker-combo-footer">
            {canAdd && (
              <button
                type="button"
                disabled={busy}
                onMouseDown={(e) => {
                  e.preventDefault();
                  onAdd();
                }}
              >
                加入关注：{value.trim().toUpperCase()}
              </button>
            )}
            <span className="muted" style={{ fontSize: 11, padding: "4px 8px" }}>
              来源：watchlist（单一权威）
            </span>
          </div>
        </div>
      )}
    </div>
  );
}
