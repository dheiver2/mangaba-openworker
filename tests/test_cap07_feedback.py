"""Capability #7 — automatic post-turn learning from user feedback."""

from __future__ import annotations

from mangaba.feedback import extract_corrections, distill_feedback
from mangaba.memory import Scope, SQLiteMemoryStore


def _messages(user1, assistant1, user2):
    return [
        {"role": "user", "content": user1},
        {"role": "assistant", "content": assistant1},
        {"role": "user", "content": user2},
    ]


def test_extract_corrections_detects_corrective_turn():
    msgs = _messages(
        "faz um relatório",
        "Criei um PDF em /tmp/rel.pdf",
        "Não era isso, eu queria uma planilha.",
    )
    corr = extract_corrections(msgs)
    assert len(corr) == 1 and "planilha" in corr[0]["user_text"]


def test_extract_ignores_non_corrective_turn():
    msgs = _messages("oi", "olá!", "obrigado, funcionou.")
    assert extract_corrections(msgs) == []


def test_distill_saves_correction_to_memory(tmp_path):
    store = SQLiteMemoryStore(tmp_path / "m.db")
    msgs = _messages("1", "devo entregar o arquivo", "Na verdade o correto é entregar X.")
    result = distill_feedback(store, msgs, workspace="/w", session_id="s1")
    assert result["saved"] == 1
    items = store.list(workspace="/w")
    assert any("Correção do usuário" in m.content for m in items)


def test_distill_deduplicates_same_session(tmp_path):
    store = SQLiteMemoryStore(tmp_path / "m.db")
    msgs = _messages("1", "olha o resultado", "não é isso, use tabs.")
    distill_feedback(store, msgs, workspace="/w", session_id="s1")
    result = distill_feedback(store, msgs, workspace="/w", session_id="s1")
    assert result["saved"] == 0 and result["skipped"] == 1

# -- aprendizado onde não há humano -------------------------------------------
def test_run_que_falha_deixa_licao_objetiva(tmp_path):
    """`distill_feedback` só aprende de correção do usuário — numa execução agendada não há
    usuário. O resultado era o inverso do que a autonomia precisa: quanto mais autônomo o
    modo, menos ele aprendia. Aqui o sinal é o veredito da execução, não texto."""
    from mangaba.feedback import distill_run
    store = SQLiteMemoryStore(tmp_path / "mem.db")
    texto = distill_run(
        store,
        task_id="task-1",
        titulo="Fechamento do mês",
        motivo="max_iterations_exceeded",
        workspace="/ws",
    )
    assert texto and "Fechamento do mês" in texto
    assert any(m.key == "run:task-1:max_iterations_exceeded"
               for m in store.list(scope=Scope.WORKSPACE, workspace="/ws"))


def test_a_mesma_falha_repetida_nao_enche_a_memoria(tmp_path):
    """Uma automação que falha do mesmo jeito por 30 dias tem de deixar UMA memória. Sem a
    chave por (tarefa, motivo), o bloco de memória viraria log e afogaria o resto."""
    from mangaba.feedback import distill_run
    store = SQLiteMemoryStore(tmp_path / "mem.db")
    for _ in range(5):
        distill_run(store, task_id="t", titulo="X", motivo="erro",
                    workspace="/ws", detalhe="conexão recusada")
    assert len(store.list(scope=Scope.WORKSPACE, workspace="/ws")) == 1


def test_run_bem_sucedida_nao_ensina_nada(tmp_path):
    from mangaba.feedback import distill_run
    store = SQLiteMemoryStore(tmp_path / "mem.db")
    assert distill_run(store, task_id="t", titulo="X", motivo="completed") is None
