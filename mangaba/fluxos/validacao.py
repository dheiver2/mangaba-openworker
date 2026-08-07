"""Validação de um fluxo PROPOSTO — as invariantes que antes só existiam no CI.

`tests/test_fluxos.py` guarda duas regras contra o catálogo escrito à mão:

- **peça declarada tem de existir** (`test_toda_peca_referenciada_existe_de_verdade`): um
  nome errado produz um fluxo que nunca fica pronto, porque a peça inexistente conta como
  faltando para sempre e a pessoa trava num cartão impossível de completar;
- **fluxo agendado não nasce em família sem `create_scheduled_task`**
  (`test_fluxo_agendado_nunca_roteia_para_negocio`): o agente veria a instrução de agendar
  e não teria a ferramenta.

Blindagem de CI basta para fluxo escrito à mão — ele passa pelo CI antes de existir. Um
fluxo GERADO em runtime não passa por lugar nenhum, então as mesmas regras precisam rodar
na hora da criação. Aqui é o mesmo predicado; o CI passa a chamar isto em vez de
reimplementar a regra por fora.

Recusar é a decisão certa quando a peça não existe: gravar o fluxo mesmo assim produz
exatamente o cartão travado que a regra existe para impedir.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..capacidades import (
    capacidades_desconhecidas,
    familia_do_agente,
    familia_para,
    familia_tem,
)

# Um fluxo com menos que isto não é procedimento, é recado — e o `Plan` semeado a partir
# dele não daria ao done-gate nada que valha cobrar.
_MIN_PASSOS = 2


@dataclass
class Inventario:
    """O que a máquina realmente tem — a fonte contra a qual as peças são conferidas."""

    skills: set[str] = field(default_factory=set)
    mcps: set[str] = field(default_factory=set)
    conectores: set[str] = field(default_factory=set)


def validar_fluxo(proposta: dict[str, Any], inventario: Inventario) -> list[str]:
    """Os problemas que impedem o fluxo de existir. Lista vazia = pode gravar.

    As mensagens vão direto para o modelo que propôs, então dizem o que corrigir, não só
    o que está errado.
    """
    erros: list[str] = []

    if not str(proposta.get("titulo", "")).strip():
        erros.append("falta `titulo`: o caminho que este fluxo toma para resolver o problema")
    if not str(proposta.get("entrega", "")).strip():
        erros.append(
            "falta `entrega`: o que aparece na mão da pessoa no fim "
            '(ex.: "e-mails em rascunho, para você revisar")'
        )
    if not str(proposta.get("prompt", "")).strip():
        erros.append("falta `prompt`: a instrução que abre a conversa do fluxo")

    passos = [str(p).strip() for p in (proposta.get("passos") or []) if str(p).strip()]
    if len(passos) < _MIN_PASSOS:
        erros.append(
            f"`passos` precisa de pelo menos {_MIN_PASSOS} ações verificáveis, em ordem — "
            "é o que vira o plano de execução e permite conferir a entrega"
        )

    for nome in proposta.get("skills") or []:
        if nome not in inventario.skills:
            erros.append(
                f"skill {nome!r} não existe nesta máquina — declarar peça inexistente cria "
                "um fluxo que nunca fica pronto; use uma skill instalada ou remova-a"
            )
    for nome in proposta.get("mcps") or []:
        if nome not in inventario.mcps:
            erros.append(f"servidor MCP {nome!r} não existe no catálogo desta máquina")
    for nome in proposta.get("conectores") or []:
        if nome not in inventario.conectores:
            erros.append(f"conector {nome!r} não existe nesta máquina")

    desconhecidas = capacidades_desconhecidas(proposta.get("exige") or [])
    if desconhecidas:
        erros.append(f"capacidades inexistentes em `exige`: {', '.join(desconhecidas)}")

    # A invariante do agendamento, agora em runtime. Ela é consequência de `familia_para`,
    # então na prática só dispara se alguém mexer no registro de capacidades sem querer —
    # e é exatamente aí que ela precisa gritar, em vez de virar automação que nunca agenda.
    if proposta.get("agendado"):
        exigidas = list(proposta.get("exige") or []) + ["agendar"]
        familia = familia_para(exigidas)
        if not familia_tem(familia_do_agente(familia), "agendar"):
            erros.append(
                f"fluxo agendado roteia para {familia!r}, que não recebe `create_scheduled_task` "
                "— a automação nunca seria criada"
            )

    return erros
