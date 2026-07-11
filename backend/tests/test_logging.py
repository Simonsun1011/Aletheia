"""Logging system tests — architecture.md §6.5 / slice-01 item 7."""

from __future__ import annotations

import logging

import pytest

from backend.app.logging_setup import (
    get_request_id,
    reset_logging_for_tests,
    set_request_id,
    setup_logging,
)
from backend.app.models import JudgmentCreate

VALID = {
    "object": "AMAT",
    "jtype": "action",
    "direction": "outperform",
    "horizon_days": 40,
    "confidence": 0.6,
    "text": "原话",
}


@pytest.fixture(autouse=True)
def _isolate_logging(tmp_path_factory):
    """Each test gets a fresh logging config; tear down after."""
    yield
    reset_logging_for_tests()


def test_setup_writes_rotating_file(tmp_path):
    reset_logging_for_tests()
    setup_logging(level="DEBUG", log_dir=tmp_path, console=False)
    set_request_id("01TESTREQUESTID000000000000")
    log = logging.getLogger("aletheia.api")
    log.info("hello from test")
    for h in logging.getLogger("aletheia").handlers:
        h.flush()
    text = (tmp_path / "aletheia.log").read_text(encoding="utf-8")
    assert "aletheia.api" in text
    assert "01TESTREQUESTID000000000000" in text
    assert "hello from test" in text
    assert " | " in text


def test_request_id_header_on_response(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.headers.get("X-Request-ID")


def test_append_only_405_logs_warning(client, tmp_path):
    reset_logging_for_tests()
    setup_logging(level="DEBUG", log_dir=tmp_path, console=False)
    created = client.post("/api/judgments", json=VALID).json()
    r = client.delete(f"/api/judgments/{created['root_id']}")
    assert r.status_code == 405
    for h in logging.getLogger("aletheia").handlers:
        h.flush()
    text = (tmp_path / "aletheia.log").read_text(encoding="utf-8")
    assert "append-only rejection" in text
    assert "WARNING" in text
    assert "aletheia.store" in text


def test_sqlite_trigger_logs_warning(store, tmp_path):
    reset_logging_for_tests()
    setup_logging(level="DEBUG", log_dir=tmp_path, console=False)
    entry = store.create_judgment(JudgmentCreate(**VALID))
    with pytest.raises(Exception):
        store._execute(
            "UPDATE judgment_entries SET text = ? WHERE id = ?",
            ("x", entry.id),
        )
    for h in logging.getLogger("aletheia").handlers:
        h.flush()
    text = (tmp_path / "aletheia.log").read_text(encoding="utf-8")
    assert "append-only rejection via SQLite trigger" in text
    assert "WARNING" in text


def test_request_id_context_default():
    set_request_id("-")
    assert get_request_id() == "-"
