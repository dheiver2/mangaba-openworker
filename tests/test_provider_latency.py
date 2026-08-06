"""Suíte de testes unitários para a funcionalidade de benchmark e medição de latência dos provedores."""

from __future__ import annotations

import time
from typing import Any, List, Optional
import pytest

from mangaba.providers.base import (
    AssistantTurn,
    ModelCapabilities,
    ProviderClient,
    StreamChunk,
    TokenUsage,
    ToolCall,
)
from mangaba.testing.latency import (
    LatencyBenchmarkRunner,
    LatencyBenchmarkSummary,
    LatencyRunMetric,
    format_benchmark_table,
)


class MockStreamingProvider(ProviderClient):
    """Provedor mock com simulação configurável de atraso/latência de streaming."""

    def __init__(self, delay_per_token: float = 0.01, ttft_delay: float = 0.05) -> None:
        self.delay_per_token = delay_per_token
        self.ttft_delay = ttft_delay

    def complete(
        self,
        *,
        model: str,
        messages: list[dict[str, Any]],
        tools: Optional[list[dict[str, Any]]] = None,
        **settings: Any,
    ) -> AssistantTurn:
        time.sleep(self.ttft_delay + self.delay_per_token * 3)
        return AssistantTurn(
            text="Resposta mock simples para teste.",
            usage=TokenUsage(input=10, output=20),
        )

    def capabilities(self, model: str) -> ModelCapabilities:
        return ModelCapabilities(streaming=True)

    def stream(
        self,
        *,
        model: str,
        messages: list[dict[str, Any]],
        tools: Optional[list[dict[str, Any]]] = None,
        **settings: Any,
    ):
        # Simula o atraso do Time to First Token (TTFT)
        time.sleep(self.ttft_delay)

        tokens = ["Olá,", " este", " é", " um", " teste", " de", " latência."]
        for i, tok in enumerate(tokens):
            if i > 0:
                time.sleep(self.delay_per_token)
            yield StreamChunk(text_delta=tok)

        turn = AssistantTurn(
            text="".join(tokens),
            usage=TokenUsage(input=15, output=len(tokens)),
        )
        yield StreamChunk(turn=turn)


class MockErrorProvider(ProviderClient):
    """Provedor mock que gera exceção para simular falhas de rede/API."""

    def complete(
        self,
        *,
        model: str,
        messages: list[dict[str, Any]],
        tools: Optional[list[dict[str, Any]]] = None,
        **settings: Any,
    ) -> AssistantTurn:
        raise RuntimeError("Erro simulado de conexão com o provedor LLM")

    def capabilities(self, model: str) -> ModelCapabilities:
        return ModelCapabilities()


def test_latency_runner_single_run():
    mock_provider = MockStreamingProvider(delay_per_token=0.01, ttft_delay=0.04)
    runner = LatencyBenchmarkRunner(mock_provider)

    messages = [{"role": "user", "content": "Olá"}]
    metric = runner.run_single(model="mock:test-model", messages=messages, run_index=1)

    assert metric.error is None
    assert metric.run_index == 1
    # TTFT deve ser próximo de ttft_delay (0.04s)
    assert metric.ttft_seconds >= 0.03
    # Duração total deve englobar TTFT + tempo dos tokens
    assert metric.total_duration_seconds > metric.ttft_seconds
    assert metric.output_tokens == 7
    assert metric.tps > 0
    assert len(metric.inter_token_latencies_ms) == 6


def test_latency_runner_benchmark():
    mock_provider = MockStreamingProvider(delay_per_token=0.01, ttft_delay=0.03)
    runner = LatencyBenchmarkRunner(mock_provider)

    messages = [{"role": "user", "content": "Teste completo"}]
    summary = runner.benchmark(
        provider_name="mock",
        model="mock:test-model",
        messages=messages,
        runs=3,
        warmup=True,
    )

    assert summary.provider == "mock"
    assert summary.runs_requested == 3
    assert summary.runs_completed == 3
    assert summary.runs_failed == 0
    assert summary.avg_ttft_ms > 20.0
    assert summary.avg_tps > 0.0
    assert len(summary.metrics) == 3

    formatted = format_benchmark_table(summary)
    assert "RELATÓRIO DE LATÊNCIA DE PROVEDOR" in formatted
    assert "mock:test-model" in formatted


def test_latency_runner_handles_error():
    mock_error = MockErrorProvider()
    runner = LatencyBenchmarkRunner(mock_error)

    messages = [{"role": "user", "content": "Erro"}]
    summary = runner.benchmark(
        provider_name="mock_error",
        model="mock:error-model",
        messages=messages,
        runs=2,
        warmup=False,
    )

    assert summary.runs_completed == 0
    assert summary.runs_failed == 2
    assert summary.avg_ttft_ms == 0.0
    assert summary.avg_tps == 0.0
    assert summary.metrics[0].error is not None
    assert "Erro simulado de conexão" in summary.metrics[0].error
