"""Identidade de serviço entre os dois catálogos (conector nativo ⇄ servidor MCP).

O problema que isto resolve: nove serviços existem nas DUAS modelagens — um conector nativo
(OAuth gerenciado, tools escritas à mão) e um servidor MCP do mesmo produto. As chaves são
diferentes ("hubspot" vs "hubspot_mcp") ou iguais por acaso ("linear", "notion", "stripe").
O resolvedor de fluxos cruza nomes literais, então um fluxo que pede `conectores=["linear"]`
dizia "falta conectar" mesmo com o Linear já conectado pelo MCP — e empurrava a pessoa a
conectar a MESMA coisa uma segunda vez, criando uma conexão duplicada.

Aqui mora o mapa de equivalência: se QUALQUER representação de um serviço está conectada, a
peça do fluxo está satisfeita — a sessão carrega as tools daquela via (nativa OU MCP) de todo
jeito. O mapa é curado de propósito (nove serviços, não uma heurística de prefixo que
confundiria "github" com o MCP genérico "git"), e um teste o valida contra os catálogos reais
para um rename quebrar o CI em vez de chegar ao usuário como um fluxo eternamente "faltando 1".
"""

from __future__ import annotations

# serviço canônico → (nome do conector nativo, {nomes de MCP equivalentes})
# Só entram serviços que existem DE FATO nos dois lados. github/gitlab NÃO mapeiam para o MCP
# "git" (genérico, não é a API do GitHub); intercom e pipedrive são MCP-only (sem conector).
SERVICOS_DUPLOS: dict[str, tuple[str, frozenset[str]]] = {
    "linear": ("linear", frozenset({"linear"})),
    "hubspot": ("hubspot", frozenset({"hubspot_mcp"})),
    "monday": ("monday", frozenset({"monday_mcp"})),
    "asana": ("asana", frozenset({"asana_mcp"})),
    "attio": ("attio", frozenset({"attio_mcp"})),
    "clickup": ("clickup", frozenset({"clickup_mcp"})),
    "close": ("close", frozenset({"close_mcp"})),
    "notion": ("notion", frozenset({"notion"})),
    "stripe": ("stripe", frozenset({"stripe"})),
}

# Índices derivados, para o resolvedor consultar em O(1) nas duas direções.
_MCPS_DO_CONECTOR: dict[str, frozenset[str]] = {
    con: mcps for (con, mcps) in SERVICOS_DUPLOS.values()
}
_CONECTOR_DO_MCP: dict[str, str] = {
    mcp: con for (con, mcps) in SERVICOS_DUPLOS.values() for mcp in mcps
}


def mcps_equivalentes(conector: str) -> frozenset[str]:
    """Os servidores MCP que valem como o mesmo serviço que este conector nativo."""
    return _MCPS_DO_CONECTOR.get(conector, frozenset())


def conector_equivalente(mcp: str) -> str | None:
    """O conector nativo que vale como o mesmo serviço que este servidor MCP (ou None)."""
    return _CONECTOR_DO_MCP.get(mcp)
