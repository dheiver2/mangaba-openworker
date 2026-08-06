"""Capability #5 — tool failure classification + bounded auto-retry."""

from __future__ import annotations

from mangaba.tools.retry import (
    ToolRetryPolicy,
    classify_error,
    retry_execute,
)


def test_classify_transient():
    assert classify_error("HTTP 429 too many requests") == "transient"
    assert classify_error("Connection reset by peer") == "transient"
    assert classify_error("request timed out after 30s") == "transient"
    assert classify_error("temporarily unavailable, try again later") == "transient"


def test_classify_permanent():
    assert classify_error("permission denied") == "permanent"
    assert classify_error("authentication failed: invalid key") == "permanent"
    assert classify_error("file not found") == "permanent"


def test_classify_unknown():
    assert classify_error("some weird problem") == "unknown"


def test_retry_transient_succeeds_after_failures():
    calls = []

    def flaky():
        calls.append(1)
        if len(calls) < 3:
            raise RuntimeError("429 rate limit")
        return "done"

    result, status, attempts = retry_execute(flaky, max_retries=3, backoff_base=0.0)
    assert status == "ok" and result == "done"
    assert attempts == 3  # 2 failed + 1 success
    assert len(calls) == 3


def test_retry_gives_up_on_transient():
    calls = []

    def always_limits():
        calls.append(1)
        raise RuntimeError("429 rate limit")

    result, status, attempts = retry_execute(always_limits, max_retries=2, backoff_base=0.0)
    assert status == "error"
    assert attempts == 3  # initial + 2 retries
    assert "429" in result["error"]


def test_retry_never_retries_permanent():
    def denied():
        raise PermissionError("permission denied")

    result, status, attempts = retry_execute(denied, max_retries=3, backoff_base=0.0)
    assert status == "error" and attempts == 1
    assert result["retry"] == "permanent"


def test_policy_allows_all_by_default():
    policy = ToolRetryPolicy()
    assert policy.allowed("anything") is True


def test_policy_can_restrict_by_tool():
    policy = ToolRetryPolicy(retryable={"search"})
    assert policy.allowed("search") is True
    assert policy.allowed("shell") is False