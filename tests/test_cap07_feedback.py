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