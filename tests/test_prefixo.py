"""Teto do PREFIXO de cada família de agente — o custo fixo pago em todo turno.

Por que isto é um teste e não um relatório: o prefixo (system + esquema das ferramentas) é
reenviado a cada hop do laço agêntico, e ele cresce sozinho. Toda ferramenta nova o empurra
para cima, ninguém sente na hora, e um dia a primeira resposta ficou lenta sem que nada
"tenha mudado". Já aconteceu neste projeto: a v0.1.33 criou a família `negocio` justamente
para fugir das ~47 ferramentas do cowork, e em 2026-08-06 o cowork estava em 61.

Os números que sustentam os tetos, medidos em 2026-08-06:

- motor local (qwen3-4b): prefill FRIO de 3.675 tokens levou 18,9 s — ~5 ms por token. Cada
  1.000 tokens de prefixo custam ~5 s na primeira resposta de uma sessão (com o cache quente
  a mesma chamada cai para 1,3 s).
- gateway Mangaba: prompt curto responde em 0,55 s de forma estável, mas a partir de alguns
  milhares de tokens a cadeia de fallback desvia para modelos 5× mais lentos — 2 s a 4,8 s.
  Ou seja, o prefixo sozinho já tira toda sessão agêntica da faixa rápida.

Os tetos abaixo são o valor MEDIDO na data, arredondado para cima com folga. Se um deles
estourar, a pergunta não é "aumenta o teto?" — é "esta ferramenta nova precisa mesmo estar no
prefixo de todo turno, ou pode ser carregada sob demanda?".
"""

from __future__ import annotations

import json
import tempfile

import pytest

from mangaba.server.manager import SessionManager

# família → teto de tokens do prefixo (system + schemas)
TETOS = {
    "chat": 3_200,
    "negocio": 5_400,
    "code": 6_300,
    "cowork": 8_200,
}


def _medir(agente: str) -> tuple[int, int, int]:
    m = SessionManager(workspace=tempfile.mkdtemp())
    eng = m.get_engine(f"__prefixo__{agente}", agent=agente)
    schemas = eng.registry.schemas()
    tok_schemas = len(json.dumps(schemas, ensure_ascii=False)) // 4
    system = eng._outbound_messages()[0].get("content") or ""
    tok_system = len(system) // 4
    return len(schemas), tok_schemas, tok_system


@pytest.mark.parametrize("agente,teto", sorted(TETOS.items()))
def test_prefixo_da_familia_cabe_no_teto(agente: str, teto: int):
    n, tok_schemas, tok_system = _medir(agente)
    total = tok_schemas + tok_system
    assert total <= teto, (
        f"o prefixo de `{agente}` subiu para ~{total} tokens ({n} ferramentas: "
        f"{tok_schemas} de schema + {tok_system} de system), acima do teto de {teto}.\n"
        f"Isso é pago em TODO turno, e no motor local custa ~5 ms por token de prefill frio "
        f"(~{total * 5 / 1000:.1f} s na primeira resposta).\n"
        f"Antes de subir o teto: a ferramenta nova precisa estar no prefixo de todo turno, "
        f"ou pode ser carregada sob demanda?"
    )


def test_schemas_nao_carregam_campos_vazios():
    """O gerador da aisuite emite `description: ""` para todo parâmetro sem docstring e
    `default: null` para todo opcional. São ~263 tokens só no cowork — lixo que o modelo lê
    em todo turno, sem carregar informação nenhuma."""
    m = SessionManager(workspace=tempfile.mkdtemp())
    bruto = json.dumps(
        m.get_engine("__prefixo__vazios", agent="cowork").registry.schemas(),
        ensure_ascii=False,
    )
    assert '"description": ""' not in bruto
    assert '"default": null' not in bruto


def test_chat_e_o_mais_enxuto_e_cowork_o_mais_gordo():
    """A ordem entre as famílias é intencional: `chat` não tem área de trabalho e não deve
    pagar por ferramenta de entrega; `negocio` existe porque o cowork ficou grande demais
    para fluxo de negócio. Se essa ordem inverter, a separação perdeu o sentido."""
    tamanhos = {ag: sum(_medir(ag)[1:]) for ag in TETOS}
    assert tamanhos["chat"] < tamanhos["negocio"] < tamanhos["cowork"]
    assert tamanhos["negocio"] < tamanhos["code"], (
        "`negocio` foi criada para ser mais enxuta que a família de código"
    )
