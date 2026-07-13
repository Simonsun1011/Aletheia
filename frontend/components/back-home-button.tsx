"use client";

import { useCallback, useEffect, useState } from "react";

/** 全站浮动「顶部」：仅看外层文档是否超过约两屏，内窗滚动不计入。 */
export function BackHomeButton() {
  const [visible, setVisible] = useState(false);

  const sync = useCallback(() => {
    const vh = window.innerHeight;
    const pageH = Math.max(
      document.documentElement.scrollHeight,
      document.body.scrollHeight
    );
    const scrollY = window.scrollY || document.documentElement.scrollTop || 0;
    // 外页不足两屏：永不出现；满两屏后，滚过约两屏才显示
    setVisible(pageH > vh * 2 && scrollY > vh * 2);
  }, []);

  useEffect(() => {
    sync();
    window.addEventListener("scroll", sync, { passive: true });
    window.addEventListener("resize", sync);
    const ro = new ResizeObserver(sync);
    ro.observe(document.documentElement);
    return () => {
      window.removeEventListener("scroll", sync);
      window.removeEventListener("resize", sync);
      ro.disconnect();
    };
  }, [sync]);

  function goTop() {
    window.scrollTo({ top: 0, behavior: "smooth" });
  }

  return (
    <button
      type="button"
      className={`feed-back-top${visible ? " is-visible" : ""}`}
      aria-label="回到页面顶部"
      onClick={goTop}
    >
      <span className="feed-back-top-icon" aria-hidden>
        ↑
      </span>
      顶部
    </button>
  );
}
