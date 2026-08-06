"""Capability #8 — skill allowed_tools sandbox enforcement."""

from __future__ import annotations

import json

import pytest

from mangaba.engine import TurnEngine
from mangaba.events import EventType
from mangaba.providers import (
    AssistantTurn,
    ModelCapabilities,
    ProviderClient,
    ToolCall,
)
from mangaba.skills.base import SkillLoader
from mangaba.tools import ToolRegistry


class _ToolTurnProvider(ProviderClient):
    """Emits one tool call, then a final text turn."""

    def __init__(self, calls):
        self._calls = list(calls)
        self._final = False

    def complete(self, *, model, messages, tools=None, **settings):
        if self._final or not self._calls:
            self._final = True
            return AssistantTurn(text="pronto", finish_reason="stop")
        return AssistantTurn(
            tool_calls=[ToolCall(id="c1", name=self._calls.pop(0), arguments={})],
            finish_reason="tool_calls",
        )

    def capabilities(self, model):
        return ModelCapabilities()


def _make_skill_engine(tmp_path, allowed_tools):
    skills_dir = tmp_path / "skills"
    d = skills_dir / "sandbox"
    d.mkdir(parents=True)
    (d / "SKILL.md").write_text(
        "---\nname: sandbox\ndescription: restricted skill\n"
        f"allowed-tools: {', '.join(allowed_tools)}\n---\n\nExecute only within the sandbox.",
        encoding="utf-8",
    )
    loader = SkillLoader([skills_dir])
    engine = TurnEngine(
        provider=_ToolTurnProvider(["load_skill", "read_file"]),
        registry=ToolRegistry(),
        permissions=None,
        model="gpt-5.5",
    )
    engine.skill_loader = loader  # type: ignore[attr-defined]
    return engine


@pytest.mark.asyncio
async def test_skill_restriction_for_denies_disallowed_tool(tmp_path):
    engine = _make_skill_engine(tmp_path, ["grep"])
    # Simulate the skill having been loaded this conversation.
    engine.messages.append(
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {"id": "load1", "type": "function",
                 "function": {"name": "load_skill", "arguments": json.dumps({"name": "sandbox"})}}
            ],
        }
    )
    engine.messages.append(
        {"role": "tool", "tool_call_id": "load1", "content": json.dumps({"instructions": "do x"})}
    )
    assert engine._loaded_skill_names() == {"sandbox"}
    reason = engine._skill_restriction_for("read_file")
    assert reason is not None and "not allowed by skill" in reason
    assert engine._skill_restriction_for("grep") is None


@pytest.mark.asyncio
async def test_skill_without_allowlist_imposes_nothing(tmp_path):
    engine = _make_skill_engine(tmp_path, [])
    engine.messages.append(
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {"id": "load1", "type": "function",
                 "function": {"name": "load_skill", "arguments": json.dumps({"name": "sandbox"})}}
            ],
        }
    )
    engine.messages.append(
        {"role": "tool", "tool_call_id": "load1", "content": json.dumps({"instructions": "do x"})}
    )
    assert engine._skill_restriction_for("write_file") is None