"""Optional small-model triage before priority sort (Slice 3c).

Protocol: triage(title, lede) -> 0|1|2 importance.
Default: no-op stub (always 0). Real model only when DIGEST_TRIAGE_MODEL is set —
this slice ships the stub only (DESIGN: 留接口、默认关).
"""

from __future__ import annotations

import os
from typing import Protocol


class TriageFn(Protocol):
    def __call__(self, title: str, lede: str) -> int: ...


def triage_configured() -> bool:
    return bool(os.environ.get("DIGEST_TRIAGE_MODEL", "").strip())


def triage(title: str, lede: str) -> int:
    """Return 0|1|2. Stub always 0 unless a future adapter is wired."""
    if not triage_configured():
        return 0
    # Placeholder: env set but no adapter yet → still no-op (do not call LLM).
    return 0


def get_triage_fn() -> TriageFn:
    return triage
