"""Friendly translation of model access + quota failures.

The picker now defaults to brand-new flagships (GPT-5.6 Sol, Claude Fable 5), and not every
account can use them: OpenAI is still rolling GPT-5.6 out per-organization, and both vendors
reject calls once quota/credits run out. Those failures arrive as terse SDK exceptions
wrapping JSON error bodies; this maps the well-known shapes to one actionable sentence.
Anything unrecognized returns None and the caller surfaces the raw error unchanged.

Matching is on the error BODY text (error codes/types), not just HTTP status — a 404 also
means "wrong base_url" and a 429 also means "slow down", and neither of those should be
dressed up as an access problem.
"""

from __future__ import annotations

import re

from typing import Optional

# Error-body markers, verbatim from the vendors' error codes/messages:
# OpenAI: {"error": {"code": "model_not_found", "message": "The model `X` does not exist or
#   you do not have access to it."}} (404/403) and {"code": "insufficient_quota"} (429).
# Anthropic: {"type": "not_found_error", "message": "model: X"} (404),
#   {"type": "permission_error"} (403), and "credit balance is too low" (400).
_NO_ACCESS = (
    "model_not_found",
    "does not exist or you do not have access",
    "does not have access to model",
    "permission_error",
    "permission denied",
)
_NO_QUOTA = (
    "insufficient_quota",
    "exceeded your current quota",
    "credit balance is too low",
    "billing hard limit",
)


def friendly_model_error(model: str, exc: Exception) -> Optional[str]:
    """One actionable sentence for "your account can't use this model" failures, or None."""
    text = str(exc).lower()
    # Estouro de contexto do llama.cpp (gateways próprios e o motor local). O corpo cru é
    # um JSON com n_ctx/n_prompt_tokens que não diz NADA para quem só quer trabalhar — e
    # o caso real que motivou isto foi um gateway anunciando 32k e servindo 8k.
    if "exceed_context_size" in text or "exceeds the available context size" in text:
        nums = re.findall(r"\((\d+) tokens\)", str(exc))
        pedido, cabe = (nums + ["?", "?"])[:2]
        return (
            f"A conversa ficou maior que a janela de contexto de {model}: foram "
            f"{pedido} tokens para um limite de {cabe}. Comece uma sessão nova, "
            "desligue conectores que não estiver usando (cada um soma ferramentas ao "
            "prompt), ou escolha um modelo com janela maior. Se este for um gateway "
            "da sua organização, peça ao administrador para aumentar o `--ctx-size`."
        )
    no_access = (
        f"Your account doesn't have access to {model} — new models can roll out "
        "gradually or require a plan upgrade. Pick a different model, or check "
        "the provider's console for availability."
    )
    # 429 de RITMO (não de crédito). O gateway da organização passou a limitar por chave
    # (30 req/min por padrão) e o laço agêntico é rajado: com cache quente um hop leva
    # ~1,7s, o que dá ~35 req/min de UM agente só — acima do teto. O SDK já tenta 2x com
    # backoff; quando esgota, isto é o que a pessoa lê, em vez do JSON cru.
    if "rate_limit" in text or "rate limit" in text or "too many requests" in text:
        return (
            "O provedor recusou por excesso de requisições no minuto — o agente faz uma "
            "chamada por passo e trabalha em rajada. Aguarde alguns segundos e mande de "
            "novo. Se este for o gateway da sua organização, peça ao administrador para "
            "aumentar o limite por minuto (`rpm`) da sua chave: uso agêntico pede pelo "
            "menos 60/min."
        )
    if any(marker in text for marker in _NO_QUOTA):
        return (
            f"Your account is out of quota for {model} — add credits or raise the limit "
            "in the provider's billing console, or pick a different model."
        )
    if any(marker in text for marker in _NO_ACCESS):
        return no_access
    # Anthropic's 404 body is just "model: <id>" under type not_found_error; require both
    # halves so unrelated 404s (bad base_url, deleted resource) keep their raw message.
    if "not_found_error" in text and f"model: {model.split(':')[-1].lower()}" in text:
        return no_access
    return None
