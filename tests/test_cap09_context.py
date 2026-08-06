"""Capability #9 — context self-management: context meter + scratchpad."""

from __future__ import annotations

import time

from mangaba.tools import ToolRegistry
from mangaba.tools.context import Scratchpad, context_tools


def test_context_usage_reports_pct(tmp_path):
    reg = ToolRegistry()
    reg.register_all(
        context_tools(
            context_window=100_000,
            meter=lambda: 40_000,
        )
    )
    res = reg.execute("context_usage", {})
    assert res["estimated_prompt_tokens"] == 40_000
    assert res["context_window"] == 100_000
    assert res["pct_used"] == 40.0
    assert res["advice"] == "ok"


def test_context_usage_advises_delegate_above_threshold():
    reg = ToolRegistry()
    reg.register_all(
        context_tools(context_window=100_000, meter=lambda: 70_000)
    )
    assert reg.execute("context_usage", {})["advice"] == "delegate"


def test_context_usage_supports_live_window():
    window = {"v": 50_000}
    reg = ToolRegistry()
    reg.register_all(context_tools(context_window=lambda: window["v"], meter=lambda: 5_000))
    assert reg.execute("context_usage", {})["context_window"] == 50_000
    window["v"] = 90_000
    assert reg.execute("context_usage", {})["context_window"] == 90_000


def test_scratchpad_roundtrip():
    scratch = Scratchpad(ttl_seconds=3600)
    reg = ToolRegistry()
    reg.register_all(context_tools(context_window=1_000, meter=lambda: 1, scratchpad=scratch))
    reg.execute("scratchpad_write", {"key": "mid", "value": "nota temporária"})
    assert reg.execute("scratchpad_read", {"key": "mid"})["value"] == "nota temporária"
    keys = reg.execute("scratchpad_read", {})["keys"]
    assert any(k["key"] == "mid" for k in keys)


def test_scratchpad_ttl_expiry():
    scratch = Scratchpad(ttl_seconds=1)
    reg = ToolRegistry()
    reg.register_all(context_tools(context_window=1_000, meter=lambda: 1, scratchpad=scratch))
    reg.execute("scratchpad_write", {"key": "x", "value": "v"})
    time.sleep(1.05)
    assert "error" in reg.execute("scratchpad_read", {"key": "x"})


def test_scratchpad_clear():
    scratch = Scratchpad()
    reg = ToolRegistry()
    reg.register_all(context_tools(context_window=1_000, meter=lambda: 1, scratchpad=scratch))
    reg.execute("scratchpad_write", {"key": "a", "value": "1"})
    reg.execute("scratchpad_write", {"key": "b", "value": "2"})
    assert reg.execute("scratchpad_clear", {})["removed"] == 2
    assert reg.execute("scratchpad_read", {})["keys"] == []