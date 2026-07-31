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


# O motor local (Ollama, escrito em Go) devolve 500 com um erro de PARSE quando não
# consegue interpretar como JSON algo que recebeu — a assinatura é o texto do Go
# "invalid character 'X' looking for beginning of value". Relatado por usuário em
# 31/07/2026: Windows, qwen3:4b, mensagem "oi", com o app mandando as 19 ferramentas.
# Não é erro do Mangaba nem falta de recurso, e o texto cru ("Error code: 500 -
# {'error': {'message': "invalid character '<'...") não diz nada a quem só quer conversar.
# As duas causas conhecidas: o modelo emite chamada de ferramenta em XML (<tool_call>,
# formato do Qwen) e a versão do motor a interpreta como JSON; ou um proxy/antivírus
# devolve HTML no lugar da resposta interna do motor.
_PARSE_DO_MOTOR = "looking for beginning of value"


def friendly_local_engine_error(model: str, exc: Exception) -> Optional[str]:
    """Uma frase acionável para a falha de parse do motor local, ou None."""
    if _PARSE_DO_MOTOR not in str(exc):
        return None
    return (
        f"O motor local não conseguiu processar a resposta do {model}. Isso costuma ser "
        "incompatibilidade entre a versão do motor e o formato de chamada de ferramenta "
        "deste modelo. Tente: (1) escolher outro modelo local em Configurações ▸ Modelos, "
        "(2) atualizar o motor local, ou (3) usar um provedor de nuvem. Se o problema "
        "persistir, o log do motor (%LOCALAPPDATA%\\Ollama\\server.log no Windows, "
        "~/.ollama/logs/server.log no macOS) mostra a causa exata."
    )


def friendly_model_error(model: str, exc: Exception) -> Optional[str]:
    """One actionable sentence for "your account can't use this model" failures, or None."""
    local = friendly_local_engine_error(model, exc)
    if local:
        return local
    text = str(exc).lower()
    no_access = (
        f"Your account doesn't have access to {model} — new models can roll out "
        "gradually or require a plan upgrade. Pick a different model, or check "
        "the provider's console for availability."
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
