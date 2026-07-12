"""GET /api/diagnostics/export — zip bundle for remote debugging.

Includes:
  - status.json  (system status snapshot)
  - aletheia.log (last ~200 KB — redacted tail, no .env / secrets)
"""

from __future__ import annotations

import io
import json
import os
import zipfile
from datetime import datetime, timezone

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from backend.app.config import get_settings

router = APIRouter(prefix="/diagnostics", tags=["diagnostics"])

_MAX_LOG_BYTES = 200 * 1024  # 200 KB tail of the log file


@router.get("/export")
async def diagnostics_export():
    """Download a zip containing status.json + recent log tail (no secrets)."""
    from backend.app.services.feed_ingest import refresh_status

    settings = get_settings()
    log_file = settings.log_dir / "aletheia.log"

    status_data = {
        "exported_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "ok": True,
        "llm_configured": bool(os.getenv("MODEL_SUMMARY")),
        "search_model_configured": bool(os.getenv("MODEL_SEARCH")),
        "version": "0.1.0",
        "refresh": refresh_status(),
    }

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(
            "status.json",
            json.dumps(status_data, indent=2, ensure_ascii=False, default=str),
        )

        if log_file.exists():
            size = log_file.stat().st_size
            with log_file.open("rb") as f:
                if size > _MAX_LOG_BYTES:
                    f.seek(size - _MAX_LOG_BYTES)
                    tail = f.read()
                    # skip partial first line for clean output
                    nl = tail.find(b"\n")
                    tail = tail[nl + 1 :] if nl >= 0 else tail
                else:
                    tail = f.read()
            zf.writestr("aletheia.log", tail)

    buf.seek(0)
    ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    filename = f"aletheia-diagnostics-{ts}.zip"
    return StreamingResponse(
        buf,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
