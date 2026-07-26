"""A senha local: gate humano por cima do token do sidecar."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from mangaba.passcode import PasscodeGuard, validate_passcode
from mangaba.server.app import create_app
from mangaba.server.manager import SessionManager

TOKEN = {"x-mangaba-token": "tok"}


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("MANGABA_STATE_DIR", str(tmp_path))
    monkeypatch.setenv("MANGABA_API_TOKEN", "tok")
    return TestClient(create_app(SessionManager()))


def test_sem_senha_definida_o_app_segue_aberto(client):
    # Primeira execução: nada a destravar ainda, senão o usuário ficaria de fora
    # do próprio app sem ter como criar a senha.
    assert client.get("/v1/auth/status", headers=TOKEN).json() == {
        "configured": False,
        "authenticated": False,
        "locked_for": 0,
    }
    assert client.get("/v1/agents", headers=TOKEN).status_code == 200


def test_setup_define_a_senha_e_ja_devolve_a_sessao(client):
    out = client.post(
        "/v1/auth/setup", json={"passcode": "mangaba123"}, headers=TOKEN
    ).json()
    assert out["ok"] and out["session"]

    # Sem a sessão, o token sozinho não abre mais nada.
    assert client.get("/v1/agents", headers=TOKEN).status_code == 401
    body = client.get("/v1/agents", headers=TOKEN).json()
    assert body["code"] == "passcode_required"

    ok = {**TOKEN, "x-mangaba-session": out["session"]}
    assert client.get("/v1/agents", headers=ok).status_code == 200


def test_setup_recusa_senha_curta_e_redefinicao(client):
    curta = client.post("/v1/auth/setup", json={"passcode": "abc"}, headers=TOKEN).json()
    assert not curta["ok"] and "6 caracteres" in curta["error"]

    client.post("/v1/auth/setup", json={"passcode": "mangaba123"}, headers=TOKEN)
    de_novo = client.post(
        "/v1/auth/setup", json={"passcode": "outra-senha"}, headers=TOKEN
    ).json()
    assert not de_novo["ok"] and "já foi definida" in de_novo["error"]


def test_login_erra_bloqueia_e_acerta(client):
    client.post("/v1/auth/setup", json={"passcode": "mangaba123"}, headers=TOKEN)

    errado = client.post(
        "/v1/auth/login", json={"passcode": "nope"}, headers=TOKEN
    ).json()
    assert not errado["ok"] and errado["error"] == "senha incorreta"

    certo = client.post(
        "/v1/auth/login", json={"passcode": "mangaba123"}, headers=TOKEN
    ).json()
    assert certo["ok"] and certo["session"]


def test_cinco_erros_bloqueiam_temporariamente(client):
    client.post("/v1/auth/setup", json={"passcode": "mangaba123"}, headers=TOKEN)
    for _ in range(5):
        client.post("/v1/auth/login", json={"passcode": "nope"}, headers=TOKEN)

    # Mesmo com a senha CERTA o bloqueio vale — é o que torna a força bruta cara.
    out = client.post(
        "/v1/auth/login", json={"passcode": "mangaba123"}, headers=TOKEN
    ).json()
    assert not out["ok"] and out["locked_for"] > 0


def test_logout_invalida_apenas_aquela_sessao(client):
    a = client.post(
        "/v1/auth/setup", json={"passcode": "mangaba123"}, headers=TOKEN
    ).json()["session"]
    b = client.post(
        "/v1/auth/login", json={"passcode": "mangaba123"}, headers=TOKEN
    ).json()["session"]

    client.post("/v1/auth/logout", headers={**TOKEN, "x-mangaba-session": a})
    assert client.get("/v1/agents", headers={**TOKEN, "x-mangaba-session": a}).status_code == 401
    assert client.get("/v1/agents", headers={**TOKEN, "x-mangaba-session": b}).status_code == 200


def test_trocar_a_senha_exige_a_atual_e_derruba_as_outras_sessoes(client):
    a = client.post(
        "/v1/auth/setup", json={"passcode": "mangaba123"}, headers=TOKEN
    ).json()["session"]
    velha = client.post(
        "/v1/auth/login", json={"passcode": "mangaba123"}, headers=TOKEN
    ).json()["session"]

    recusada = client.post(
        "/v1/auth/change",
        json={"current": "errada", "passcode": "nova-senha"},
        headers={**TOKEN, "x-mangaba-session": a},
    ).json()
    assert not recusada["ok"] and "incorreta" in recusada["error"]

    out = client.post(
        "/v1/auth/change",
        json={"current": "mangaba123", "passcode": "nova-senha"},
        headers={**TOKEN, "x-mangaba-session": a},
    ).json()
    assert out["ok"] and out["session"]
    # A sessão antiga não sobrevive à troca.
    assert (
        client.get("/v1/agents", headers={**TOKEN, "x-mangaba-session": velha}).status_code
        == 401
    )
    assert client.post(
        "/v1/auth/login", json={"passcode": "nova-senha"}, headers=TOKEN
    ).json()["ok"]


def test_health_e_rotas_de_login_ficam_fora_do_gate(client):
    client.post("/v1/auth/setup", json={"passcode": "mangaba123"}, headers=TOKEN)
    assert client.get("/v1/health", headers=TOKEN).status_code == 200
    assert client.get("/v1/auth/status", headers=TOKEN).status_code == 200
    assert client.post(
        "/v1/auth/login", json={"passcode": "mangaba123"}, headers=TOKEN
    ).status_code == 200


def test_a_senha_em_claro_nunca_e_gravada(tmp_path, monkeypatch):
    monkeypatch.setenv("MANGABA_STATE_DIR", str(tmp_path))
    guard = PasscodeGuard()
    guard.set_passcode("segredo-do-dheiver")

    gravado = (tmp_path / "passcode.json").read_text("utf-8")
    assert "segredo-do-dheiver" not in gravado
    assert guard.verify("segredo-do-dheiver")
    assert not guard.verify("outra-coisa")


def test_validacao_de_tamanho():
    assert validate_passcode("12345")
    assert validate_passcode("123456") is None
