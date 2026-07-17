"""Shared TestClient defaults for TrustedHost + X-Aletheia-Client (slice-11 A2)."""

from __future__ import annotations

from fastapi.testclient import TestClient

from backend.app.main import app

TEST_CLIENT_BASE_URL = "http://127.0.0.1"
TEST_CLIENT_HEADERS = {"X-Aletheia-Client": "1"}


def make_test_client(**kwargs) -> TestClient:
    headers = {**TEST_CLIENT_HEADERS, **(kwargs.pop("headers", None) or {})}
    return TestClient(
        app,
        base_url=kwargs.pop("base_url", TEST_CLIENT_BASE_URL),
        headers=headers,
        **kwargs,
    )
