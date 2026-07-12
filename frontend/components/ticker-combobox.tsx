"use client";

import {
  KeyboardEvent,
  MouseEvent as ReactMouseEvent,
  useEffect,
  useId,
  useMemo,
  useRef,
  useState,
} from "react";
import {
  addTicker,
  loadTickers,
  removeTicker,
  resetTickers,
  TickerOption,
} from "@/lib/tickers";

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
  const [tickers, setTickers] = useState<TickerOption[]>(DEFAULT_SAFE);
  const [highlight, setHighlight] = useState(0);
  /** 点 ▾ 展开时看全表；在输入框打字时才按关键字过滤 */
  const [filterActive, setFilterActive] = useState(false);

  useEffect(() => {
    setTickers(loadTickers());
  }, []);

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

  function onAdd() {
    const next = addTicker(tickers, value);
    setTickers(next);
    onChange(value.trim().toUpperCase());
  }

  function onRemove(sym: string, e: ReactMouseEvent) {
    e.stopPropagation();
    e.preventDefault();
    setTickers(removeTicker(tickers, sym));
  }

  function onReset() {
    setTickers(resetTickers());
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
            <div className="ticker-combo-empty">无匹配标的</div>
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
                  aria-label={`删除 ${t.symbol}`}
                  title="从列表删除"
                  onMouseDown={(e) => onRemove(t.symbol, e)}
                >
                  ×
                </button>
              </div>
            ))
          )}
          <div className="ticker-combo-footer">
            {canAdd && (
              <button type="button" onMouseDown={(e) => { e.preventDefault(); onAdd(); }}>
                加入列表：{value.trim().toUpperCase()}
              </button>
            )}
            <button type="button" onMouseDown={(e) => { e.preventDefault(); onReset(); }}>
              恢复默认（AI 科技 + 上游）
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

const DEFAULT_SAFE: TickerOption[] = [];
