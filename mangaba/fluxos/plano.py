"""Do fluxo para o `Plan` — o que torna o `entrega` do cartão verificável.

Um fluxo era uma string de prompt entregue a uma conversa nova. O cartão prometia "e-mails
em rascunho, agrupados por faixa de atraso" e nada no runtime tinha como conferir se aquilo
saiu: o modelo improvisava a decomposição a cada execução, o painel de Progresso dependia
dele lembrar de chamar `todo_write`, e um trabalho que não coubesse num turno não deixava
rastro do que já tinha sido feito.

O `Plan` (passos, dependências, done-gate que só cobra passo desbloqueado) já existia — só
não era alimentado por ninguém. Aqui os `passos` declarados no catálogo viram um plano
encadeado, e a abertura da conversa manda o agente gravá-lo antes de começar. A partir daí
o done-gate do engine cobra os passos abertos, e a persistência do plano faz a retomada
entre execuções valer para fluxo agendado também.

Encadeamento linear (cada passo depende do anterior) é deliberado: um fluxo de catálogo
descreve um procedimento em ordem. O agente pode reescrever o plano com `plan_write` se o
trabalho real exigir outra forma — o plano semeado é ponto de partida, não camisa de força.
"""

from __future__ import annotations

from typing import Any


def plano_do_fluxo(passos: list[str]) -> list[dict[str, Any]]:
    """Os passos declarados como passos de `Plan`, encadeados na ordem escrita."""
    plano: list[dict[str, Any]] = []
    for i, descricao in enumerate(passos or [], start=1):
        texto = str(descricao).strip()
        if not texto:
            continue
        passo: dict[str, Any] = {
            "id": f"p{i}",
            "description": texto,
            "status": "pending",
        }
        if plano:
            passo["depends_on"] = [plano[-1]["id"]]
        plano.append(passo)
    return plano


def prompt_com_plano(prompt: str, passos: list[str]) -> str:
    """A abertura da conversa do fluxo, com a instrução de gravar o plano antes de agir.

    O plano é dito em texto (e não injetado direto no engine) porque a conversa do fluxo
    nasce pelo caminho normal de sessão: quem a inicia é a GUI mandando uma mensagem. Fazer
    o próprio agente chamar `plan_write` mantém um caminho só — e deixa o plano visível no
    histórico, em vez de aparecer do nada.
    """
    plano = plano_do_fluxo(passos)
    if not plano:
        return prompt
    linhas = "\n".join(f"{p['id']}. {p['description']}" for p in plano)
    return (
        f"{prompt}\n\n"
        "Antes de começar, grave este plano com `plan_write` (cada passo depende do "
        "anterior) e vá atualizando o status conforme concluir:\n"
        f"{linhas}\n"
        "Só considere o trabalho pronto quando todos os passos estiverem `done`."
    )
