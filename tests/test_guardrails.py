"""Guarda-corpos locais: protetor de segredos, Modo Cofre e freio de gastos."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from mangaba.guardrails import PLACEHOLDER, DailyTurnBudget, redact_secrets
from mangaba.server.app import create_app
from mangaba.server.manager import SessionManager


# -- protetor de segredos --------------------------------------------------------


def test_redige_chaves_conhecidas_e_conta():
    texto = (
        "minha chave é sk-abc123def456ghi789jkl012 e o token do slack é "
        "xoxb-1234567890-abcdefghij"
    )
    saida, n = redact_secrets(texto)
    assert n == 2
    assert "sk-abc123" not in saida and "xoxb-" not in saida
    assert saida.count(PLACEHOLDER) == 2


def test_rediga_bloco_de_chave_privada_inteiro():
    pem = (
        "-----BEGIN RSA PRIVATE KEY-----\n"
        "MIIEowIBAAKCAQEA1234567890\nlinha2\n"
        "-----END RSA PRIVATE KEY-----"
    )
    saida, n = redact_secrets(f"segue a chave:\n{pem}\nvaleu")
    assert n == 1
    assert "BEGIN RSA" not in saida and "linha2" not in saida
    assert "valeu" in saida


def test_rediga_atribuicoes_de_senha_preservando_a_chave():
    saida, n = redact_secrets('DB_PASSWORD="hunter2hunter2" e senha: abc12345xyz')
    assert n == 2
    assert "hunter2" not in saida and "abc12345xyz" not in saida
    # o NOME da variável sobrevive — o modelo ainda entende o contexto
    assert "DB_PASSWORD" in saida.upper() or "password" in saida.lower()


def test_texto_inocente_passa_intacto():
    texto = "resuma o relatório de vendas do trimestre, focando em SP e no RJ"
    saida, n = redact_secrets(texto)
    assert n == 0 and saida == texto


def test_github_e_aws_e_jwt():
    texto = (
        "ghp_abcdefghij1234567890KLMNOP "
        "AKIAIOSFODNN7EXAMPLE "
        "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dozjgNryP4J3jVmNHl0w5N_XgL0n3I9P"
    )
    _, n = redact_secrets(texto)
    assert n == 3


# -- freio de gastos ---------------------------------------------------------------


def test_freio_zero_e_ilimitado():
    b = DailyTurnBudget(0)
    for _ in range(50):
        assert b.try_spend() is None
    assert b.used_today == 50


def test_freio_bloqueia_no_teto_com_mensagem_em_pt():
    b = DailyTurnBudget(2)
    assert b.try_spend() is None and b.try_spend() is None
    msg = b.try_spend()
    assert msg and "Freio de gastos" in msg and "2" in msg
    assert b.used_today == 2  # a recusa não consome


# -- endpoints ---------------------------------------------------------------------

TOKEN = {"x-mangaba-token": "tok"}


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("MANGABA_STATE_DIR", str(tmp_path))
    monkeypatch.setenv("MANGABA_API_TOKEN", "tok")
    return TestClient(create_app(SessionManager()))


def test_settings_expoe_e_persiste_os_guarda_corpos(client):
    s = client.get("/v1/settings", headers=TOKEN).json()
    assert s["vault_mode"] is False
    assert s["secret_guard"] is True  # ligado por padrão
    assert s["daily_turn_limit"] == 0

    assert client.post(
        "/v1/settings/vault-mode", json={"value": True}, headers=TOKEN
    ).json()["vault_mode"]
    assert client.post(
        "/v1/settings/daily-turn-limit", json={"value": 25}, headers=TOKEN
    ).json()["daily_turn_limit"] == 25

    s = client.get("/v1/settings", headers=TOKEN).json()
    assert s["vault_mode"] is True and s["daily_turn_limit"] == 25


def test_teto_invalido_recusa_em_pt(client):
    out = client.post(
        "/v1/settings/daily-turn-limit", json={"value": "muito"}, headers=TOKEN
    ).json()
    assert not out["ok"] and "número" in out["error"]


def test_somente_mangaba_barra_provedor_de_terceiro(tmp_path, monkeypatch):
    """O modo já significou "100% local, nada sai desta máquina" — promessa que valia quando
    os modelos rodavam na própria máquina. Servidos pelo gateway, ela deixaria de ser verdade;
    o que ele garante hoje, e só o que diz, é que nenhum provedor de terceiro é usado."""
    monkeypatch.setenv("MANGABA_STATE_DIR", str(tmp_path))
    manager = SessionManager()
    manager.set_vault_mode(True)
    bloqueio = manager.vault_block("anthropic:claude-opus-4-8")
    assert bloqueio and "Somente Mangaba" in bloqueio
    assert "nada sai desta máquina" not in bloqueio  # não promete o que não cumpre
    assert manager.vault_block("mangaba:mangaba-chat") is None
    manager.set_vault_mode(False)
    assert manager.vault_block("anthropic:claude-opus-4-8") is None


def test_diagnostics_e_local_e_completo(client):
    d = client.get("/v1/diagnostics", headers=TOKEN).json()
    for chave in ("version", "python", "uptime_seconds", "state_dir", "model", "turn_budget"):
        assert chave in d
    assert d["secret_guard"] is True


def test_export_de_sessao_vira_markdown(client):
    out = client.get("/v1/sessions/qualquer-id/export", headers=TOKEN).json()
    assert out["ok"] and out["markdown"].startswith("# ")


# -- GUI embutida (modo Docker) ----------------------------------------------------


def test_gui_embutida_serve_estaticos_sem_token_mas_api_continua_trancada(
    tmp_path, monkeypatch
):
    gui = tmp_path / "gui-dist"
    gui.mkdir()
    (gui / "index.html").write_text("<title>Mangaba</title>", "utf-8")
    monkeypatch.setenv("MANGABA_STATE_DIR", str(tmp_path / "estado"))
    monkeypatch.setenv("MANGABA_API_TOKEN", "tok")
    monkeypatch.setenv("MANGABA_GUI_DIST", str(gui))
    client = TestClient(create_app(SessionManager()))

    # A interface abre sem credencial nenhuma (é o mesmo bundle público do Vite)…
    pagina = client.get("/")
    assert pagina.status_code == 200 and "Mangaba" in pagina.text
    # …mas a API continua exigindo o token do sidecar.
    assert client.get("/v1/agents").status_code == 401
    assert client.get("/v1/agents", headers=TOKEN).status_code == 200
