"""Context self-management: context meter + session scratchpad.

The compaction layer manages the token budget invisibly; this module hands the AGENT the
controls: `context_usage` reports how full the window is (using the same estimator as
compaction, plus the provider-reported usage when available) and `scratchpad_*` gives a
session-scoped, TTL'd working area for "keep this, discard later" notes — separating working
state from durable memory and from deliverables on disk.
"""

from __future__ import annotations

import json
import time
from typing import Any, Optional

import aisuite as ai

from .. import compaction as _compaction

_DEFAULT_TTL_SECONDS = 3600  # scratch notes expire after an hour by default


class Scratchpad:
    def __init__(self, ttl_seconds: int = _DEFAULT_TTL_SECONDS) -> None:
        self._ttl = ttl_seconds
        self._notes: dict[str, dict[str, Any]] = {}

    def _prune(self) -> None:
        now = time.time()
        self._notes = {
            k: v for k, v in self._notes.items() if v.get("expires_at", 0) > now
        }

    def write(self, key: str, value: str, ttl_seconds: Optional[int] = None) -> dict:
        self._prune()
        ttl = ttl_seconds if ttl_seconds is not None else self._ttl
        self._notes[key] = {"value": value, "expires_at": time.time() + ttl}
        return {"ok": True, "key": key, "expires_in": ttl}

    def read(self, key: Optional[str] = None) -> dict:
        self._prune()
        if key is not None:
            note = self._notes.get(key)
            if note is None:
                return {"error": f"no scratchpad note '{key}'"}
            return {"key": key, "value": note["value"]}
        return {
            "keys": [
                {"key": k, "expires_in": int(v["expires_at"] - time.time())}
                for k, v in self._notes.items()
            ]
        }

    def clear(self, key: Optional[str] = None) -> dict:
        if key is not None:
            removed = self._notes.pop(key, None)
            return {"removed": removed is not None, "key": key}
        count = len(self._notes)
        self._notes.clear()
        return {"removed": count}


def context_tools(
    *,
    context_window: Optional[int],
    meter: Optional[Any] = None,
    scratchpad: Optional[Scratchpad] = None,
) -> list:
    """`meter` is a callable returning the current outbound token estimate (the engine's
    `_outbound_messages` + compaction estimator). `context_window` can be a fixed int or a
    callable so a mid-session model switch updates the meter."""
    scratchpad = scratchpad or Scratchpad()

    def _window() -> Optional[int]:
        return context_window() if callable(context_window) else context_window

    def context_usage() -> dict[str, Any]:
        """Report your context-window usage: the estimated/measured prompt tokens, the model's
        window, and how full it is. Use this before starting broad work to decide whether to
        delegate to subagents (delegate/explore/fan_out), compact, or wrap up."""
        used = None
        if meter is not None:
            try:
                used = int(meter())
            except Exception:
                used = None
        window = _window()
        if used is None:
            used = _compaction.estimate_tokens([])  # 0-safe fallback
        return {
            "estimated_prompt_tokens": used,
            "context_window": window,
            "pct_used": round(100.0 * used / window, 1) if window else None,
            "advice": (
                "delegate" if window and used > 0.6 * window else "ok"
            ),
        }

    def scratchpad_write(key: str, value: str, ttl_seconds: Optional[int] = None) -> dict:
        """Save a short-lived working note (expires after `ttl_seconds`, default 1h). Use for
        mid-task state you'll want later but that shouldn't become durable memory. Returns ok."""
        return scratchpad.write(key, value, ttl_seconds)

    def scratchpad_read(key: Optional[str] = None) -> dict:
        """Read a scratch note by key, or list all live notes when no key is given."""
        return scratchpad.read(key)

    def scratchpad_clear(key: Optional[str] = None) -> dict:
        """Delete a scratch note (all of them when no key is given)."""
        return scratchpad.clear(key)

    def _wrap(fn, name, doc):
        fn.__name__ = name
        fn.__doc__ = doc
        return ai.tool(
            fn,
            metadata=ai.ToolMetadata(
                name=name,
                category="context",
                risk_level="low",
                capabilities=["context"],
                requires_approval=False,
            ),
        )

    return [
        _wrap(context_usage, "context_usage", context_usage.__doc__),
        _wrap(scratchpad_write, "scratchpad_write", scratchpad_write.__doc__),
        _wrap(scratchpad_read, "scratchpad_read", scratchpad_read.__doc__),
        _wrap(scratchpad_clear, "scratchpad_clear", scratchpad_clear.__doc__),
    ]