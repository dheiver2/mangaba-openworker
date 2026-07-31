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
    """Diagnóstico da falha do motor local, com os dados DESTA máquina.

    A primeira versão desta mensagem só explicava a falha em tese, e quem a lia continuava
    sem saber o que fazer — tinha de ir atrás da memória da máquina e do log por conta
    própria. As duas causas conhecidas se distinguem por um número que o app já sabe: se a
    memória não comporta o modelo mais o cache de contexto, é falta de RAM; senão, é o
    formato de chamada de ferramenta. Medimos e dizemos qual é."""
    if _PARSE_DO_MOTOR not in str(exc):
        return None

    from . import local_engine as le

    ram = le.total_ram_gb()
    contexto = le.contexto_para_a_maquina(ram or None)
    versao = le.engine_version()
    tag = model.split(":", 1)[-1] if model.startswith("ollama:") else model

    # Cache de contexto de um modelo pequeno (~4B, Q4) mais os pesos. É uma estimativa
    # grosseira de propósito: serve para escolher a hipótese principal, não para prever
    # a alocação exata do motor.
    precisa_gb = round(2.5 + contexto * 0.00015, 1)
    livre_estimado = ram - 3.0 if ram else 0.0  # ~3 GB ficam com o sistema

    linhas = [f"O motor local falhou ao responder com o {tag}.", ""]
    detalhes = []
    if ram:
        detalhes.append(f"{ram:.0f} GB de RAM")
    detalhes.append(f"contexto de {contexto} tokens")
    if versao:
        detalhes.append(f"motor {versao}")
    linhas.append("Esta máquina: " + " · ".join(detalhes))
    linhas.append("")

    if ram and livre_estimado < precisa_gb:
        linhas += [
            f"Causa provável: MEMÓRIA. Este modelo com este contexto precisa de cerca de "
            f"{precisa_gb} GB, e sobram por volta de {max(livre_estimado, 0):.0f} GB depois "
            "do sistema. Quando não cabe, o motor morre no meio e devolve uma resposta "
            "quebrada — que é este erro.",
            "",
            "O que resolve, em ordem:",
            "1. Escolher um modelo menor em Configurações ▸ Modelos",
            "2. Fechar outros programas pesados (navegador com muitas abas, por exemplo)",
            "3. Usar um provedor de nuvem (OpenAI, Claude, Gemini…) em vez do local",
        ]
    else:
        linhas += [
            "Causa provável: FORMATO. A versão do motor e o formato de chamada de "
            "ferramenta deste modelo não se entendem — o motor tenta ler como JSON algo "
            "que o modelo escreveu em XML.",
            "",
            "O que resolve, em ordem:",
            "1. Trocar de modelo em Configurações ▸ Modelos (o Qwen 2.5 7B e o Llama 3.1 "
            "usam o formato que o motor lê sem problema)",
            "2. Atualizar o motor local",
            "3. Usar um provedor de nuvem",
        ]

    linhas += [
        "",
        "O log do motor mostra a causa exata: %LOCALAPPDATA%\\Ollama\\server.log "
        "(Windows) ou ~/.ollama/logs/server.log (macOS).",
    ]
    return "\n".join(linhas)


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
