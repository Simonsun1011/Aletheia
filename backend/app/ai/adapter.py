"""LiteLLM adapter — model names and keys from env only.

v1.8 A4: zero persistence dependency. Usage recording / budget checks go through
assembly-injected callbacks (wired in main lifespan to ai.usage helpers).
"""

from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Literal, Optional

from backend.app.config import REPO_ROOT

log = logging.getLogger("aletheia.ai")

PROMPTS_DIR = Path(__file__).resolve().parent / "prompts"

Purpose = Literal["summary", "promote", "scan", "other"]
BudgetMode = Literal["batch", "interactive"]

RecordUsageFn = Callable[..., dict]
BudgetStatusFn = Callable[[], tuple[bool, Optional[str]]]
AssertBatchFn = Callable[[], None]

_record_usage: Optional[RecordUsageFn] = None
_budget_status: Optional[BudgetStatusFn] = None
_assert_batch: Optional[AssertBatchFn] = None


@dataclass
class CompletionResult:
    text: str
    model: str
    prompt_version: str
    elapsed_ms: float
    prompt_tokens: Optional[int] = None
    completion_tokens: Optional[int] = None
    budget_warning: Optional[str] = None


class AdapterError(Exception):
    pass


def configure_usage_hooks(
    *,
    record_usage: Optional[RecordUsageFn] = None,
    budget_status: Optional[BudgetStatusFn] = None,
    assert_batch_budget_allows: Optional[AssertBatchFn] = None,
) -> None:
    """Assembly layer injects persistence/budget callbacks — adapter never holds Store."""
    global _record_usage, _budget_status, _assert_batch
    _record_usage = record_usage
    _budget_status = budget_status
    _assert_batch = assert_batch_budget_allows


def reset_usage_hooks() -> None:
    configure_usage_hooks(
        record_usage=None,
        budget_status=None,
        assert_batch_budget_allows=None,
    )


def load_prompt(filename: str) -> str:
    path = PROMPTS_DIR / filename
    if not path.exists():
        raise AdapterError(f"prompt file missing: {filename}")
    return path.read_text(encoding="utf-8")


def complete(
    *,
    prompt_file: str,
    user_content: str,
    model: Optional[str] = None,
    timeout_s: float = 60.0,
    retries: int = 1,
    purpose: Purpose = "other",
    budget_mode: BudgetMode = "interactive",
    system_override: Optional[str] = None,
) -> CompletionResult:
    """
    Call LLM via LiteLLM. Model from MODEL_SUMMARY env unless overridden.
    Records usage via injected callback on success. Batch mode raises if budget exceeded.
    system_override: if set, use instead of loading prompt_file (prompt_file still recorded as version).
    """
    model_name = model or os.getenv("MODEL_SUMMARY")
    if not model_name:
        raise AdapterError("MODEL_SUMMARY is not set")

    budget_warning: Optional[str] = None
    if _budget_status is not None:
        over, msg = _budget_status()
        if over:
            if budget_mode == "batch":
                if _assert_batch is not None:
                    _assert_batch()
                else:
                    raise AdapterError(msg or "LLM budget exceeded")
            else:
                budget_warning = msg

    system = system_override if system_override is not None else load_prompt(prompt_file)
    import litellm

    litellm.drop_params = True
    last_err: Exception | None = None
    attempts = 1 + max(0, retries)
    for attempt in range(attempts):
        started = time.perf_counter()
        try:
            resp = litellm.completion(
                model=model_name,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user_content},
                ],
                timeout=timeout_s,
            )
            elapsed_ms = (time.perf_counter() - started) * 1000
            text = resp.choices[0].message.content or ""
            usage = getattr(resp, "usage", None)
            pt = getattr(usage, "prompt_tokens", None) if usage else None
            ct = getattr(usage, "completion_tokens", None) if usage else None
            log.info(
                "llm ok model=%s prompt=%s purpose=%s elapsed_ms=%.0f tokens_in=%s tokens_out=%s",
                model_name,
                prompt_file,
                purpose,
                elapsed_ms,
                pt,
                ct,
            )
            log.debug("llm prompt_file=%s user=%s", prompt_file, user_content[:500])
            log.debug("llm response=%s", text[:2000])
            if _record_usage is not None:
                try:
                    _record_usage(
                        model=model_name,
                        purpose=purpose,
                        prompt_version=prompt_file,
                        tokens_in=pt,
                        tokens_out=ct,
                        elapsed_ms=elapsed_ms,
                    )
                except Exception as e:
                    log.warning("llm_usage record failed: %s", type(e).__name__)
            return CompletionResult(
                text=text,
                model=model_name,
                prompt_version=prompt_file,
                elapsed_ms=elapsed_ms,
                prompt_tokens=pt,
                completion_tokens=ct,
                budget_warning=budget_warning,
            )
        except Exception as e:
            last_err = e
            log.warning(
                "llm attempt %s/%s failed model=%s err=%s",
                attempt + 1,
                attempts,
                model_name,
                type(e).__name__,
            )
            if attempt + 1 >= attempts:
                break
    log.error("llm exhausted retries model=%s", model_name)
    raise AdapterError(str(last_err) if last_err else "llm failed")


class SearchModelNotConfigured(AdapterError):
    """MODEL_SEARCH missing — do not silently fall back to a non-search model."""

    code = "SEARCH_MODEL_NOT_CONFIGURED"


def call_with_search(
    *,
    prompt_file: str,
    user_content: str,
    model: Optional[str] = None,
    timeout_s: float = 120.0,
    retries: int = 1,
    purpose: Purpose = "scan",
    budget_mode: BudgetMode = "interactive",
) -> CompletionResult:
    """
    Search-capable completion. Requires MODEL_SEARCH in env.
    Never falls back to MODEL_SUMMARY (would invent sources).
    """
    model_name = model or os.getenv("MODEL_SEARCH")
    if not model_name or not str(model_name).strip():
        raise SearchModelNotConfigured(
            "MODEL_SEARCH is not set; refuse to run narrative scan without search"
        )
    return complete(
        prompt_file=prompt_file,
        user_content=user_content,
        model=model_name,
        timeout_s=timeout_s,
        retries=retries,
        purpose=purpose,
        budget_mode=budget_mode,
    )


_ = REPO_ROOT
