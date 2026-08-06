"""Capability #3 — general-purpose subagents (delegate) + fan-out orchestration."""

from __future__ import annotations

from mangaba.providers import AssistantTurn, ModelCapabilities, ProviderClient
from mangaba.tools import ToolRegistry
from mangaba.tools.delegate import delegate_tools
from mangaba.tools.subagent import build_explorer_engine


class EchoProvider(ProviderClient):
    """Returns the SAME text turn forever — safe for any number of child engines."""

    def complete(self, *, model, messages, tools=None, **settings):
        return AssistantTurn(text="relatório final: tudo verificado", finish_reason="stop")

    def capabilities(self, model):
        return ModelCapabilities()


def test_delegate_researcher_role(tmp_path):
    reg = ToolRegistry()
    reg.register_all(delegate_tools(workspace=tmp_path, provider=EchoProvider(), model="gpt-5.5"))
    result = reg.execute("delegate", {"role": "researcher", "task": "descubra onde X é tratado"})
    assert "report" in result and "pesquisou" not in result["report"]
    assert result["role"] == "researcher"


def test_delegate_rejects_unknown_role(tmp_path):
    reg = ToolRegistry()
    reg.register_all(delegate_tools(workspace=tmp_path, provider=EchoProvider(), model="gpt-5.5"))
    result = reg.execute("delegate", {"role": "janitor", "task": "limpe"})
    assert result["error"]


def test_fan_out_merges_reports(tmp_path):
    reg = ToolRegistry()
    reg.register_all(delegate_tools(workspace=tmp_path, provider=EchoProvider(), model="gpt-5.5"))
    result = reg.execute(
        "fan_out", {"role": "researcher", "tasks": ["revise A", "revise B", "revise C"]}
    )
    assert result["count"] == 3
    assert len(result["results"]) == 3
    assert all("report" in r for r in result["results"])


def test_fan_out_rejects_empty_tasks(tmp_path):
    reg = ToolRegistry()
    reg.register_all(delegate_tools(workspace=tmp_path, provider=EchoProvider(), model="gpt-5.5"))
    assert "error" in reg.execute("fan_out", {"role": "researcher", "tasks": []})


def test_delegate_writer_has_write_tools(tmp_path):
    # The writer role's engine must expose a write path (scratch) — probe its toolset.
    from mangaba.tools.delegate import build_worker_engine

    engine = build_worker_engine(
        role="writer", workspace=tmp_path, provider=EchoProvider(), model="gpt-5.5"
    )
    names = set(engine.registry.names())
    assert "write_file" in names or "ai_write_file" in names or any("write" in n for n in names)


def test_researcher_role_read_only(tmp_path):
    from mangaba.tools.delegate import build_worker_engine

    engine = build_worker_engine(
        role="researcher", workspace=tmp_path, provider=EchoProvider(), model="gpt-5.5"
    )
    names = set(engine.registry.names())
    assert "grep" in names and "git_log" in names
    assert not any("write" in n for n in names)
    assert "delegate" not in names and "fan_out" not in names  # no recursion