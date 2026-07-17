"""FastAPI entrypoint."""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from backend.app.config import get_settings
from backend.app.logging_setup import get_request_id, setup_logging
from backend.app.middleware import RequestIdMiddleware, RequireClientHeaderMiddleware
from backend.app.routers import (
    changefeed,
    cloud,
    console,
    diagnostics,
    executions,
    feed,
    glossary,
    judgments,
    meta,
    notes,
    reviews,
    status_router,
    tags,
    tickers,
    usage,
    watchlist,
)
from backend.app.stores.base import AppStore
from backend.app.stores.factory import create_app_store
from backend.app.stores.sqlite_store import SqliteStore

settings = get_settings()
setup_logging(level=settings.log_level, log_dir=settings.log_dir)


def create_store() -> AppStore:
    return create_app_store(get_settings())


@asynccontextmanager
async def lifespan(app: FastAPI):
    from backend.app.ai import adapter as ai_adapter
    from backend.app.ai import usage as llm_usage

    store = create_store()
    app.state.store = store
    # v1.8 A4: wire Store into usage module; adapter gets callbacks only (no Store)
    llm_usage.wire_llm_usage(store)
    yield
    ai_adapter.reset_usage_hooks()
    llm_usage.clear_store()
    if isinstance(store, SqliteStore):
        store.close()


app = FastAPI(title="Aletheia", version="0.1.0", lifespan=lifespan)

# Last added = outermost. TrustedHost → CORS → client header → request id → routes.
app.add_middleware(RequestIdMiddleware)
app.add_middleware(RequireClientHeaderMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(
    TrustedHostMiddleware,
    allowed_hosts=["127.0.0.1", "localhost"],
)

app.include_router(judgments.router, prefix="/api")
app.include_router(notes.router, prefix="/api")
app.include_router(watchlist.router, prefix="/api")
app.include_router(tickers.router, prefix="/api")
app.include_router(changefeed.router, prefix="/api")
app.include_router(feed.router, prefix="/api")
app.include_router(tags.router, prefix="/api")
app.include_router(console.router, prefix="/api")
app.include_router(glossary.router, prefix="/api")
app.include_router(meta.router, prefix="/api")
app.include_router(usage.router, prefix="/api")
app.include_router(executions.router, prefix="/api")
app.include_router(reviews.router, prefix="/api")
app.include_router(cloud.router, prefix="/api")
app.include_router(status_router.router, prefix="/api")
app.include_router(diagnostics.router, prefix="/api")


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    """Flatten to contract §1 envelope (routers raise detail={"error": ...})."""
    detail = exc.detail
    if isinstance(detail, dict) and "error" in detail:
        return JSONResponse(status_code=exc.status_code, content=detail)
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": {
                "code": f"HTTP_{exc.status_code}",
                "message": str(detail),
                "detail": {},
            }
        },
    )


@app.exception_handler(RequestValidationError)
async def validation_handler(request: Request, exc: RequestValidationError):
    return JSONResponse(
        status_code=422,
        content={
            "error": {
                "code": "VALIDATION_ERROR",
                "message": "request validation failed",
                "request_id": get_request_id(),
                "detail": {"errors": jsonable_encoder(exc.errors())},
            }
        },
    )


@app.exception_handler(Exception)
async def generic_exception_handler(request: Request, exc: Exception):
    return JSONResponse(
        status_code=500,
        content={
            "error": {
                "code": "INTERNAL_ERROR",
                "message": "internal server error",
                "request_id": get_request_id(),
            }
        },
    )


@app.get("/api/health")
async def health():
    return {"ok": True}
