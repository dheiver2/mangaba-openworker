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


# -- aprendizado sem humano na frente ------------------------------------------------
#
# `distill_feedback` aprende de CORREÇÃO do usuário — mensagem curta com marcador de
# "errado", "corrija", "na verdade". Numa execução agendada não há usuário nenhum, então o
# efeito prático era o inverso do que a autonomia precisa: quanto mais autônomo o modo,
# menos ele aprendia. Justamente onde ninguém está olhando é onde o erro se repete todo dia.
#
# O sinal aqui não depende de humano nem de heurística de texto: é o veredito objetivo da
# execução — estourou o teto de rodadas, quebrou com exceção. Uma lição por MOTIVO por
# automação (a chave carrega o id da tarefa), então uma automação que falha do mesmo jeito
# por 30 dias deixa uma memória, não trinta.

_LICOES = {
    "max_iterations_exceeded": (
        "A automação {titulo!r} não coube em uma execução (parou no teto de rodadas). Ao "
        "rodá-la, comece pelos passos que produzem o entregável e feche cada passo do plano "
        "assim que terminar — o que ficar aberto continua na execução seguinte."
    ),
    "erro": (
        "A automação {titulo!r} falhou com: {detalhe}. Verifique essa condição antes de "
        "repetir os mesmos passos."
    ),
}


def distill_run(
    store: MemoryStore,
    *,
    task_id: str,
    titulo: str,
    motivo: str,
    workspace: Optional[str] = None,
    detalhe: str = "",
) -> Optional[str]:
    """Grava a lição objetiva de uma execução não-supervisionada. Devolve o texto gravado,
    ou `None` quando o motivo não ensina nada (execução que deu certo) ou já foi gravado."""
    molde = _LICOES.get(motivo)
    if molde is None:
        return None
    key = f"run:{task_id}:{motivo}"
    ja_existe = any(
        m.key == key for m in store.list(scope=Scope.WORKSPACE, workspace=workspace)
    ) or any(m.key == key for m in store.list(scope=Scope.GLOBAL))
    if ja_existe:
        return None
    conteudo = molde.format(titulo=titulo, detalhe=(detalhe or "")[:200])
    store.add(
        conteudo,
        scope=Scope.WORKSPACE if workspace else Scope.GLOBAL,
        key=key,
        workspace=workspace,
    )
    return conteudo


def _signature(text: str) -> str:
    import hashlib

    return hashlib.sha1(text.strip().lower().encode("utf-8")).hexdigest()[:12]