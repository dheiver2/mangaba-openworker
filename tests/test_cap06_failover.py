"""Capability #6 — automatic model failover on transient provider errors."""

from __future__ import annotations

import asyncio

import pytest

from mangaba.engine import TurnEngine
from mangaba.events import EventType
from mangaba.providers import AssistantTurn, ModelCapabilities, ProviderClient
from mangaba.tools import ToolRegistry


class FailoverProvider(ProviderClient):
    """The primary model fails with a transient error; the fallback succeeds."""

    def __init__(self):
        self.current = "primary"

    def complete(self, *, model, messages, tools=None, **settings):
        if model == "primary":
            raise RuntimeError("429 rate limit exceeded")
        return AssistantTurn(text="ok after failover", finish_reason="stop")

    def stream(self, *, model, messages, tools=None, **settings):
        if model == "primary":
            raise RuntimeError("connection reset by peer")
        yield __import__("mangaba.providers.base", fromlist=["StreamChunk"]).StreamChunk(
            turn=AssistantTurn(text="ok after failover", finish_reason="stop")
        )

    def capabilities(self, model):
        return ModelCapabilities()


def _engine(provider, fallback_models):
    return TurnEngine(
        provider=provider,
        registry=ToolRegistry(),
        permissions=None,
        model="primary",
        fallback_models=fallback_models,
    )


@pytest.mark.asyncio
async def test_failover_retries_on_fallback_model():
    provider = FailoverProvider()
    engine = _engine(provider, ["fallback"])
    # permissions/evaluate not used since no tools; but _authorize needs permissions? No
    # tool calls here, so only the stream path runs.
    events = [e async for e in engine.run("tarefa")]
    types = [e.type for e in events]
    assert EventType.TURN_END in types
    assert any(e.type == EventType.ASSISTANT_MESSAGE for e in events)
    # A model_switch notice was appended so the transcript is honest.
    notices = [m for m in engine.messages if m.get("role") == "notice"]
    assert any("switched" in str(m.get("text", "")) for m in notices)


@pytest.mark.asyncio
async def test_no_failover_without_fallback():
    provider = FailoverProvider()
    engine = _engine(provider, [])
    events = [e async for e in engine.run("tarefa")]
    assert any(e.type == EventType.ERROR for e in events)