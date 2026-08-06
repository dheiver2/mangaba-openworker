"""Capability #10 — long-horizon continuity: living brief + session summaries."""

from __future__ import annotations

from mangaba.brief import (
    BriefStore,
    SessionBrief,
    brief_block,
    brief_tools,
    summarize_session,
)
from mangaba.tools import ToolRegistry


def test_brief_store_persists(tmp_path):
    store = BriefStore(tmp_path / "briefs")
    store.update("/proj", objective="Entregar o dossiê", decisive=[], open_threads=["revisar capítulo 3"])
    brief = store.get("/proj")
    assert brief.objective == "Entregar o dossiê"
    # Round-trip via a fresh store instance reads from disk.
    store2 = BriefStore(tmp_path / "briefs")
    assert store2.get("/proj").open_threads == ["revisar capítulo 3"]


def test_brief_block_includes_fields():
    b = SessionBrief(objective="Objetivo", decisions=["usar auth JWT"], open_threads=["revisar"], last_summary="travei no cap 2")
    block = brief_block(b)
    assert "Objetivo" in block and "auth JWT" in block and "cap 2" in block


def test_summarize_session_uses_last_assistant_text():
    messages = [
        {"role": "assistant", "content": "primeira entrega"},
        {"role": "user", "content": "ok"},
        {"role": "assistant", "content": "entreguei o relatório do capítulo", "tool_calls": []},
    ]
    assert "relatório do capítulo" in summarize_session(messages)


def test_summarize_skips_tool_turn():
    messages = [
        {"role": "assistant", "content": "", "tool_calls": [{"id": "c1"}]},
        {"role": "assistant", "content": "por fim, fechei", "tool_calls": []},
    ]
    assert summarize_session(messages) == "por fim, fechei"


def test_brief_tools_end_writes_summary(tmp_path):
    store = BriefStore(tmp_path / "briefs")
    reg = ToolRegistry()
    reg.register_all(brief_tools(store, "/proj"))
    assert reg.execute("brief_end", {"summary": "concluído parcial"})["ok"] is True
    assert store.get("/proj").last_summary == "concluído parcial"


def test_brief_write_sets_objective(tmp_path):
    store = BriefStore(tmp_path / "briefs")
    reg = ToolRegistry()
    reg.register_all(brief_tools(store, "/proj"))
    reg.execute("brief_write", {"objective": "novo projeto X"})
    assert store.get("/proj").objective == "novo projeto X"