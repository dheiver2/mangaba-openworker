"""Tool registry — wraps callables (incl. aisuite toolkit tools) into a registry the
runtime owns: JSON schemas for the model, plus execution. Permission checks live in the
PermissionEngine and are applied by the turn engine, not here.

Schema generation is reused from aisuite (`Tools`) so we don't reimplement
docstring/type-hint → JSON-schema extraction.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Optional

from aisuite.utils.tools import Tools


def enxugar_schema(obj: Any) -> Any:
    """Tira do schema o que não carrega informação: `"description": ""` e `"default": null`.

    O gerador de schema da aisuite emite uma `description` vazia para todo parâmetro sem
    docstring própria, e um `default: null` para todo opcional — em 61 ferramentas isso vira
    lixo repetido que o modelo lê em TODO turno. Medido em 2026-08-06: ~4% do prefixo (263
    tokens no cowork), e no motor local o prefill frio custa ~5 ms por token, então são ~1,3 s
    de espera por prefixo novo. É a única poda sem risco nenhum — não remove capacidade, não
    muda semântica, só apaga campos que não dizem nada.
    """
    if isinstance(obj, dict):
        return {
            k: enxugar_schema(v)
            for k, v in obj.items()
            if not (k == "description" and v == "") and not (k == "default" and v is None)
        }
    if isinstance(obj, list):
        return [enxugar_schema(x) for x in obj]
    return obj


@dataclass
class ToolSpec:
    name: str
    schema: dict[str, Any]  # OpenAI-format function tool schema
    func: Callable[..., Any]
    metadata: Any = None  # aisuite ToolMetadata or None


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, ToolSpec] = {}

    def register(
        self,
        func: Callable[..., Any],
        *,
        metadata: Any = None,
        schema: Optional[dict[str, Any]] = None,
    ) -> ToolSpec:
        name = getattr(func, "__name__", None)
        if not name:
            raise ValueError("Tool function must have a __name__.")
        meta = metadata or getattr(func, "__aisuite_tool_metadata__", None)
        # Allow an explicit schema override (param or a `__mangaba_schema__` attribute)
        # for tools whose signature can't be auto-converted to a valid JSON schema.
        resolved_schema = (
            schema or getattr(func, "__mangaba_schema__", None) or _schema_for(func)
        )
        spec = ToolSpec(
            name=name, schema=enxugar_schema(resolved_schema), func=func, metadata=meta
        )
        self._tools[name] = spec
        return spec

    def register_all(self, funcs: list[Callable[..., Any]]) -> None:
        for func in funcs:
            self.register(func)

    def names(self) -> list[str]:
        return list(self._tools)

    def get(self, name: str) -> Optional[ToolSpec]:
        return self._tools.get(name)

    def schemas(self) -> list[dict[str, Any]]:
        return [spec.schema for spec in self._tools.values()]

    def execute(self, name: str, arguments: Optional[dict[str, Any]] = None) -> Any:
        spec = self._tools.get(name)
        if spec is None:
            raise KeyError(f"Tool not registered: {name}")
        return spec.func(**(arguments or {}))


def _schema_for(func: Callable[..., Any]) -> dict[str, Any]:
    """Generate one OpenAI-format tool schema via aisuite's schema generator."""
    return Tools([func]).tools(format="openai")[0]
