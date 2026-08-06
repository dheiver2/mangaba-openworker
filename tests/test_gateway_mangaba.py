"""Transporte do gateway Mangaba — a parte que NÃO é OpenAI-compatível.

Este provedor existe para que quem instala o app tenha IA na nuvem sem gerar chave. O preço
disso é um transporte próprio, e é exatamente aí que mora o risco de regressão:

- a rota é `POST /api/chat`, não `/v1/chat/completions`;
- a resposta não-streaming vem embrulhada em `{"provider", "model", "data"}`;
- a resposta em streaming é SSE OpenAI cru, sem embrulho;
- a Groq devolve `service_tier: "on_demand"`, fora do `Literal` do SDK — validação estrita
  rejeitaria a resposta INTEIRA por um campo que nem lemos.

Cada um desses pontos tem um teste. O parsing de tool calls, reasoning e streaming acumulado
é herdado do `OpenAIProvider` e já é coberto por tests/test_openai_provider.py — aqui só
provamos que o que chega até ele tem a forma certa.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from mangaba.providers import mangaba_gateway as gw


class _Resp:
    def __init__(self, payload: Any, status: int = 200, linhas: list[str] | None = None):
        self._payload = payload
        self.status_code = status
        self._linhas = linhas or []
        self.text = json.dumps(payload) if payload is not None else ""

    def json(self) -> Any:
        return self._payload

    def iter_lines(self):
        return iter(self._linhas)

    def read(self) -> None:
        return None

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class _HttpFalso:
    """Cliente httpx de mentira que grava a chamada e devolve a resposta combinada."""

    ultima: dict[str, Any] = {}

    def __init__(self, resp: _Resp):
        self._resp = resp

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def post(self, url, json=None, headers=None):
        _HttpFalso.ultima = {"url": url, "body": json, "headers": headers}
        return self._resp

    def stream(self, metodo, url, json=None, headers=None):
        _HttpFalso.ultima = {"url": url, "body": json, "headers": headers}
        return self._resp


@pytest.fixture
def _fixar(monkeypatch):
    def aplicar(resp: _Resp):
        import httpx

        # O SDK da OpenAI subclassa httpx.Client no import; se ele for importado DEPOIS
        # do patch, a subclasse tenta herdar da lambda e explode. Importar antes fixa a
        # ordem — o teste troca só o cliente que o gateway constrói.
        import openai._base_client  # noqa: F401

        monkeypatch.setattr(httpx, "Client", lambda **k: _HttpFalso(resp))

    _HttpFalso.ultima = {}
    return aplicar


def _completion(**msg: Any) -> dict[str, Any]:
    return {
        "id": "x",
        "object": "chat.completion",
        "created": 1,
        "model": "openai/gpt-oss-120b",
        # o valor que a validação estrita do SDK rejeita
        "service_tier": "on_demand",
        "choices": [{"index": 0, "finish_reason": "stop", "message": {"role": "assistant", **msg}}],
    }


# -- rota e corpo ---------------------------------------------------------------------------


def test_bate_em_api_chat_e_nao_em_v1_chat_completions(_fixar):
    _fixar(_Resp({"provider": "groq", "data": _completion(content="oi")}))
    gw.MangabaGatewayProvider().complete(model="auto", messages=[{"role": "user", "content": "oi"}])
    assert _HttpFalso.ultima["url"] == gw.DEFAULT_BASE_URL + "/api/chat"


def test_modelo_auto_e_omitido_para_o_gateway_escolher(_fixar):
    """`auto` não é um id de modelo — é a instrução de deixar a cadeia de fallback do
    gateway agir. Se o campo `model` vazar no corpo, o failover morre."""
    _fixar(_Resp({"data": _completion(content="oi")}))
    gw.MangabaGatewayProvider().complete(model="auto", messages=[{"role": "user", "content": "oi"}])
    assert "model" not in _HttpFalso.ultima["body"]


def test_modelo_explicito_vai_no_corpo(_fixar):
    _fixar(_Resp({"data": _completion(content="oi")}))
    gw.MangabaGatewayProvider().complete(
        model="groq/openai/gpt-oss-20b", messages=[{"role": "user", "content": "oi"}]
    )
    assert _HttpFalso.ultima["body"]["model"] == "groq/openai/gpt-oss-20b"


def test_sem_cabecalho_de_autorizacao(_fixar):
    """O provedor é sem chave por definição. Um Authorization aqui só poderia vir de uma
    chave de OUTRO provedor vazando para um endpoint de terceiro."""
    _fixar(_Resp({"data": _completion(content="oi")}))
    gw.MangabaGatewayProvider().complete(model="auto", messages=[{"role": "user", "content": "oi"}])
    assert "Authorization" not in _HttpFalso.ultima["headers"]
    # e o túnel gratuito não pode devolver a página de aviso do ngrok no lugar do JSON
    assert _HttpFalso.ultima["headers"]["ngrok-skip-browser-warning"] == "1"


def test_endpoint_do_perfil_substitui_o_padrao(_fixar):
    _fixar(_Resp({"data": _completion(content="oi")}))
    gw.MangabaGatewayProvider(base_url="https://meu-gw.exemplo/").complete(
        model="auto", messages=[{"role": "user", "content": "oi"}]
    )
    assert _HttpFalso.ultima["url"] == "https://meu-gw.exemplo/api/chat"


# -- embrulho e validação -------------------------------------------------------------------


def test_desembrulha_o_envelope_do_gateway(_fixar):
    _fixar(_Resp({"provider": "groq", "model": "m", "data": _completion(content="olá")}))
    t = gw.MangabaGatewayProvider().complete(
        model="auto", messages=[{"role": "user", "content": "oi"}]
    )
    assert t.text == "olá" and t.finish_reason == "stop"


def test_aceita_resposta_crua_sem_envelope(_fixar):
    """Se o gateway um dia devolver o `chat.completion` direto, nada quebra."""
    _fixar(_Resp(_completion(content="olá")))
    t = gw.MangabaGatewayProvider().complete(
        model="auto", messages=[{"role": "user", "content": "oi"}]
    )
    assert t.text == "olá"


def test_service_tier_da_groq_nao_derruba_a_resposta(_fixar):
    """`service_tier: "on_demand"` está fora do Literal do SDK. Com `model_validate` a
    resposta INTEIRA seria rejeitada por um campo que não lemos — por isso `construct`."""
    _fixar(_Resp({"data": _completion(content="passou")}))
    t = gw.MangabaGatewayProvider().complete(
        model="auto", messages=[{"role": "user", "content": "oi"}]
    )
    assert t.text == "passou"


def test_tool_calls_chegam_parseadas(_fixar):
    _fixar(
        _Resp(
            {
                "data": _completion(
                    tool_calls=[
                        {
                            "id": "c1",
                            "type": "function",
                            "function": {
                                "name": "obter_clima",
                                "arguments": '{"cidade":"Maceió"}',
                            },
                        }
                    ]
                )
            }
        )
    )
    t = gw.MangabaGatewayProvider().complete(
        model="auto",
        messages=[{"role": "user", "content": "clima?"}],
        tools=[{"type": "function", "function": {"name": "obter_clima"}}],
    )
    assert [(c.name, c.arguments) for c in t.tool_calls] == [
        ("obter_clima", {"cidade": "Maceió"})
    ]


def test_erro_http_carrega_a_mensagem_do_gateway(_fixar):
    _fixar(_Resp({"error": "Rota nao encontrada"}, status=404))
    with pytest.raises(RuntimeError, match="404"):
        gw.MangabaGatewayProvider().complete(
            model="auto", messages=[{"role": "user", "content": "oi"}]
        )


# -- streaming ------------------------------------------------------------------------------


def _sse(*objs: dict[str, Any]) -> list[str]:
    return [f"data: {json.dumps(o)}" for o in objs] + ["data: [DONE]"]


def test_streaming_le_sse_openai_cru(_fixar):
    linhas = _sse(
        {"choices": [{"index": 0, "delta": {"content": "1,"}}]},
        {"choices": [{"index": 0, "delta": {"content": " 2"}}], "x_groq": {"id": "r"}},
        {"choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]},
    )
    _fixar(_Resp(None, linhas=linhas))
    pedacos = list(
        gw.MangabaGatewayProvider().stream(
            model="auto", messages=[{"role": "user", "content": "conte"}]
        )
    )
    assert [p.text_delta for p in pedacos if p.text_delta] == ["1,", " 2"]
    assert _HttpFalso.ultima["body"]["stream"] is True
    final = pedacos[-1].turn
    assert final.text == "1, 2" and final.finish_reason == "stop"


def test_streaming_ignora_linhas_de_ruido(_fixar):
    """Comentários de keep-alive, `[DONE]` e JSON truncado não podem derrubar o turno."""
    linhas = [
        ": keep-alive",
        "",
        "data: {nao-e-json",
        'data: {"sem":"choices"}',
        'data: {"choices":[{"index":0,"delta":{"content":"ok"},"finish_reason":"stop"}]}',
        "data: [DONE]",
    ]
    _fixar(_Resp(None, linhas=linhas))
    pedacos = list(
        gw.MangabaGatewayProvider().stream(
            model="auto", messages=[{"role": "user", "content": "oi"}]
        )
    )
    assert pedacos[-1].turn.text == "ok"


# -- catálogo de modelos --------------------------------------------------------------------


def test_modelos_do_gateway_poe_auto_na_frente(monkeypatch):
    import httpx

    monkeypatch.setattr(
        httpx,
        "get",
        lambda *a, **k: _Resp({"chain": ["google/gemini-2.5-flash", "groq/x"]}),
    )
    assert gw.modelos_do_gateway() == ["auto", "google/gemini-2.5-flash", "groq/x"]


def test_modelos_do_gateway_fora_do_ar_ainda_oferece_auto(monkeypatch):
    """Sugestão de modelo não pode quebrar a tela de Configurações se o túnel cair."""
    import httpx

    def _boom(*a, **k):
        raise httpx.ConnectError("down")

    monkeypatch.setattr(httpx, "get", _boom)
    assert gw.modelos_do_gateway() == ["auto"]


# -- migração de quem já usava o provedor antigo --------------------------------------------


def test_prefs_com_o_provedor_antigo_sao_migradas(tmp_path, monkeypatch):
    """Quem já usava o `mangaba-nordeste` não pode virar cliente involuntário da OpenAI.

    O roteador manda todo modelo com prefixo DESCONHECIDO para o provedor padrão. Com o
    `mangaba-nordeste` fora do registro, o modelo preferido dessa pessoa viraria uma chamada
    cobrada na chave da OpenAI — ou um erro sem explicação. A migração acontece ao abrir."""
    import json

    from mangaba.server.manager import SessionManager

    monkeypatch.setenv("MANGABA_DATA_DIR", str(tmp_path))
    prefs = tmp_path / "prefs.json"
    prefs.write_text(
        json.dumps(
            {
                "default_model": "mangaba-nordeste:Mangaba-Nordeste-30B",
                "models": ["mangaba-nordeste:outro", "openai:gpt-5.6-sol"],
            }
        ),
        encoding="utf-8",
    )

    m = SessionManager(workspace=str(tmp_path / "ws"))
    if m._prefs.get("default_model") != "mangaba:auto":
        # O manager pode guardar prefs em outro caminho neste ambiente; então exercitamos a
        # migração direto, que é a unidade sob teste.
        m._prefs = json.loads(prefs.read_text(encoding="utf-8"))
        m._migrar_provedor_nordeste()

    assert m._prefs["default_model"] == "mangaba:auto"
    assert not [x for x in m._prefs["models"] if x.startswith("mangaba-nordeste:")]
    assert "openai:gpt-5.6-sol" in m._prefs["models"], "os outros modelos ficam de pé"


def test_migracao_nao_mexe_em_quem_nao_usava(tmp_path):
    from mangaba.server.manager import SessionManager

    m = SessionManager(workspace=str(tmp_path / "ws"))
    m._prefs = {"default_model": "anthropic:claude-opus-5", "models": ["local:qwen3-4b"]}
    assert m._migrar_provedor_nordeste() is False
    assert m._prefs == {"default_model": "anthropic:claude-opus-5", "models": ["local:qwen3-4b"]}


def test_nenhum_modelo_do_gateway_declara_visao():
    """MEDIDO em 2026-08-06, não presumido: o gateway TROCA o modelo em silêncio.

    Pedindo `google/gemini-2.5-flash` explicitamente, a resposta voltou como
    `openai/gpt-oss-120b` — e mandar `content` multimodal devolveu HTTP 400
    ("messages[0].content must be a string"). Ou seja, escolher modelo aqui é melhor
    esforço, não garantia.

    Se alguém declarar `vision=True` numa entrada `mangaba:`, o app passa a anexar imagem
    numa conversa que vai receber 400 — e o usuário vê o erro cru, sem entender por quê.
    Para imagem existe o provedor local ou um provedor com chave própria."""
    from mangaba.providers.matrix import MATRIX

    do_gateway = {k: v for k, v in MATRIX.items() if k.startswith("mangaba:")}
    assert do_gateway, "o gateway precisa continuar no catálogo"
    assert not [k for k, v in do_gateway.items() if v.caps.vision or v.caps.pdf]


def test_todo_elo_do_gateway_faz_tool_calling():
    """A cadeia inteira foi sondada em 2026-08-06 e os 14 elos devolveram `tool_calls`.

    Isto é o que sustenta declarar `tools=True` no `auto`: como o gateway pode trocar o
    modelo no meio, basta UM elo sem tool calling para o agente virar um chat que inventa
    o resultado da ferramenta. O catálogo só pode prometer o que vale para todos."""
    from mangaba.providers.matrix import MATRIX

    do_gateway = {k: v for k, v in MATRIX.items() if k.startswith("mangaba:")}
    assert all(v.caps.tools for v in do_gateway.values())
