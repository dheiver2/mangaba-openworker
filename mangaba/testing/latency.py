"""Módulo de benchmark e testes de latência para os provedores do Mangaba AI / OpenWorker.

Permite medir:
- TTFT (Time to First Token)
- Latência total de execução (segundos)
- TPS (Tokens por segundo / Throughput)
- Inter-Token Latency (ITL)
- Comparações com e sem chamadas de ferramentas (tool calling)
"""

from __future__ import annotations

import argparse
import json
import statistics
import time
from dataclasses import asdict, dataclass, field
from typing import Any, List, Optional, Sequence

from mangaba.providers.base import AssistantTurn, ProviderClient, StreamChunk


@dataclass
class LatencyRunMetric:
    """Métricas de um único disparo de benchmark."""

    run_index: int
    ttft_seconds: float
    total_duration_seconds: float
    output_tokens: int
    input_tokens: int
    tps: float
    chunk_count: int
    inter_token_latencies_ms: List[float] = field(default_factory=list)
    has_tool_calls: bool = False
    error: Optional[str] = None


@dataclass
class LatencyBenchmarkSummary:
    """Sumário estatístico acumulado de múltiplos disparos de benchmark."""

    provider: str
    model: str
    runs_requested: int
    runs_completed: int
    runs_failed: int
    avg_ttft_ms: float
    p95_ttft_ms: float
    avg_total_duration_s: float
    p95_total_duration_s: float
    avg_tps: float
    p95_tps: float
    avg_inter_token_latency_ms: float
    metrics: List[LatencyRunMetric] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        return data


