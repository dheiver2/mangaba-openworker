"""Capability #2 — selective memory recall + consolidation."""

from __future__ import annotations

from mangaba.memory import Scope, SQLiteMemoryStore
from mangaba.memory.recall import (
    consolidate_memories,
    recall_block,
    recall_memories,
    score_memories,
)


def _store(tmp_path):
    return SQLiteMemoryStore(tmp_path / "mem.db")


def test_recall_ranks_relevant_first(tmp_path):
    store = _store(tmp_path)
    store.add("Usa indentação de 2 espaços no Python", workspace="/proj")
    store.add("o deploy às sextas é proibido", workspace="/proj")
    store.add("prefere tabs", workspace="/proj")
    hits = recall_memories(store, "qual indentação usamos?", k=3, workspace="/proj")
    assert hits[0].content.startswith("Usa indentação")


def test_recall_returns_top_k(tmp_path):
    store = _store(tmp_path)
    for n in range(10):
        store.add(f"item {n} sobre cache de dados", workspace="/proj")
    hits = recall_memories(
        store, "decisão sobre cache", k=2, workspace="/proj"
    )
    assert 1 <= len(hits) <= 2


def test_recall_scope_isolation(tmp_path):
    store = _store(tmp_path)
    store.add("fato global", scope=Scope.GLOBAL)
    store.add("fato da workspace", workspace="/other")
    hits = recall_memories(store, "fato global", workspace="/proj")
    assert all(h.scope is Scope.GLOBAL for h in hits)


def test_consolidate_removes_near_duplicates(tmp_path):
    store = _store(tmp_path)
    store.add("usa ponto e vírgula sempre", workspace="/p")
    store.add("sempre ponto; vírgula usa e", workspace="/p")  # same tokens
    store.add("prefere tabulação", workspace="/p")
    result = consolidate_memories(store, workspace="/p")
    assert result["merged"] >= 1
    remaining = store.list(workspace="/p")
    assert len(remaining) == 2


def test_score_memories_empty_query(tmp_path):
    store = _store(tmp_path)
    store.add("qualquer coisa", workspace="/p")
    assert score_memories(store.list(workspace="/p"), "")[0][1] == 0.0


def test_recall_block_carries_ids(tmp_path):
    store = _store(tmp_path)
    item = store.add("nome do cliente no arquivo bd", workspace="/p")
    block = recall_block(store.list(workspace="/p"), query="cliente")
    assert f"[#{item.id}]" in block and "recovered" in block