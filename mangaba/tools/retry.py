"""Tool failure classification + bounded auto-retry.

When a tool execution raises, the engine currently appends a generic error message and lets
the model react. This module classifies the failure so the ENGINE can retry the cheap,
transient ones itself (rate-limit, timeout, connection reset) with backoff — instead of
burning a model iteration on "run that again" — and only surfaces permanent failures as
tool errors with a structured reason the model can act on.
"""

from __future__ import annotations

import re
import time
from typing import Any, Callable, Optional

# Transient: worth retrying with backoff — a rate-limit or flaky connection usually clears.
_TRANSIENT_PATTERNS = [
    re.compile(r"rate\s*limit", re.I),
    re.compile(r"429\b"),
    re.compile(r"timeout", re.I),
    re.compile(r"timed\s*out", re.I),
    re.compile(r"connection\s*(reset|refused|aborted|closed)", re.I),
    re.compile(r"temporarily", re.I),
    re.compile(r"try again later", re.I),
    re.compile(r"network\s*error", re.I),
    re.compile(r"503\b"),
]

# Permanent: retrying would not change the outcome.
_PERMANENT_PATTERNS = [
    re.compile(r"permission\s*denied", re.I),
    re.compile(r"authentication?.*(fail|invalid|expired)", re.I),
    re.compile(r"not found", re.I),
    re.compile(r"does not exist", re.I),
    re.compile(r"invalid\s*(argument|syntax)", re.I),
    re.compile(r"validation\s*error", re.I),
]

_DEFAULT_MAX_RETRIES = 2
_DEFAULT_BACKOFF_BASE = 0.4


def classify_error(error: Any) -> str:
    """Return 'transient', 'permanent' or 'unknown' for an exception/message."""
    text = str(error)
    for pattern in _PERMANENT_PATTERNS:
        if pattern.search(text):
            return "permanent"
    for pattern in _TRANSIENT_PATTERNS:
        if pattern.search(text):
            return "transient"
    return "unknown"


def retry_execute(
    fn: Callable[[], Any],
    *,
    max_retries: int = _DEFAULT_MAX_RETRIES,
    backoff_base: float = _DEFAULT_BACKOFF_BASE,
) -> tuple[Any, str, int]:
    """Run `fn`; on transient/unknown failures retry with exponential backoff up to
    `max_retries` extra attempts. Returns (result, status, attempts). Permanent failures
    never retry. `fn` may raise; the last exception is returned as the result with an
    'error' marker and status 'error'."""
    attempts = 0
    for attempt in range(max_retries + 1):
        attempts += 1
        try:
            return fn(), "ok", attempts
        except Exception as exc:  # noqa: BLE001 - we own the surface
            kind = classify_error(exc)
            if kind == "permanent" or attempt >= max_retries:
                return (
                    {
                        "error": str(exc),
                        "error_type": type(exc).__name__,
                        "retry": kind,
                    },
                    "error",
                    attempts,
                )
            time.sleep(backoff_base * (2 ** attempt))
    raise AssertionError("unreachable")


class ToolRetryPolicy:
    """Per-tool retry policy holder — lets the engine ask 'should this tool auto-retry?'
    while keeping the policy data-driven (tools can opt out via metadata)."""

    def __init__(
        self,
        max_retries: int = _DEFAULT_MAX_RETRIES,
        retryable: Optional[set[str]] = None,
    ) -> None:
        self.max_retries = max_retries
        self.retryable = retryable  # None → all tools eligible; a set restricts by name

    def allowed(self, tool_name: str) -> bool:
        return self.retryable is None or tool_name in self.retryable