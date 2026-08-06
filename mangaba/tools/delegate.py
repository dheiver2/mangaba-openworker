"""General-purpose subagents + fan-out orchestration.

`s/explore` covers the read-only researcher. This module generalizes it:

- **`delegate(role, task, workspace)`** — spawns a child TurnEngine with a role-shaped toolset
  and system prompt, keeps only its final report, and returns it. Roles:
  - `researcher`: read-only (grep/read/git) — the same slice as `explore`.
  - `writer`: reads into a scratch subfolder of the workspace and writes there, so a subagent
    can assemble a deliverable without polluting the caller's context; the report lists the
    files it produced.
  - `verifier`: read + shell, runs the target's tests and reports pass/fail.
- **`fan_out(role, tasks)`** — runs several independent subagents for the same role in
  parallel (map), each with its own context, then merges the reports (reduce). Use for
  "review these N files independently" breadth work.

Child engines never get `delegate`/`fan_out`/`explore` (no recursion), and `researcher` runs
in plan mode so writes are hard-blocked.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, Optional

import aisuite as ai

from ..engine import TurnEngine
from ..events import EventType
from ..permissions import Mode, PermissionEngine
from ..tools import ToolRegistry
from .files import file_tools
from .git import git_tools
from .search import search_tools
from .shell import LocalExecutor
from .verify import verify_tools, VerifyTracker

_ROLES = {"researcher", "writer", "verifier"}

_RESEARCHER_INSTRUCTIONS = """Você é um pesquisador somente leitura na área de trabalho. \
Pesquise a tarefa com `grep`, `read_file`, `list_files`, `git_log`, `git_status`, `git_diff`. \
Não escreva arquivos nem rode comandos. Sua mensagem final é o relatório QUE VOLTA PARA O \
AGENTE QUE TE CRIOU (não para o usuário): autocontido, referenciando código como caminho:linha \
e citando os trechos principais. Se não achar algo, diga o que pesquisou para não repetirem \
buscas. Escreva em português do Brasil."""

_WRITER_INSTRUCTIONS = """Você é um redator de documentos na área de trabalho. Produza o \
arquivo(s) entregável que a tarefa pede apenas dentro da pasta `.mangaba/scratch` (já é a sua \
área de trabalho raiz). Sua mensagem final é o relatório PARA O AGENTE QUE TE CRIOU: liste os \
arquivos que criou/alterou, resuma o conteúdo e aponte limitações. Escreva em português do Brasil."""

_VERIFIER_INSTRUCTIONS = """Você é um verificador. Investigue o trabalho recebido (leia \
arquivos, greps) e, quando possível, rode o teste/check mais restrito cabível via `run_verify`. \
Sua mensagem final é o relatório QUE VOLTA PARA O AGENTE QUE TE CRIOU: o que você verificou, o \
que rodou, se passou/falhou e o que ainda parece quebrado, com caminhos:linha. Escreva em português."""

_CHILD_MAX_ITERATIONS = 10


def _writer_dir(ws: str) -> Path:
    base = Path(ws).resolve() / ".mangaba" / "scratch"
    base.mkdir(parents=True, exist_ok=True)
    return base


def _registry_for(role: str, ws: str) -> ToolRegistry:
    import aisuite as _ai

    registry = ToolRegistry()
    replaced = {"search_files", "read_file", "read_file_lines"}
    registry.register_all(
        t
        for t in _ai.toolkits.files(root=ws)
        if getattr(t, "__name__", "") not in replaced
    )
    registry.register_all(file_tools(ws))
    registry.register_all(_ai.toolkits.git(root=ws))
    registry.register_all(git_tools(ws))
    registry.register_all(search_tools(ws))
    if role == "writer":
        # Writer's own writable scratch within the shared workspace (read-only elsewhere).
        scratch = _writer_dir(ws)
        scratch_files = [
            t
            for t in _ai.toolkits.files(root=str(scratch), allow_write=True)
            if getattr(t, "__name__", "") not in replaced
        ]
        registry.register_all(scratch_files)
    if role == "verifier":
        registry.register_all(verify_tools(LocalExecutor(cwd=ws), VerifyTracker()))
    return registry


def build_worker_engine(
    *,
    role: str,
    workspace: str | Path,
    provider: Any,
    model: str,
    model_settings: Optional[dict[str, Any]] = None,
    max_iterations: int = _CHILD_MAX_ITERATIONS,
) -> TurnEngine:
    if role not in _ROLES:
        raise ValueError(f"unknown role {role!r}")
    ws = str(Path(workspace).resolve())
    mode = Mode.PLAN if role == "researcher" else Mode.INTERACTIVE
    registry = _registry_for(role, ws)
    permissions = PermissionEngine(workspace_root=Path(ws), mode=mode)
    instructions = {
        "researcher": _RESEARCHER_INSTRUCTIONS,
        "writer": _WRITER_INSTRUCTIONS,
        "verifier": _VERIFIER_INSTRUCTIONS,
    }[role]
    return TurnEngine(
        provider=provider,
        registry=registry,
        permissions=permissions,
        model=model,
        instructions=instructions,
        max_iterations=max_iterations,
        model_settings=model_settings,
    )


def _run_child(engine: TurnEngine, task: str) -> tuple[str, str]:
    report, status = "", "unknown"

    async def _run() -> None:
        nonlocal report, status
        async for event in engine.run(task):
            if event.type == EventType.ASSISTANT_MESSAGE and event.data.get("text"):
                report = event.data["text"]
            elif event.type == EventType.TURN_END:
                status = event.data.get("status", "unknown")
            elif event.type == EventType.ERROR:
                report = f"error: {event.data.get('error', '')}"
                status = "error"
                return

    asyncio.run(_run())  # tools execute in a worker thread; no running loop here
    return report, status


def _run_worker(event_pair) -> tuple[str, str]:
    return _run_child(event_pair[0], event_pair[1])


def _wrap(fn, name: str, schema: dict) -> Any:
    fn.__name__ = name
    fn.__doc__ = schema["function"]["description"]
    wrapped = ai.tool(
        fn,
        metadata=ai.ToolMetadata(
            name=name,
            category="subagent",
            risk_level="low",
            capabilities=["delegate"],
            requires_approval=False,
        ),
    )
    wrapped.__mangaba_schema__ = schema
    return wrapped


_DELEGATE_SCHEMA = {
    "type": "function",
    "function": {
        "name": "delegate",
        "description": (
            "Delegate a bounded, self-contained sub-task to a fresh subagent with its own "
            "context window (its intermediate tool use never touches your context). Roles: "
            "'researcher' (read-only), 'writer' (assembles a deliverable in a scratch folder "
            "and reports the files), 'verifier' (runs the relevant checks). Returns only the "
            "final report."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "role": {"type": "string", "enum": sorted(_ROLES)},
                "task": {"type": "string"},
            },
            "required": ["role", "task"],
        },
    },
}

_FANOUT_SCHEMA = {
    "type": "function",
    "function": {
        "name": "fan_out",
        "description": (
            "Run several independent subagents for the same role in parallel (one context "
            "window each) and merge their reports. Use for breadth work: review files "
            "independently, summarize sections, sample-check a dataset. Each task must be "
            "self-contained."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "role": {"type": "string", "enum": sorted(_ROLES)},
                "tasks": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["role", "tasks"],
        },
    },
}


def delegate_tools(
    *,
    workspace: str | Path,
    provider: Any,
    model: str,
    model_settings: Optional[dict[str, Any]] = None,
) -> list:
    def _make(role: str) -> TurnEngine:
        return build_worker_engine(
            role=role,
            workspace=workspace,
            provider=provider,
            model=model,
            model_settings=model_settings,
        )

    def delegate(role: str, task: str) -> dict[str, Any]:
        if role not in _ROLES:
            return {"error": f"unknown role {role!r}: {sorted(_ROLES)}"}
        engine = _make(role)
        report, status = _run_child(engine, task)
        if not report:
            return {"error": f"subagent ({role}) produced no report (status: {status})"}
        result: dict[str, Any] = {"role": role, "report": report}
        if status != "completed":
            result["note"] = f"subagent stopped early ({status}); report may be partial"
        return result

    def fan_out(role: str, tasks: list[str]) -> dict[str, Any]:
        if role not in _ROLES:
            return {"error": f"unknown role {role!r}: {sorted(_ROLES)}"}
        if not tasks:
            return {"error": "no tasks to fan out"}
        engines = [_make(role) for _ in tasks]
        results = [_run_worker((e, t)) for e, t in zip(engines, tasks)]
        merged = []
        for (report, status), task in zip(results, tasks):
            merged.append({"task": task, "status": status, "report": report})
        return {"role": role, "count": len(merged), "results": merged}

    return [_wrap(delegate, "delegate", _DELEGATE_SCHEMA),
            _wrap(fan_out, "fan_out", _FANOUT_SCHEMA)]