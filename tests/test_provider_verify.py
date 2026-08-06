"""Tests for provider key detection + the live (read-only) Test/verify path. SDK-free: the
single httpx.get is monkeypatched so no network is touched."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from mangaba.providers import detect_provider, verify_provider_key


# -- detect_provider ------------------------------------------------------------
@pytest.mark.parametrize(
    "key,expected",
    [
        ("sk-ant-api03-abc", "anthropic"),
        ("AIzaSyAbc123", "gemini"),
        ("sk-proj-abc", "openai"),
        ("sk_live_abc", "openai"),
        ("", None),
        ("   ", None),
        ("nonsense", None),
    ],
)
def test_detect_provider(key, expected):
    assert detect_provider(key) == expected


# -- verify_provider_key: status-code mapping + per-provider request shape -------
def _patch_get(monkeypatch, status=200, capture=None, raise_exc=None):
    def fake_get(url, **kwargs):
        if capture is not None:
            capture["url"] = url
            capture.update(kwargs)
        if raise_exc is not None:
            raise raise_exc
        return SimpleNamespace(status_code=status)

    monkeypatch.setattr("httpx.get", fake_get)


def test_verify_openai_ok(monkeypatch):
    cap: dict = {}
    _patch_get(monkeypatch, status=200, capture=cap)
    assert verify_provider_key("openai", api_key="sk-x") == {"ok": True}
    assert cap["url"] == "https://api.openai.com/v1/models"
    assert cap["headers"]["Authorization"] == "Bearer sk-x"


def test_verify_openai_custom_endpoint(monkeypatch):
    cap: dict = {}
    _patch_get(monkeypatch, status=200, capture=cap)
    verify_provider_key(
        "openai", api_key="sk-x", base_url="https://gw.example/openai/v1/"
    )
    # trailing slash trimmed, /models appended to the custom endpoint
    assert cap["url"] == "https://gw.example/openai/v1/models"


def test_verify_bad_key_is_invalid(monkeypatch):
    _patch_get(monkeypatch, status=401)
    assert verify_provider_key("openai", api_key="sk-bad") == {
        "ok": False,
        "error": "Invalid API key.",
    }


def test_verify_anthropic_headers(monkeypatch):
    cap: dict = {}
    _patch_get(monkeypatch, status=200, capture=cap)
    verify_provider_key("anthropic", api_key="sk-ant-x")
    assert cap["url"] == "https://api.anthropic.com/v1/models"
    assert cap["headers"]["x-api-key"] == "sk-ant-x"
    assert "anthropic-version" in cap["headers"]


def test_verify_gemini_key_param(monkeypatch):
    cap: dict = {}
    _patch_get(monkeypatch, status=200, capture=cap)
    verify_provider_key("gemini", api_key="AIza-x")
    assert cap["params"]["key"] == "AIza-x"


def test_verify_network_error_is_clean(monkeypatch):
    _patch_get(monkeypatch, raise_exc=ConnectionError("boom"))
    res = verify_provider_key("openai", api_key="sk-x")
    assert res["ok"] is False
    assert "Couldn't reach" in res["error"]


def test_verify_unexpected_status(monkeypatch):
    _patch_get(monkeypatch, status=500)
    res = verify_provider_key("anthropic", api_key="sk-ant-x")
    assert res["ok"] is False
    assert "500" in res["error"]


def test_gateway_mangaba_avisa_quando_nao_executa_ferramenta(monkeypatch):
    """Alcançar o gateway NÃO garante agente. O gateway anterior deste projeto aceitava o
    parâmetro `tools` e nunca devolvia `tool_calls` — e o modelo, em vez de falhar,
    INVENTAVA o resultado (pedimos uma listagem de arquivos e ele escreveu uma saída de
    `ls` que nunca rodou). O 'Testar' é o único momento em que a pessoa está olhando."""
    import httpx

    class RespModelos:
        status_code = 200

        def json(self):
            return {"default": "google/gemini-2.5-flash", "chain": ["google/gemini-2.5-flash"]}

    class RespSemToolCalls:
        status_code = 200

        def json(self):
            # aceita `tools`, responde texto — o caso perigoso. Já no embrulho do gateway.
            return {
                "provider": "groq",
                "data": {"choices": [{"message": {"content": "Em Maceió faz sol."}}]},
            }

    monkeypatch.setattr(httpx, "get", lambda *a, **k: RespModelos())
    monkeypatch.setattr(httpx, "post", lambda *a, **k: RespSemToolCalls())

    res = verify_provider_key("mangaba")
    assert res["ok"] is True, "o gateway respondeu — não é erro"
    assert "aviso" in res, "mas o usuário precisa saber que não é agente"
    assert "ferramenta" in res["aviso"]


def test_gateway_mangaba_sem_aviso_quando_executa_ferramenta(monkeypatch):
    import httpx

    class RespModelos:
        status_code = 200

        def json(self):
            return {"chain": ["google/gemini-2.5-flash"]}

    class RespComToolCalls:
        status_code = 200

        def json(self):
            return {
                "provider": "groq",
                "data": {
                    "choices": [
                        {
                            "message": {
                                "tool_calls": [
                                    {
                                        "id": "c1",
                                        "function": {
                                            "name": "obter_clima",
                                            "arguments": '{"cidade":"Maceió"}',
                                        },
                                    }
                                ]
                            }
                        }
                    ]
                },
            }

    monkeypatch.setattr(httpx, "get", lambda *a, **k: RespModelos())
    monkeypatch.setattr(httpx, "post", lambda *a, **k: RespComToolCalls())

    res = verify_provider_key("mangaba")
    assert res["ok"] is True and "aviso" not in res


def test_gateway_mangaba_fora_do_ar_e_erro_nao_excecao(monkeypatch):
    """Túnel ngrok cai. Isso vira {ok: False} com texto legível, nunca um 500 na API."""
    import httpx

    def _boom(*a, **k):
        raise httpx.ConnectError("tunnel down")

    monkeypatch.setattr(httpx, "get", _boom)
    res = verify_provider_key("mangaba")
    assert res["ok"] is False and "gateway" in res["error"].lower()


def test_descriptor_do_gateway_nao_pede_chave():
    """A razão de existir deste provedor: quem instala o app usa IA na nuvem sem gerar
    chave nenhuma. Se `needs_key` voltar a ser True, o provedor perdeu o propósito."""
    from mangaba.providers.registry import get_descriptor

    d = get_descriptor("mangaba")
    assert d is not None and d.needs_key is False
    assert d.env_key is None, "não há chave de ambiente para um provedor sem chave"
    campos = {f.key: f for f in d.fields}
    assert "api_key" not in campos, "nenhum campo de chave na tela"
    # o endpoint continua editável (gateway próprio / túnel de teste), mas nunca obrigatório
    assert campos["base_url"].required is False and campos["base_url"].default
    assert d.recommended_model == "auto"


def test_provedor_mangaba_nordeste_saiu_de_cena():
    """Trocado pelo gateway sem chave em 2026-08-06. Se o nome voltar, alguém restaurou
    um provedor que ninguém que só instala o app conseguia usar."""
    from mangaba.providers.registry import get_descriptor, provider_names

    assert get_descriptor("mangaba-nordeste") is None
    assert "mangaba-nordeste" not in provider_names()
