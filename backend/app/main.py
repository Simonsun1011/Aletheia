"""FastAPI entrypoint."""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from backend.app.config import get_settings
from backend.app.logging_setup import setup_logging
from backend.app.middleware import RequestIdMiddleware
from backend.app.routers import judgments, notes, watchlist
from backend.app.stores.base import AppStore
from backend.app.stores.sqlite_store import SqliteStore

settings = get_settings()
setup_logging(level=settings.log_level, log_dir=settings.log_dir)


def create_store() -> AppStore:
    s = get_settings()
    store = SqliteStore(s.app_db_path, s.journal_dir)
    store.init_schema()
    return store


@asynccontextmanager
async def lifespan(app: FastAPI):
    store = create_store()
    app.state.store = store
    yield
    if isinstance(store, SqliteStore):
        store.close()


app = FastAPI(title="Aletheia", version="0.1.0", lifespan=lifespan)

# RequestId outermost among our middleware so CORS preflight also gets an id
# when it reaches the app; CORS is added after so it can short-circuit OPTIONS.
app.add_middleware(RequestIdMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(judgments.router, prefix="/api")
app.include_router(notes.router, prefix="/api")
app.include_router(watchlist.router, prefix="/api")


@app.exception_handler(RequestValidationError)
async def validation_handler(request: Request, exc: RequestValidationError):
    return JSONResponse(
        status_code=422,
        content={
            "error": {
                "code": "VALIDATION_ERROR",
                "message": "request validation failed",
                "detail": {"errors": jsonable_encoder(exc.errors())},
            }
        },
    )


@app.get("/api/health")
def health():
    return {"ok": True}
