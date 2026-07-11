"""AI output guard — conclusion / summary iron law / attributed_views."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, Optional

from backend.app.config import REPO_ROOT

try:
    import tomllib
except ModuleNotFoundError:
    import tomli as tomllib  # type: ignore

Ruleset = Literal["conclusion", "summary", "attributed_views"]


@dataclass
class GuardResult:
    ok: bool
    matched: list[str] = field(default_factory=list)
    ruleset: str = "conclusion"
    normalized_text: str = ""


def blocklist_path() -> Path:
    return REPO_ROOT / "config" / "guard_blocklist.toml"


_CACHE: dict[str, object] = {}


def reset_guard_cache() -> None:
    _CACHE.clear()


def normalize_for_guard(text: str) -> str:
    return unicodedata.normalize("NFKC", text or "")


def _compile_list(raw: list) -> list[re.Pattern[str]]:
    return [re.compile(str(pat), re.IGNORECASE) for pat in raw]


def load_patterns(
    ruleset: Ruleset = "conclusion", path: Optional[Path] = None
) -> list[re.Pattern[str]]:
    """Load simple pattern lists (conclusion / summary)."""
    p = path or blocklist_path()
    data = tomllib.loads(p.read_text(encoding="utf-8"))
    section = "conclusion" if ruleset == "conclusion" else "summary_iron_law"
    if section not in data and ruleset == "conclusion" and "patterns" in data:
        raw = data.get("patterns") or []
    else:
        raw = (data.get(section) or {}).get("patterns") or []
    return _compile_list(raw)


@dataclass
class AttributedViewsConfig:
    always_block: list[re.Pattern[str]]
    conditional_block: list[re.Pattern[str]]
    attribution_allows: list[re.Pattern[str]]


def load_attributed_views(path: Optional[Path] = None) -> AttributedViewsConfig:
    """All exemption / block strings come from config — never hardcode in callers."""
    p = path or blocklist_path()
    data = tomllib.loads(p.read_text(encoding="utf-8"))
    section = data.get("attributed_views") or {}
    return AttributedViewsConfig(
        always_block=_compile_list(section.get("always_block") or []),
        conditional_block=_compile_list(section.get("conditional_block") or []),
        attribution_allows=_compile_list(section.get("attribution_allows") or []),
    )


def _patterns(ruleset: Ruleset) -> list[re.Pattern[str]]:
    key = f"patterns:{ruleset}"
    if key not in _CACHE:
        _CACHE[key] = load_patterns(ruleset)  # type: ignore[arg-type]
    return _CACHE[key]  # type: ignore[return-value]


def _attributed_cfg() -> AttributedViewsConfig:
    if "attributed_views" not in _CACHE:
        _CACHE["attributed_views"] = load_attributed_views()
    return _CACHE["attributed_views"]  # type: ignore[return-value]


def _guard_attributed_views(normalized: str) -> GuardResult:
    cfg = _attributed_cfg()
    matched: list[str] = []
    for pat in cfg.always_block:
        if pat.search(normalized):
            matched.append(pat.pattern)
    attributed = any(a.search(normalized) for a in cfg.attribution_allows)
    for pat in cfg.conditional_block:
        if pat.search(normalized) and not attributed:
            matched.append(pat.pattern)
    return GuardResult(
        ok=len(matched) == 0,
        matched=matched,
        ruleset="attributed_views",
        normalized_text=normalized,
    )


def guard_attributed_field(text: str, *, attributed: bool) -> GuardResult:
    """v1.8 (A1/C2): attribution is decided by a STRUCTURED field, not regex.

    always_block patterns (建议买卖/应该/仓位) are unconditional. conditional_block
    patterns (看多/看空/目标价) pass only when the caller has a non-empty structured
    attribution source (``attributed=True``). This never inspects free text to
    infer whether a view is attributed.
    """
    cfg = _attributed_cfg()
    normalized = normalize_for_guard(text)
    matched: list[str] = []
    for pat in cfg.always_block:
        if pat.search(normalized):
            matched.append(pat.pattern)
    if not attributed:
        for pat in cfg.conditional_block:
            if pat.search(normalized):
                matched.append(pat.pattern)
    return GuardResult(
        ok=len(matched) == 0,
        matched=matched,
        ruleset="attributed_views",
        normalized_text=normalized,
    )


def guard(text: str, ruleset: Ruleset = "conclusion") -> GuardResult:
    """
    ruleset='conclusion': investment-conclusion blacklist (all AI text).
    ruleset='summary': iron law — no impact judgment in card summaries.
    ruleset='attributed_views': narrative scan — attributed 看多/看空 may pass
        per config exemptions; 建议/目标价/应该 always blocked.
    """
    normalized = normalize_for_guard(text)
    if ruleset == "attributed_views":
        return _guard_attributed_views(normalized)

    matched: list[str] = []
    for pat in _patterns(ruleset):
        if pat.search(normalized):
            matched.append(pat.pattern)
    if ruleset == "summary":
        for pat in _patterns("conclusion"):
            if pat.search(normalized) and pat.pattern not in matched:
                matched.append(pat.pattern)
    return GuardResult(
        ok=len(matched) == 0,
        matched=matched,
        ruleset=ruleset,
        normalized_text=normalized,
    )
