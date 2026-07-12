"""Cloud / Firestore status — scaffold only; no secrets in responses."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from backend.app.config import get_settings
from backend.app.stores.factory import create_cloud_mirror

router = APIRouter(prefix="/cloud", tags=["cloud"])


@router.get("/status")
def cloud_status() -> dict[str, Any]:
    """
    Report store + mirror backend selection.

    Never returns credential paths or key material — only booleans / labels.
    """
    s = get_settings()
    mirror = create_cloud_mirror(s)
    st = mirror.status()
    return {
        "store_backend": (s.store_backend or "sqlite").lower(),
        "cloud_mirror": {
            "backend": st.backend,
            "enabled": st.enabled,
            "configured": st.configured,
            "detail": st.detail,
        },
        "firebase_project_set": bool(s.firebase_project_id),
        "credentials_path_set": bool(s.google_application_credentials),
    }
