"""Senha local de acesso — a segunda camada de autenticação da GUI.

O token do sidecar prova que a requisição veio de um processo com acesso de leitura ao
`state_dir` (mesmo usuário, mesma máquina). Isso não protege nada de quem já está sentado
na máquina destravada. A senha desta camada é o gate humano: sem ela, nenhuma rota /v1/*
responde, mesmo com o token correto.

Armazenamento: PBKDF2-HMAC-SHA256 (stdlib, sem dependência nova) com salt de 16 bytes e
480k iterações, gravado `0600` em `<state-dir>/passcode.json`. A senha em claro nunca é
persistida nem registrada em log.

Sessões vivem SÓ em memória: reiniciar o servidor exige a senha de novo — o comportamento
seguro por padrão, e o custo é um login por inicialização.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets as _secrets
import threading
import time
from pathlib import Path
from typing import Any

from .secrets import state_dir, write_private_text

_ITERATIONS = 480_000
_SALT_BYTES = 16
_SESSION_TTL = 12 * 60 * 60  # 12h — um dia de trabalho sem relogar
_MIN_LENGTH = 6

# Tentativas erradas seguidas antes do bloqueio temporário (defesa contra força bruta
# local; o gate é humano, então a janela é curta o bastante para não travar o dono).
_MAX_ATTEMPTS = 5
_LOCKOUT_SECONDS = 60


def passcode_path() -> Path:
    return state_dir() / "passcode.json"


def _hash(passcode: str, salt: bytes) -> str:
    dk = hashlib.pbkdf2_hmac("sha256", passcode.encode("utf-8"), salt, _ITERATIONS)
    return dk.hex()


def _read() -> dict[str, Any]:
    try:
        return json.loads(passcode_path().read_text("utf-8"))
    except Exception:
        return {}


class PasscodeGuard:
    """Estado da senha + sessões em memória. Uma instância por servidor."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._sessions: dict[str, float] = {}  # token -> expira em (epoch)
        self._failures = 0
        self._locked_until = 0.0

    # -- estado ----------------------------------------------------------------
    def configured(self) -> bool:
        """True quando já existe uma senha definida neste computador."""
        data = _read()
        return bool(data.get("hash") and data.get("salt"))

    def locked_for(self) -> int:
        """Segundos restantes de bloqueio por tentativas erradas (0 = liberado)."""
        remaining = self._locked_until - time.time()
        return int(remaining) if remaining > 0 else 0

    # -- definição / troca -----------------------------------------------------
    def set_passcode(self, passcode: str) -> None:
        salt = os.urandom(_SALT_BYTES)
        write_private_text(
            passcode_path(),
            json.dumps(
                {
                    "version": 1,
                    "algorithm": "pbkdf2_sha256",
                    "iterations": _ITERATIONS,
                    "salt": salt.hex(),
                    "hash": _hash(passcode, salt),
                },
                indent=2,
            )
            + "\n",
        )
        with self._lock:
            self._failures = 0
            self._locked_until = 0.0

    def verify(self, passcode: str) -> bool:
        data = _read()
        salt_hex, expected = data.get("salt", ""), data.get("hash", "")
        if not salt_hex or not expected:
            return False
        try:
            salt = bytes.fromhex(salt_hex)
        except ValueError:
            return False
        # Iterações vêm do arquivo para que um hash antigo continue verificável se o
        # custo padrão subir numa versão futura.
        iterations = int(data.get("iterations") or _ITERATIONS)
        dk = hashlib.pbkdf2_hmac(
            "sha256", passcode.encode("utf-8"), salt, iterations
        ).hex()
        return hmac.compare_digest(dk, expected)

    # -- sessões ---------------------------------------------------------------
    def login(self, passcode: str) -> str | None:
        """Valida a senha e devolve um token de sessão (None quando recusada)."""
        with self._lock:
            if self._locked_until > time.time():
                return None
        if not self.verify(passcode):
            with self._lock:
                self._failures += 1
                if self._failures >= _MAX_ATTEMPTS:
                    self._locked_until = time.time() + _LOCKOUT_SECONDS
                    self._failures = 0
            return None
        token = _secrets.token_urlsafe(32)
        with self._lock:
            self._failures = 0
            self._locked_until = 0.0
            self._sessions[token] = time.time() + _SESSION_TTL
        return token

    def authenticated(self, token: str) -> bool:
        if not token:
            return False
        now = time.time()
        with self._lock:
            expiry = self._sessions.get(token)
            if expiry is None:
                return False
            if expiry < now:
                self._sessions.pop(token, None)
                return False
            return True

    def logout(self, token: str) -> None:
        with self._lock:
            self._sessions.pop(token, None)

    def logout_all(self) -> None:
        with self._lock:
            self._sessions.clear()


def validate_passcode(passcode: str) -> str | None:
    """Regra mínima de senha. Devolve a mensagem de erro, ou None quando está OK."""
    if len(passcode) < _MIN_LENGTH:
        return f"a senha precisa ter pelo menos {_MIN_LENGTH} caracteres"
    return None
