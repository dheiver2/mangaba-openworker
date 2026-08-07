"""Quais capacidades agênticas cada FAMÍLIA de persona recebe — fonte única.

O gating vivia como `if agent.family in ("code", "knowledge", ...)` espalhado por
`agent.py`, e o roteamento de fluxo repetia a mesma regra à mão em `fluxos/estado.py`.
Os dois só ficavam em dia porque um teste de invariante comparava um com o outro; quando
divergiam, o sintoma que chegava ao usuário era uma automação que "roda" e nunca se agenda.

Aqui a regra é declarada uma vez. `agent.py` pergunta se a família TEM a capacidade;
`estado.py` pergunta qual é a família mais enxuta que tem TODAS as que o fluxo exige. Isso
importa mais agora que fluxos podem ser gerados em runtime (`criar_fluxo`): a regra precisa
ser consultável por código, não só verificável por teste.

Por que estas famílias e não outras:

- `agendar` só em "knowledge" — `create_scheduled_task` mora lá, e é de propósito: dar
  agendamento a "business" arrastaria a persona enxuta para perto do tamanho da Cowork, e o
  custo de prefill do esquema de ferramentas é a lentidão que se sente no modelo local.
- `verificar` fica nas famílias de ENTREGA ("code", "business"), que produzem artefato com
  como falhar; "knowledge" conversa mais do que constrói.
- `integracoes` é o pacote de conector/MCP (navegador, e-mail, mensageria). Só "knowledge",
  pelo mesmo motivo de tamanho.
"""

from __future__ import annotations

# Ordem de PREFERÊNCIA, da família mais enxuta para a mais completa. `familia_para` devolve a
# primeira que sirva — o fluxo só paga pelo tamanho que precisa.
_FAMILIAS_POR_TAMANHO: tuple[tuple[str, str], ...] = (
    ("negocio", "business"),
    ("cowork", "knowledge"),
)

CAPACIDADES: dict[str, tuple[str, ...]] = {
    # Subagente de pesquisa somente leitura (`explore`).
    "explorar": ("code", "knowledge", "business"),
    # Subagentes gerais (`delegate`/`fan_out`).
    "delegar": ("code", "knowledge", "business"),
    # Verificação estruturada (`run_verify` + tracker).
    "verificar": ("code", "business"),
    # Criar/alterar automações (`create_scheduled_task`).
    "agendar": ("knowledge",),
    # Suspender e marcar a própria retomada (`sleep_for`/`wake_on`).
    "autodespertar": ("knowledge",),
    # Conectores + servidores MCP (navegador, e-mail, mensageria).
    "integracoes": ("knowledge",),
}


def familia_tem(familia: str, capacidade: str) -> bool:
    """A família recebe essa capacidade? Capacidade desconhecida é negada (fail-closed)."""
    return familia in CAPACIDADES.get(capacidade, ())


def familia_para(exigidas: list[str] | set[str] | tuple[str, ...]) -> str:
    """O nome do agente mais enxuto que tem TODAS as capacidades exigidas.

    Sem exigência nenhuma, devolve a família mais enxuta. Se nenhuma servir (combinação que
    o app não oferece), devolve a mais completa em vez de erro: o fluxo ainda roda com o que
    houver, e a peça que faltar já aparece como pendente no cartão.
    """
    pedidas = set(exigidas or ())
    for nome, familia in _FAMILIAS_POR_TAMANHO:
        if all(familia_tem(familia, c) for c in pedidas):
            return nome
    return _FAMILIAS_POR_TAMANHO[-1][0]


def familia_do_agente(nome: str) -> str:
    """A família de uma persona de destino de fluxo ("negocio" → "business")."""
    return dict(_FAMILIAS_POR_TAMANHO).get(nome, "knowledge")


def capacidades_desconhecidas(exigidas: list[str] | set[str] | tuple[str, ...]) -> list[str]:
    """As capacidades pedidas que não existem — usado ao validar um fluxo gerado."""
    return sorted(c for c in (exigidas or ()) if c not in CAPACIDADES)
