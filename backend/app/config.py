"""Load paths and settings from environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

# Repo root: backend/app/config.py → parents[2]
REPO_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(REPO_ROOT / ".env")


@dataclass(frozen=True)
class Settings:
    app_db_path: Path
    journal_dir: Path
    cors_origins: list[str]
    log_level: str
    log_dir: Path
    market_db_path: Path
    store_backend: str = "sqlite"
    cloud_mirror: str = "off"
    firebase_project_id: str | None = None
    google_application_credentials: str | None = None
    # Slice 7：Obsidian vault 导出目录（绝对路径，可含空格；未配置则导出禁用）
    obsidian_export_dir: str | None = None


def get_settings() -> Settings:
    db = os.getenv("ALETHEIA_APP_DB", str(REPO_ROOT / "data" / "app.db"))
    journal = os.getenv("ALETHEIA_JOURNAL_DIR", str(REPO_ROOT / "data" / "journal"))
    origins = os.getenv(
        "ALETHEIA_CORS_ORIGINS",
        "http://localhost:3000,http://127.0.0.1:3000",
    )
    log_level = os.getenv("ALETHEIA_LOG_LEVEL", "INFO")
    log_dir = os.getenv("ALETHEIA_LOG_DIR", str(REPO_ROOT / "logs"))
    market_db = os.getenv(
        "ALETHEIA_MARKET_DB",
        str(REPO_ROOT / "data" / "market" / "market_data.db"),
    )
    store_backend = os.getenv("ALETHEIA_STORE", "sqlite")
    cloud_mirror = os.getenv("ALETHEIA_CLOUD_MIRROR", "off")
    firebase_project_id = os.getenv("FIREBASE_PROJECT_ID") or None
    gac = os.getenv("GOOGLE_APPLICATION_CREDENTIALS") or None
    # 勿 split：路径可含空格（Obsidian Vault）
    obsidian = os.getenv("OBSIDIAN_EXPORT_DIR")
    obsidian = obsidian.strip() if obsidian else None
    return Settings(
        app_db_path=Path(db),
        journal_dir=Path(journal),
        cors_origins=[o.strip() for o in origins.split(",") if o.strip()],
        log_level=log_level,
        log_dir=Path(log_dir),
        market_db_path=Path(market_db),
        store_backend=store_backend,
        cloud_mirror=cloud_mirror,
        firebase_project_id=firebase_project_id,
        google_application_credentials=gac,
        obsidian_export_dir=obsidian or None,
    )