class LatencyBenchmarkRunner:
    """Executor de benchmarks de latência para ProviderClients do Mangaba."""

    def __init__(self, provider_client: ProviderClient) -> None:
        self.client = provider_client

    def run_single(
        self,
        model: str,
        messages: List[dict[str, Any]],
        tools: Optional[List[dict[str, Any]]] = None,
        run_index: int = 0,
        **settings: Any,
    ) -> LatencyRunMetric:
        """Executa uma requisição em modo streaming e calcula métricas minuciosas de latência."""
        start_time = time.perf_counter()
        first_token_time: Optional[float] = None
        last_chunk_time: Optional[float] = None
        inter_token_latencies: List[float] = []

        chunk_count = 0
        final_turn: Optional[AssistantTurn] = None
        accumulated_text = ""

        try:
            stream = self.client.stream(
                model=model, messages=messages, tools=tools, **settings
            )
            for chunk in stream:
                now = time.perf_counter()
                chunk_count += 1

                # Verifica se há delta de texto ou raciocínio no chunk
                if chunk.text_delta or chunk.reasoning_delta:
                    if first_token_time is None:
                        first_token_time = now
                    elif last_chunk_time is not None:
                        dt_ms = (now - last_chunk_time) * 1000.0
                        inter_token_latencies.append(dt_ms)
                    
                    if chunk.text_delta:
                        accumulated_text += chunk.text_delta

                last_chunk_time = now
                if chunk.turn is not None:
                    final_turn = chunk.turn

            total_duration = time.perf_counter() - start_time

            # Se não houve stream detalhado (ex: provedor sem streaming real), TTFT é a duração total
            if first_token_time is None:
                first_token_time = start_time + total_duration

            ttft = first_token_time - start_time

            # Determina número de tokens de saída (pelo usage ou aproximado por palavras)
            output_tokens = 0
            input_tokens = 0
            has_tool_calls = False

            if final_turn is not None:
                has_tool_calls = final_turn.has_tool_calls
                if final_turn.usage:
                    output_tokens = final_turn.usage.output
                    input_tokens = final_turn.usage.input

            if output_tokens == 0 and accumulated_text:
                # Estimativa heurística (~4 caracteres por token) se usage não veio
                output_tokens = max(1, len(accumulated_text) // 4)

            # Cálculo de TPS (Tokens por Segundo) considerando o tempo após o primeiro token
            generation_time = total_duration - ttft
            if generation_time > 0.001 and output_tokens > 0:
                tps = output_tokens / generation_time
            elif total_duration > 0 and output_tokens > 0:
                tps = output_tokens / total_duration
            else:
                tps = 0.0

            return LatencyRunMetric(
                run_index=run_index,
                ttft_seconds=ttft,
                total_duration_seconds=total_duration,
                output_tokens=output_tokens,
                input_tokens=input_tokens,
                tps=tps,
                chunk_count=chunk_count,
                inter_token_latencies_ms=inter_token_latencies,
                has_tool_calls=has_tool_calls,
                error=None,
            )

        except Exception as err:
            total_duration = time.perf_counter() - start_time
            return LatencyRunMetric(
                run_index=run_index,
                ttft_seconds=total_duration,
                total_duration_seconds=total_duration,
                output_tokens=0,
                input_tokens=0,
                tps=0.0,
                chunk_count=chunk_count,
                inter_token_latencies_ms=[],
                has_tool_calls=False,
                error=str(err),
            )

    def benchmark(
        self,
        provider_name: str,
        model: str,
        messages: List[dict[str, Any]],
        tools: Optional[List[dict[str, Any]]] = None,
        runs: int = 3,
        warmup: bool = True,
        **settings: Any,
    ) -> LatencyBenchmarkSummary:
        """Executa uma bateria completa de testes de latência."""
        if warmup:
            # Descarte de aquecimento de conexão (warmup)
            self.run_single(model, messages, tools, run_index=-1, **settings)

        metrics: List[LatencyRunMetric] = []
        for i in range(runs):
            metric = self.run_single(model, messages, tools, run_index=i + 1, **settings)
            metrics.append(metric)

        successful_runs = [m for m in metrics if m.error is None]
        failed_count = len(metrics) - len(successful_runs)

        if not successful_runs:
            return LatencyBenchmarkSummary(
                provider=provider_name,
                model=model,
                runs_requested=runs,
                runs_completed=0,
                runs_failed=failed_count,
                avg_ttft_ms=0.0,
                p95_ttft_ms=0.0,
                avg_total_duration_s=0.0,
                p95_total_duration_s=0.0,
                avg_tps=0.0,
                p95_tps=0.0,
                avg_inter_token_latency_ms=0.0,
                metrics=metrics,
            )

        ttfts_ms = [m.ttft_seconds * 1000.0 for m in successful_runs]
        durations_s = [m.total_duration_seconds for m in successful_runs]
        tps_list = [m.tps for m in successful_runs]

        all_itls: List[float] = []
        for m in successful_runs:
            all_itls.extend(m.inter_token_latencies_ms)

        def _p95(vals: List[float]) -> float:
            if not vals:
                return 0.0
            sorted_vals = sorted(vals)
            idx = int(len(sorted_vals) * 0.95)
            return sorted_vals[min(idx, len(sorted_vals) - 1)]

        avg_ttft = statistics.mean(ttfts_ms)
        p95_ttft = _p95(ttfts_ms)

        avg_duration = statistics.mean(durations_s)
        p95_duration = _p95(durations_s)

        avg_tps_val = statistics.mean(tps_list)
        p95_tps_val = _p95(tps_list)

        avg_itl = statistics.mean(all_itls) if all_itls else 0.0

        return LatencyBenchmarkSummary(
            provider=provider_name,
            model=model,
            runs_requested=runs,
            runs_completed=len(successful_runs),
            runs_failed=failed_count,
            avg_ttft_ms=round(avg_ttft, 2),
            p95_ttft_ms=round(p95_ttft, 2),
            avg_total_duration_s=round(avg_duration, 3),
            p95_total_duration_s=round(p95_duration, 3),
            avg_tps=round(avg_tps_val, 2),
            p95_tps=round(p95_tps_val, 2),
            avg_inter_token_latency_ms=round(avg_itl, 2),
            metrics=metrics,
        )


def format_benchmark_table(summary: LatencyBenchmarkSummary) -> str:
    """Formata o relatório de latência em formato legível de tabela de texto."""
    lines = [
        f"============================================================",
        f"  RELATÓRIO DE LATÊNCIA DE PROVEDOR - MANGABA AI / OPENWORKER",
        f"============================================================",
        f" Provedor           : {summary.provider}",
        f" Modelo             : {summary.model}",
        f" Testes Executados  : {summary.runs_completed}/{summary.runs_requested} (Falhas: {summary.runs_failed})",
        f" -----------------------------------------------------------",
        f" TTFT (Time to 1st Token) : Média = {summary.avg_ttft_ms:.2f} ms | P95 = {summary.p95_ttft_ms:.2f} ms",
        f" Tempo Total de Execução  : Média = {summary.avg_total_duration_s:.3f} s  | P95 = {summary.p95_total_duration_s:.3f} s",
        f" Throughput (TPS)         : Média = {summary.avg_tps:.2f} tok/s | P95 = {summary.p95_tps:.2f} tok/s",
        f" Latência Inter-Token     : Média = {summary.avg_inter_token_latency_ms:.2f} ms",
        f" -----------------------------------------------------------",
        f" DETALHES DAS CORRIDAS:",
    ]

    for m in summary.metrics:
        status = f"FALHA: {m.error}" if m.error else "OK"
        lines.append(
            f"  Run #{m.run_index}: TTFT={m.ttft_seconds*1000:.1f}ms | "
            f"Total={m.total_duration_seconds:.2f}s | Tokens Out={m.output_tokens} | "
            f"TPS={m.tps:.1f} | Status={status}"
        )

    lines.append(f"============================================================")
    return "\n".join(lines)


def main(args: Optional[Sequence[str]] = None) -> None:
    """CLI para rodar testes de latência diretamente pelo terminal."""
    parser = argparse.ArgumentParser(
        description="Mangaba AI Provider Latency Benchmarking Tool"
    )
    parser.add_argument(
        "--model",
        type=str,
        default="local:qwen3-4b",
        help="Modelo a testar (ex: 'openai:gpt-4o', 'local:qwen3-4b', 'anthropic:claude-3-5-sonnet')",
    )
    parser.add_argument(
        "--prompt",
        type=str,
        default="Escreva um pequeno poema em português sobre automação e inteligência artificial.",
        help="Prompt para o teste de latência",
    )
    parser.add_argument(
        "--runs",
        type=int,
        default=3,
        help="Número de rodadas para medição de latência",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Exibir saída formatada em JSON",
    )

    parsed = parser.parse_args(args)

    from mangaba.providers.router import ProviderRouter
    router = ProviderRouter()

    messages = [{"role": "user", "content": parsed.prompt}]
    runner = LatencyBenchmarkRunner(router)

    summary = runner.benchmark(
        provider_name=router._provider_name(parsed.model),
        model=parsed.model,
        messages=messages,
        runs=parsed.runs,
    )

    if parsed.json:
        print(json.dumps(summary.to_dict(), indent=2))
    else:
        print(format_benchmark_table(summary))


if __name__ == "__main__":
    main()
