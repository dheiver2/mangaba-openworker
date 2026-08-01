"""Guarda-corpos locais: protetor de segredos, Modo Cofre e freio de gastos.

Três diferenciais do Mangaba frente aos assistentes de nuvem, todos aplicados
NA MÁQUINA, antes de qualquer coisa sair dela:

- ``redact_secrets``  — remove chaves de API, tokens e chaves privadas da
  mensagem do usuário antes de ela chegar ao modelo. Colar um ``.env`` numa
  conversa não pode virar vazamento para um provedor de nuvem.
- Somente Mangaba    — ligado, só os modelos da própria Mangaba podem
  rodar; a checagem fica no servidor, então nem uma UI alterada contorna.
- Freio de gastos    — teto diário de turnos iniciados pelo usuário; quando o
  modelo é pago por token, um laço descontrolado tem custo real.
"""

from __future__ import annotations

import re
from datetime import date

# Padrões de credenciais reais, dos formatos publicados pelos provedores. A ordem
# importa: os blocos multi-linha (chave privada) vêm antes dos tokens curtos para
# o placeholder não picotar um PEM no meio.
_SECRET_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    (
        "chave privada",
        re.compile(
            r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----",
            re.S,
        ),
    ),
    ("chave OpenAI", re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b")),
    ("chave Anthropic", re.compile(r"\bsk-ant-[A-Za-z0-9_-]{20,}\b")),
    ("token GitHub", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b")),
    ("token GitHub (fine-grained)", re.compile(r"\bgithub_pat_[A-Za-z0-9_]{30,}\b")),
    ("token Slack", re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b")),
    ("chave AWS", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("chave Google", re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b")),
    ("token Hugging Face", re.compile(r"\bhf_[A-Za-z0-9]{30,}\b")),
    ("token Telegram", re.compile(r"\b\d{8,10}:AA[A-Za-z0-9_-]{30,}\b")),
    ("JWT", re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b")),
    (
        "senha em atribuição",
        # password=..., senha: "..." — só quando o valor tem cara de segredo (8+ sem espaço).
        # aceita prefixo de variável (DB_PASSWORD, STRIPE_SECRET…): "_" é caractere de
        # palavra, então um \b puro não casaria depois dele.
        re.compile(r"(?i)\b([A-Za-z0-9_]*(?:password|passwd|senha|api[_-]?key|secret|token))\s*[=:]\s*['\"]?([^\s'\"]{8,})"),
    ),
]

PLACEHOLDER = "[SEGREDO REMOVIDO PELO MANGABA]"


def redact_secrets(text: str) -> tuple[str, int]:
    """Substitui credenciais por um placeholder. Devolve (texto, quantos achou)."""
    if not text:
        return text, 0
    count = 0

    for label, pattern in _SECRET_PATTERNS:
        if label == "senha em atribuição":
            def _keep_key(m: re.Match[str]) -> str:
                nonlocal count
                count += 1
                return f"{m.group(1)}={PLACEHOLDER}"

            text, n = pattern.subn(_keep_key, text)
        else:
            text, n = pattern.subn(PLACEHOLDER, text)
            count += n
    return text, count


class DailyTurnBudget:
    """Contador de turnos do dia. ``limit`` 0 = sem teto. Só turnos iniciados
    pelo usuário contam — as iterações internas de um turno não."""

    def __init__(self, limit: int = 0) -> None:
        self.limit = max(0, int(limit))
        self._day = date.today().isoformat()
        self._count = 0

    def _roll(self) -> None:
        today = date.today().isoformat()
        if today != self._day:
            self._day = today
            self._count = 0

    @property
    def used_today(self) -> int:
        self._roll()
        return self._count

    def try_spend(self) -> str | None:
        """Registra um turno; devolve a mensagem de recusa quando o teto estourou."""
        self._roll()
        if self.limit and self._count >= self.limit:
            return (
                f"Freio de gastos: você já usou os {self.limit} turnos de hoje. "
                "Aumente ou desligue o teto em Configurações ▸ Privacidade e limites."
            )
        self._count += 1
        return None

    def snapshot(self) -> dict[str, int]:
        self._roll()
        return {"limit": self.limit, "used_today": self._count}
