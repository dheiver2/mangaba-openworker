"""`criar_fluxo` — o pedido do usuário virando procedimento guardado.

Até aqui, o único artefato durável que um pedido podia virar era `create_scheduled_task`,
cujo conteúdo é uma string de instruções: sem passos, sem peças declaradas, sem entrega
verificável. Tudo que o runtime tem de estruturado — `Plan`, resolução de prontidão,
roteamento por capacidade — só existia para os fluxos escritos à mão no catálogo.

Esta ferramenta fecha a diferença: o agente que acabou de fazer um trabalho pode gravá-lo
como fluxo, com os passos que de fato executou e as peças que de fato usou. Da próxima vez,
é um cartão pronto.

Gated (`requires_approval`): guardar um procedimento é decisão da pessoa, e o cartão de
aprovação é onde ela vê o que está sendo declarado antes de virar item permanente da tela.

Nada é gravado sem passar por `validar_fluxo`. Um fluxo com peça inexistente não é fluxo
ruim — é cartão que nunca fica pronto, e a pessoa fica travada nele sem entender por quê.
"""

from __future__ import annotations

import re
import uuid
from typing import Any, Callable

import aisuite as ai

from .catalog import _fluxo
from .store import FluxoStore
from .validacao import Inventario, validar_fluxo

_CRIAR_SCHEMA = {
    "type": "function",
    "function": {
        "name": "criar_fluxo",
        "description": (
            "Guarde o trabalho que você acabou de fazer como um fluxo reutilizável, para a "
            "pessoa repetir com um clique em vez de reexplicar. Use quando um trabalho de "
            "vários passos deu certo e tem cara de recorrente. Declare apenas peças que você "
            "REALMENTE usou (skills, servidores MCP, conectores) — peça declarada é peça "
            "verificada, e uma que não existe deixa o fluxo travado para sempre. Os `passos` "
            "viram o plano de execução: escreva as ações na ordem em que aconteceram. A "
            "pessoa confirma antes de o fluxo ser criado."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "titulo": {
                    "type": "string",
                    "description": "O CAMINHO que este fluxo toma, não o problema — "
                                   "ex.: 'Da planilha, quando eu pedir'.",
                },
                "resumo": {
                    "type": "string",
                    "description": "Uma ou duas frases sobre o que ele faz.",
                },
                "entrega": {
                    "type": "string",
                    "description": "O que aparece na mão da pessoa no fim — ex.: 'e-mails em "
                                   "rascunho, para você revisar'. Não 'processa os dados'.",
                },
                "prompt": {
                    "type": "string",
                    "description": "A instrução que abre a conversa quando o fluxo é usado.",
                },
                "passos": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "As ações verificáveis, em ordem. Viram o plano de execução.",
                },
                "skills": {"type": "array", "items": {"type": "string"}},
                "mcps": {"type": "array", "items": {"type": "string"}},
                "conectores": {"type": "array", "items": {"type": "string"}},
                "agendado": {
                    "type": "string",
                    "description": "Quando roda sozinho, em linguagem natural ('Segunda, 9h'). "
                                   "Omita para um fluxo sob demanda.",
                },
                "aprovacao": {
                    "type": "boolean",
                    "description": "true quando o fluxo manda mensagem ou mexe em dado externo "
                                   "— aí cada ação passa pela pessoa. Padrão true.",
                },
            },
            "required": ["titulo", "resumo", "entrega", "prompt", "passos"],
        },
    },
}


def _id_a_partir_do_titulo(titulo: str, usados: set[str]) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", titulo.lower()).strip("-")[:40] or "fluxo"
    if base not in usados:
        return base
    return f"{base}-{uuid.uuid4().hex[:4]}"


def fluxo_tools(store: FluxoStore, inventario: Callable[[], Inventario]) -> list:
    """`criar_fluxo` ligado ao armazém e ao inventário real da máquina.

    O inventário é um callable, não um valor: entre a construção do engine e a chamada da
    ferramenta a pessoa pode ter instalado uma skill ou conectado uma conta, e validar
    contra uma foto velha recusaria uma peça que já existe.
    """

    def criar_fluxo(
        titulo: str,
        resumo: str,
        entrega: str,
        prompt: str,
        passos: list = None,
        skills: list = None,
        mcps: list = None,
        conectores: list = None,
        agendado: str = "",
        aprovacao: bool = True,
    ) -> dict:
        proposta = _fluxo(
            id="",
            titulo=titulo,
            resumo=resumo,
            entrega=entrega,
            skills=[str(s) for s in (skills or [])],
            mcps=[str(m) for m in (mcps or [])],
            conectores=[str(c) for c in (conectores or [])],
            agendado=(agendado or "").strip() or None,
            aprovacao=bool(aprovacao),
            prompt=prompt,
            passos=[str(p) for p in (passos or [])],
        )
        erros = validar_fluxo(proposta, inventario())
        if erros:
            # Devolver os erros (em vez de gravar assim mesmo) é o ponto: o modelo corrige e
            # chama de novo. Gravar produziria o cartão travado que a validação evita.
            return {"ok": False, "erros": erros}

        usados = {f["id"] for f in store.listar()}
        proposta["id"] = _id_a_partir_do_titulo(titulo, usados)
        proposta["problema_id"] = "meus-fluxos"
        proposta["problema"] = "Meus fluxos"
        store.salvar(proposta)
        return {
            "ok": True,
            "id": proposta["id"],
            "passos": len(proposta["passos"]),
            "nota": "O fluxo aparece na tela de Fluxos, em 'Meus fluxos'.",
        }

    wrapped = ai.tool(
        criar_fluxo,
        metadata=ai.ToolMetadata(
            name="criar_fluxo",
            category="planning",
            risk_level="low",
            capabilities=["fluxo"],
            # Item permanente na tela da pessoa: ela vê o que está sendo declarado antes.
            requires_approval=True,
        ),
    )
    wrapped.__mangaba_schema__ = _CRIAR_SCHEMA
    return [wrapped]
