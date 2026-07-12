"use client";

import { useEffect, useReducer } from "react";

type ToastKind = "success" | "error" | "info";
type ToastItem = { id: number; kind: ToastKind; text: string };

let items: ToastItem[] = [];
let nextId = 1;
const listeners = new Set<() => void>();

function emit() {
  for (const l of listeners) l();
}

function push(text: string, kind: ToastKind, ttl: number) {
  const id = nextId++;
  items = [...items, { id, kind, text }];
  emit();
  if (typeof window !== "undefined") {
    window.setTimeout(() => {
      items = items.filter((t) => t.id !== id);
      emit();
    }, ttl);
  }
}

export const toast = {
  success: (text: string) => push(text, "success", 3000),
  error: (text: string) => push(text, "error", 5000),
  info: (text: string) => push(text, "info", 3000),
};

export function Toaster() {
  const [, force] = useReducer((x) => x + 1, 0);
  useEffect(() => {
    const l = () => force();
    listeners.add(l);
    return () => {
      listeners.delete(l);
    };
  }, []);

  if (items.length === 0) return null;
  return (
    <div className="toast-wrap" role="status" aria-live="polite">
      {items.map((t) => (
        <div key={t.id} className={`toast toast-${t.kind}`}>
          <span className="toast-dot" />
          <span>{t.text}</span>
        </div>
      ))}
    </div>
  );
}
