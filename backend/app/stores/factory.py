"""Store / cloud-mirror factory — sole place allowed to pick concrete backends."""

from __future__ import annotations

from backend.app.config import Settings, get_settings
from backend.app.stores.base import AppStore
from backend.app.stores.cloud_mirror import (
    CloudMirror,
    FirestoreCloudMirror,
    NullCloudMirror,
)
from backend.app.stores.firestore_store import FirestoreStore
from backend.app.stores.sqlite_store import SqliteStore


def create_cloud_mirror(settings: Settings | None = None) -> CloudMirror:
    s = settings or get_settings()
    backend = (s.cloud_mirror or "off").strip().lower()
    if backend in ("", "off", "none", "null"):
        return NullCloudMirror()
    if backend == "firestore":
        return FirestoreCloudMirror(
            project_id=s.firebase_project_id,
            credentials_path=s.google_application_credentials,
        )
    raise ValueError(f"unknown ALETHEIA_CLOUD_MIRROR={backend!r} (use off|firestore)")


def create_app_store(settings: Settings | None = None) -> AppStore:
    """
    Construct the primary AppStore.

    Business routers must receive AppStore via DI — never import SqliteStore /
    FirestoreStore directly.
    """
    s = settings or get_settings()
    backend = (s.store_backend or "sqlite").strip().lower()
    mirror = create_cloud_mirror(s)

    if backend == "sqlite":
        store = SqliteStore(s.app_db_path, s.journal_dir, cloud_mirror=mirror)
        store.init_schema()
        return store

    if backend == "firestore":
        # Stub only — usable for status experiments; writes will raise.
        return FirestoreStore(
            project_id=s.firebase_project_id,
            credentials_path=s.google_application_credentials,
        )

    raise ValueError(f"unknown ALETHEIA_STORE={backend!r} (use sqlite|firestore)")
