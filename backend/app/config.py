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
    return Settings(
        app_db_path=Path(db),
        journal_dir=Path(journal),
        cors_origins=[o.strip() for o in origins.split(",") if o.strip()],
        log_level=log_level,
        log_dir=Path(log_dir),
        market_db_path=Path(market_db),
    )
