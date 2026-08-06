"""Post-turn learning from user feedback.

The agent only learns when it decides to call `remember`. This module adds a cheap,
automatic distillation path: after a turn, scan for user corrections (a short user message
following an assistant reply that contradicts or corrects it) and save them as scoped
memories — so the SAME mistake is less likely to repeat in the next session. Guarded to be
conservative: only clearly corrective turns (negative/corrective markers) are distilled, and
each correction is saved once per session.
"""

from __future__ import annotations

import re
from typing import Optional

from .memory.base import MemoryItem, MemoryStore, Scope

_CORRECTIVE_HINT = re.compile(
    r"(n[ãa]o\s+(é|foi|era|pode|deveria)|errad|incorret|cuidado|corrija|correto\s+é|"
    r"evite|nunca\s+mais|pare\s+de|o\s+certo\s+é|a\s+certa\s+é|na\s+verdade|"
    r"esquece\s+isso|ignore\s+isso|diferente\s+do\s+que)",
    re.I,
)

_VERY_SHORT = 12  # a correction is usually terse


def _plain(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = [p.get("text", "") for p in content if isinstance(p, dict)]
        return " ".join(parts)
    return str(content or "")


def extract_corrections(messages: list[dict]) -> list[dict]:
    """Find user messages that read as corrections of the preceding assistant reply.
    Returns [{"user_text", "assistant_text"}]. A correction is a terse user message with a
    corrective marker that directly follows an assistant text turn."""
    out: list[dict] = []
    for i, msg in enumerate(messages):
        if msg.get("role") != "user":
            continue
        text = _plain(msg.get("content")).strip()
        if not text or len(text) > 400:
            continue
        if not _CORRECTIVE_HINT.search(text):
            continue
        # The preceding non-tool, non-notice message should be an assistant reply.
        prev = next(
            (
                m
                for m in reversed(messages[:i])
                if m.get("role") in ("assistant", "user")
            ),
            None,
        )
        if prev is None or prev.get("role") != "assistant":
            continue
        assistant_text = _plain(prev.get("content")).strip()
        if not assistant_text:
            continue
        out.append({"user_text": text, "assistant_text": assistant_text[:600]})
    return out


def distill_feedback(
    store: MemoryStore,
    messages: list[dict],
    *,
    workspace: Optional[str] = None,
    session_id: Optional[str] = None,
) -> dict[str, Any]:
    """Save corrections as memories, skipping ones already saved this session (keyed
    `feedback:<signature>`). Returns what was learned."""
    corrections = extract_corrections(messages)
    saved, skipped = 0, 0
    for c in corrections:
        key = "feedback:" + _signature(c["user_text"])
        exists = any(
            m.key == key and m.session_id == session_id
            for m in store.list(scope=Scope.GLOBAL)
        ) or any(
            m.key == key and m.session_id == session_id
            for m in store.list(scope=Scope.WORKSPACE, workspace=workspace)
        )
        if exists:
            skipped += 1
            continue
        content = f"Correção do usuário: {c['user_text'].strip()}"
        store.add(
            content,
            scope=Scope.WORKSPACE if workspace else Scope.GLOBAL,
            key=key,
            workspace=workspace,
            session_id=session_id,
        )
        saved += 1
    return {"saved": saved, "skipped": skipped, "corrections": len(corrections)}


def _signature(text: str) -> str:
    import hashlib

    return hashlib.sha1(text.strip().lower().encode("utf-8")).hexdigest()[:12]