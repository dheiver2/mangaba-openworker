"""Selective memory recall + consolidation.

The base memory layer (`base.py`) injects the WHOLE store into the prompt
(`format_memories`) — fine for a handful of memories, noise once the store grows. This
module adds two things, both free of new dependencies (no embedding model):

- **Recall**: a deterministic, stop-word-aware token scorer that returns the top-k memories
  most relevant to the current task text. The engine can inject only those, and exposes
  `memory_recall` for on-demand lookups.
- **Consolidation**: merges near-duplicate memories (same edited-normalized stem signature)
  by retiring the older copy — so corrections replace stale facts instead of piling up, and
  the recall index stays tight.
"""

from __future__ import annotations

import re
from collections import Counter
from typing import Iterable, Optional

from .base import MemoryItem, MemoryStore, Scope, format_memories

_STOPWORDS = {
    "a", "agora", "ao", "aos", "as", "com", "como", "da", "das", "de", "do", "dos",
    "e", "em", "entre", "era", "esse", "esse", "esta", "este", "eu", "faça", "fazer",
    "foi", "haver", "isto", "já", "mais", "mas", "no", "na", "nos", "nas", "não",
    "o", "os", "ou", "para", "por", "que", "se", "sua", "suas", "seu", "seus", "também",
    "the", "and", "or", "of", "to", "for", "with", "in", "on", "a", "an", "is", "are",
    "was", "were", "it", "do", "does", "from", "this", "that",
}

_TOKEN = re.compile(r"[\w\u00C0-\u024F]+")


def _tokens(text: str) -> Counter:
    words = [w.lower() for w in _TOKEN.findall(text) if w.lower() not in _STOPWORDS]
    return Counter(words)


def _signature(text: str) -> tuple:
    """A normalized stem signature for duplicate detection (order-insensitive, deduped)."""
    return tuple(sorted(set(_tokens(text))))


def score_memories(items: Iterable[MemoryItem], query: str) -> list[tuple[MemoryItem, float]]:
    """Rank memories by term-overlap relevance to `query`. Returns (item, score) descending."""
    q = _tokens(query)
    if not q:
        return [(item, 0.0) for item in items]
    scored: list[tuple[MemoryItem, float]] = []
    for item in items:
        d = _tokens(item.content)
        if not d:
            continue
        overlap = sum(min(q[t], d[t]) for t in q)
        # Normalize a little by the doc's size so one giant entry can't always win.
        score = overlap / (1.0 + 0.5 * sum(d.values()))
        scored.append((item, score))
    scored.sort(key=lambda pair: pair[1], reverse=True)
    return scored


def recall_memories(
    store: MemoryStore,
    query: str,
    *,
    k: int = 5,
    scope: Optional[Scope] = None,
    workspace: Optional[str] = None,
    min_score: float = 0.0,
) -> list[MemoryItem]:
    """Top-k most relevant memories for `query`, scoped as requested. Replaces the blanket
    full-store injection with the relevant slice (falls back to the full list when there's
    nothing scored above `min_score`, so the agent still sees its context)."""
    items = store.list(scope=scope, workspace=workspace)
    if not items:
        return []
    ranked = score_memories(items, query)
    hits = [item for item, s in ranked[:k] if s >= min_score]
    return hits or items[:k]


def consolidate_memories(
    store: MemoryStore,
    *,
    workspace: Optional[str] = None,
    scope: Optional[Scope] = None,
) -> dict[str, Any]:
    """Retire near-duplicate memories (identical stem signature within the same workspace/scope)
    keeping the newest copy (SQLite returns ascending by id). Returns what it merged."""
    items = store.list(scope=scope, workspace=workspace)
    by_sig: dict[tuple, list[MemoryItem]] = {}
    for item in items:
        sig = _signature(item.content)
        if sig:
            by_sig.setdefault(sig, []).append(item)

    merged = 0
    for sig, group in by_sig.items():
        if len(group) < 2:
            continue
        keeper = group[-1]  # newest (highest id)
        for dup in group[:-1]:
            if store.delete(dup.id):
                merged += 1
    return {"merged": merged}


def recall_block(items: list[MemoryItem], query: Optional[str] = None) -> str:
    """Render recalled memories into a prompt block, reusing the id-carrying format so the
    agent can still `memory_update` / `memory_forget` by id."""
    if not items:
        return ""
    body = format_memories(items)
    return body + (f"\n(Said: recovered by relevance for '{query.strip()}'.)" if query and query.strip() else "")