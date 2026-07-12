"""Cloud offsite mirror — DESIGN v0.4 one-way append after local write succeeds.

Full Firestore AppStore is separate (`firestore_store.py`). This module is the
lighter backup path that can ship before a complete second Store.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Optional

log = logging.getLogger("aletheia.store")

# Irreversible / personal data that v0.4 says must leave the machine somehow.
MIRROR_TABLES = frozenset(
    {
        "judgment_entries",
        "quick_notes",
        "executions",
        "watchlist",
    }
)


@dataclass(frozen=True)
class CloudMirrorStatus:
    backend: str  # off | firestore | …
    enabled: bool
    configured: bool
    detail: str


class CloudMirror(ABC):
    """One-way push of a row already persisted locally. Never blocks durability."""

    @abstractmethod
    def status(self) -> CloudMirrorStatus:
        ...

    @abstractmethod
    def push(self, table: str, row: dict[str, Any]) -> bool:
        """
        Best-effort mirror. Return True if accepted/queued, False if skipped.
        Must NOT raise into callers on transport failure (log + return False).
        """
        ...


class NullCloudMirror(CloudMirror):
    """Default: local-only. No network."""

    def status(self) -> CloudMirrorStatus:
        return CloudMirrorStatus(
            backend="off",
            enabled=False,
            configured=False,
            detail="cloud mirror disabled (ALETHEIA_CLOUD_MIRROR=off)",
        )

    def push(self, table: str, row: dict[str, Any]) -> bool:
        return False


class FirestoreCloudMirror(CloudMirror):
    """
    Stub for Firestore backup mirror.

    Until credentials + firebase-admin are configured, push() is a no-op and
    status().configured is False. Real SDK wiring belongs in a later pass —
    do not import firebase_admin here until that day (keeps requirements light).
    """

    def __init__(
        self,
        *,
        project_id: Optional[str] = None,
        credentials_path: Optional[str] = None,
    ) -> None:
        self.project_id = (project_id or "").strip() or None
        self.credentials_path = (credentials_path or "").strip() or None
        self._warned = False

    def status(self) -> CloudMirrorStatus:
        configured = bool(self.project_id and self.credentials_path)
        if not configured:
            detail = (
                "ALETHEIA_CLOUD_MIRROR=firestore but FIREBASE_PROJECT_ID / "
                "GOOGLE_APPLICATION_CREDENTIALS not set — push is no-op"
            )
        else:
            detail = (
                "credentials present; SDK write path not implemented yet "
                "(stub — will no-op until wired)"
            )
        return CloudMirrorStatus(
            backend="firestore",
            enabled=True,
            configured=configured,
            detail=detail,
        )

    def push(self, table: str, row: dict[str, Any]) -> bool:
        if table not in MIRROR_TABLES:
            return False
        st = self.status()
        if not st.configured:
            if not self._warned:
                log.warning("firestore mirror not configured; skips pushes")
                self._warned = True
            return False
        # Intentionally unimplemented: avoid accidental network / secret use.
        if not self._warned:
            log.warning(
                "firestore mirror stub: push skipped (SDK not wired) table=%s id=%s",
                table,
                row.get("id") or row.get("ticker"),
            )
            self._warned = True
        return False
