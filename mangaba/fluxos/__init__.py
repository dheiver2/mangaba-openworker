"""Fluxos agênticos prontos — a porta de entrada por PROBLEMA, não por mecanismo.

O app expõe cinco mecanismos (automações, conectores, servidores MCP, skills e modelos) em
quatro telas diferentes, cada um nomeado pelo que É. Para montar algo útil, a pessoa precisa
entender os cinco conceitos e traduzir sozinha o problema dela para eles — tradução que o
produto deveria fazer por ela.

Aqui a unidade é o PROBLEMA do dia a dia ("cobrar quem está atrasado"), e cada problema tem
mais de um FLUXO que o resolve. Ter alternativas não é enfeite: a empresa com CRM resolve
diferente da que só tem planilha, quem quer no piloto automático resolve diferente de quem
quer sob demanda, e quem trata dado sensível resolve diferente de quem não trata. Um caminho
único obrigaria todo mundo a ter a mesma pilha.

Cada fluxo declara suas peças, então o app calcula sozinho o que já está pronto e o que
falta — sem prometer o que não existe.
"""

from .catalog import (
    FLUXOS,
    PROBLEMAS,
    fluxo_por_id,
    listar_problemas,
    problema_por_id,
)

__all__ = [
    "FLUXOS",
    "PROBLEMAS",
    "fluxo_por_id",
    "listar_problemas",
    "problema_por_id",
]
