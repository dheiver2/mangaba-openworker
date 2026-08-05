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


def test_gateway_da_organizacao_avisa_quando_nao_executa_ferramenta(monkeypatch):
    """Chave válida NÃO garante agente. O gateway anterior deste projeto aceitava o
    parâmetro `tools` e nunca devolvia `tool_calls` — e o modelo, em vez de falhar,
    INVENTAVA o resultado (pedimos uma listagem de arquivos e ele escreveu uma saída de
    `ls` que nunca rodou). O 'Testar' é o único momento em que a pessoa está olhando."""
    import httpx

    class RespModelos:
        status_code = 200

        def json(self):
            return {"data": [{"id": "mangaba-chat"}]}

    class RespSemToolCalls:
        status_code = 200

        def json(self):
            # aceita `tools`, responde texto — o caso perigoso
            return {"choices": [{"message": {"content": "O clima em Maceió é ensolarado."}}]}

    monkeypatch.setattr(httpx, "get", lambda *a, **k: RespModelos())
    monkeypatch.setattr(httpx, "post", lambda *a, **k: RespSemToolCalls())

    res = verify_provider_key(
        "mangaba-nordeste", api_key="chave-do-admin", base_url="https://gw.exemplo/v1"
    )
    assert res["ok"] is True, "a chave é válida — não é erro"
    assert "aviso" in res, "mas o usuário precisa saber que não é agente"
    assert "inventar" in res["aviso"] or "ferramenta" in res["aviso"]


def test_gateway_da_organizacao_sem_aviso_quando_executa_ferramenta(monkeypatch):
    import httpx

    class RespModelos:
        status_code = 200

        def json(self):
            return {"data": [{"id": "mangaba-chat"}]}

    class RespComToolCalls:
        status_code = 200

        def json(self):
            return {
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
            }

    monkeypatch.setattr(httpx, "get", lambda *a, **k: RespModelos())
    monkeypatch.setattr(httpx, "post", lambda *a, **k: RespComToolCalls())

    res = verify_provider_key(
        "mangaba-nordeste", api_key="chave-do-admin", base_url="https://gw.exemplo/v1"
    )
    assert res["ok"] is True and "aviso" not in res


def test_descriptor_do_gateway_pede_chave_e_aponta_para_o_admin():
    from mangaba.providers.registry import get_descriptor

    d = get_descriptor("mangaba-nordeste")
    assert d is not None and d.needs_key is True
    campos = {f.key: f for f in d.fields}
    assert campos["api_key"].secret is True
    # a chave vem do administrador, não de um cadastro num site
    assert "/admin/keys" in campos["base_url"].help  # a chave sai do Swagger do gateway
