"""Deterministic relevance whitelist + blocklist (Slice 3b / 3c)."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Optional

from backend.app.config import REPO_ROOT

try:
    import tomllib
except ModuleNotFoundError:
    import tomli as tomllib  # type: ignore


@dataclass
class RelevanceLexicon:
    """Patterns → optional ticker (None = theme keyword only)."""

    # (term, ticker|None, scope) scope: "title" = aliases; "any" = tickers/themes
    terms: list[tuple[str, Optional[str], str]] = field(default_factory=list)
    # Slice 3c: negative patterns — substring match on title+body, case-insensitive
    block_patterns: list[str] = field(default_factory=list)

    def is_blocked(self, title: str, content: str) -> bool:
        hay = f"{title or ''}\n{_first_paragraph(content)}"
        low = hay.lower()
        for pat in self.block_patterns:
            if pat and pat.lower() in low:
                return True
        return False

    def is_relevant(self, title: str, content: str) -> tuple[bool, list[str]]:
        """Match title + first paragraph.

        Blocklist wins over positive hits (Slice 3c).
        Company aliases only count in the **title** (avoids summary name-drops
        like "available on Amazon" / "vs Nvidia" falsely keeping noise cards).
        Tickers and theme keywords may match title or body.
        """
        if self.is_blocked(title, content):
            return False, []
        head = _first_paragraph(content)
        title_hay = title or ""
        any_hay = f"{title}\n{head}"
        tickers: list[str] = []
        hit = False
        for term, ticker, scope in self.terms:
            hay = title_hay if scope == "title" else any_hay
            mode = "phrase" if scope == "title" else "substring"
            if _contains(hay, term, mode=mode):
                hit = True
                if ticker:
                    t = ticker.upper()
                    if t not in tickers:
                        tickers.append(t)
        return hit, tickers

    def match_detail(
        self, title: str, content: str
    ) -> dict[str, object]:
        """Breakdown for priority scoring (title tickers / body tickers / theme)."""
        if self.is_blocked(title, content):
            return {
                "blocked": True,
                "relevant": False,
                "title_tickers": [],
                "body_tickers": [],
                "theme_hit": False,
            }
        head = _first_paragraph(content)
        title_hay = title or ""
        any_hay = f"{title}\n{head}"
        title_tickers: list[str] = []
        body_tickers: list[str] = []
        theme_hit = False
        for term, ticker, scope in self.terms:
            if scope == "title":
                if _contains(title_hay, term, mode="phrase") and ticker:
                    t = ticker.upper()
                    if t not in title_tickers:
                        title_tickers.append(t)
            else:
                if _contains(any_hay, term, mode="substring"):
                    if ticker:
                        t = ticker.upper()
                        # body-only if not already in title
                        if t not in title_tickers and t not in body_tickers:
                            if _contains(title_hay, term, mode="substring"):
                                if t not in title_tickers:
                                    title_tickers.append(t)
                            else:
                                body_tickers.append(t)
                    else:
                        theme_hit = True
        # Also: ticker symbols appearing in title as tokens
        relevant = bool(title_tickers or body_tickers or theme_hit)
        # Reconcile with is_relevant for objects merge
        hit, matched = self.is_relevant(title, content)
        return {
            "blocked": False,
            "relevant": hit,
            "title_tickers": title_tickers,
            "body_tickers": body_tickers,
            "theme_hit": theme_hit,
            "matched": matched,
        }

    def match(self, title: str, content: str) -> list[str]:
        hit, tickers = self.is_relevant(title, content)
        return tickers if hit else []


def _first_paragraph(content: str) -> str:
    text = (content or "").strip()
    if not text:
        return ""
    # first ~800 chars / first blank-line block
    chunk = text[:800]
    parts = re.split(r"\n\s*\n", chunk, maxsplit=1)
    return parts[0]


def _contains(haystack: str, needle: str, *, mode: str = "auto") -> bool:
    if not needle:
        return False
    n = needle.strip()
    if mode == "substring":
        return n.lower() in haystack.lower()
    # phrase / ticker: word boundaries (aliases, watchlist codes)
    if re.fullmatch(r"[A-Za-z]{1,5}", n) or re.fullmatch(r"[A-Za-z][A-Za-z0-9 .&'-]+", n):
        return (
            re.search(rf"(?<![A-Za-z]){re.escape(n)}(?![A-Za-z])", haystack, re.I)
            is not None
        )
    return n.lower() in haystack.lower()


def relevance_path() -> Path:
    return REPO_ROOT / "config" / "relevance.toml"


def load_relevance(
    *,
    watchlist_tickers: Iterable[str] = (),
    path: Optional[Path] = None,
) -> RelevanceLexicon:
    p = path or relevance_path()
    data = tomllib.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
    terms: list[tuple[str, Optional[str], str]] = []

    aliases = data.get("aliases") or {}
    for alias, ticker in aliases.items():
        terms.append((str(alias), str(ticker).upper(), "title"))

    tk = data.get("theme_keywords") or {}
    for term in tk.get("terms") or []:
        terms.append((str(term), None, "any"))

    for t in watchlist_tickers:
        sym = str(t).strip().upper()
        if sym:
            terms.append((sym, sym, "any"))

    block = data.get("blocklist") or {}
    patterns = [str(x) for x in (block.get("patterns") or []) if str(x).strip()]

    return RelevanceLexicon(terms=terms, block_patterns=patterns)
