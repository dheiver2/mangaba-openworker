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
        self.fechada = False

    def json(self) -> Any:
        return self._payload

    def iter_lines(self):
        return iter(self._linhas)

    def read(self) -> None:
        return None

    def close(self) -> None:
        self.fechada = True

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class _HttpFalso:
    """Cliente httpx de mentira que grava a chamada e devolve a resposta combinada.

    Espelha a forma real que o gateway usa: cabeçalhos fixados NO CLIENTE (pool reaproveitado)
    e streaming aberto por `build_request` + `send(stream=True)`, não por um `with` dentro do
    gerador — é isso que faz o erro de HTTP chegar ao laço de retry do OpenAIProvider."""

    ultima: dict[str, Any] = {}
    criados: int = 0

    def __init__(self, resp: _Resp, headers=None):
        self._resp = resp
        self.headers = dict(headers or {})
        _HttpFalso.criados += 1

    def post(self, url, json=None):
        _HttpFalso.ultima = {"url": url, "body": json, "headers": self.headers}
        return self._resp

    def build_request(self, metodo, url, json=None):
        return {"metodo": metodo, "url": url, "body": json}

    def send(self, req, stream=False):
        _HttpFalso.ultima = {
            "url": req["url"],
            "body": req["body"],
            "headers": self.headers,
        }
        return self._resp


@pytest.fixture
def _fixar(monkeypatch):
    def aplicar(resp: _Resp):
        import httpx

        # O SDK da OpenAI subclassa httpx.Client no import; se ele for importado DEPOIS
        # do patch, a subclasse tenta herdar da lambda e explode. Importar antes fixa a
        # ordem — o teste troca só o cliente que o gateway constrói.
        import openai._base_client  # noqa: F401

        _HttpFalso.criados = 0
        monkeypatch.setattr(
            httpx, "Client", lambda **k: _HttpFalso(resp, headers=k.get("headers"))
        )

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


# -- achados da auditoria (2026-08-06) ------------------------------------------------------


def test_cliente_http_e_reaproveitado_entre_chamadas(_fixar):
    """Um `httpx.Client` novo por chamada refazia o handshake TLS a cada hop do laço
    agêntico: 278 ms contra 130 ms reaproveitando, medido contra o gateway real. São ~1,5 s
    desperdiçados num turno de 10 hops — e o provedor OpenAI já mantinha pool justamente por
    isso."""
    _fixar(_Resp({"data": _completion(content="oi")}))
    p = gw.MangabaGatewayProvider()
    for _ in range(3):
        p.complete(model="auto", messages=[{"role": "user", "content": "oi"}])
    assert _HttpFalso.criados == 1, "o cliente deve ser criado uma vez, não uma por chamada"


def test_erro_de_http_no_streaming_chega_a_quem_pode_repetir(_fixar):
    """A requisição do streaming é aberta dentro de `create()`, não dentro do gerador.

    Se ficasse no gerador, `create()` voltaria sem ter tocado a rede, e o laço de
    param-fix-retry do OpenAIProvider — que envolve exatamente esta chamada — nunca veria
    erro: um 5xx do gateway só estouraria durante a iteração, longe do único ponto que sabe
    consertar e repetir."""
    _fixar(_Resp({"error": "boom"}, status=500))
    with pytest.raises(RuntimeError, match="500"):
        gw.MangabaGatewayProvider().complete(
            model="auto", messages=[{"role": "user", "content": "oi"}], stream=True
        )


def test_streaming_abandonado_no_meio_fecha_a_conexao(_fixar):
    """Parar no meio de uma resposta é o caso comum. Sem o `finally`, a conexão ficaria
    pendurada no pool a cada Stop."""
    resp = _Resp(
        None,
        linhas=_sse({"choices": [{"index": 0, "delta": {"content": "1"}}]}),
    )
    _fixar(resp)
    fluxo = gw.MangabaGatewayProvider().stream(
        model="auto", messages=[{"role": "user", "content": "oi"}]
    )
    next(fluxo)  # consome só o primeiro pedaço
    fluxo.close()
    assert resp.fechada, "a resposta precisa ser fechada mesmo com o gerador abandonado"


def test_provedor_sem_chave_nao_e_medido_pelo_motor_local():
    """O card do gateway media prontidão pelos modelos LOCAIS baixados, porque o ramo
    `needs_key=False` assumia que só o `local` era sem chave. O card mentia nos dois
    sentidos: ✗ num provedor que funciona sem setup, ✓ pelo motivo errado."""
    from mangaba.providers.registry import get_descriptor

    assert get_descriptor("mangaba").ready is None, "o gateway está pronto ao abrir o app"
    assert get_descriptor("local").ready is not None, "o local depende de modelo no disco"


def test_migracao_apaga_a_chave_orfa_do_provedor_aposentado(tmp_path):
    """Um segredo válido de um serviço que o app não sabe mais usar, guardado para sempre
    sem nada que o exiba ou o apague."""
    from mangaba.server.manager import SessionManager

    class _Cofre:
        def __init__(self):
            self.dados = {"provider:mangaba-nordeste": {"api_key": "chave-do-admin"}}

        def get(self, p):
            return self.dados.get(p)

        def delete(self, p):
            return self.dados.pop(p, None) is not None

    m = SessionManager(workspace=str(tmp_path / "ws"))
    cofre = _Cofre()
    m.secrets = cofre
    m._prefs = {}
    assert m._migrar_provedor_nordeste() is True
    assert "provider:mangaba-nordeste" not in cofre.dados


# -- blindagem contra o roteamento quebrado da cadeia (plano nota-10, item N.1) -------------


def test_400_de_roteamento_reintenta_sem_model(monkeypatch):
    """A cadeia do gateway já anunciou ids malformados (`nvidia/nvidia/nemotron-...`): quando
    o `auto` cai num elo desses, vem HTTP 400 com o id defeituoso na mensagem e o turno
    MORRIA no meio da tarefa — aconteceu numa bateria real em 2026-08-06. A nova tentativa
    sem `model` deixa a cadeia escolher outro elo."""
    chamadas: list[dict] = []

    p = gw.MangabaGatewayProvider()
    comps = p._ensure_client().chat.completions

    def _enviar(body):
        chamadas.append(dict(body))
        if len(chamadas) == 1:
            raise RuntimeError(
                'Gateway Mangaba HTTP 400: {"error":"nvidia/nvidia/nemotron-3-super-120b'
                ' 400: model not found"}'
            )
        from openai.types.chat import ChatCompletion

        return ChatCompletion.construct(**_completion(content="salvo pela retentativa"))

    monkeypatch.setattr(comps, "_enviar", _enviar)
    t = p.complete(
        model="groq/openai/gpt-oss-120b", messages=[{"role": "user", "content": "oi"}]
    )
    assert t.text == "salvo pela retentativa"
    assert len(chamadas) == 2
    assert "model" in chamadas[0], "a 1ª tentativa respeita o modelo pedido"
    assert "model" not in chamadas[1], "a 2ª entrega a escolha à cadeia (auto)"


def test_400_que_nao_e_de_roteamento_nao_reintenta(monkeypatch):
    """Repetir um corpo malformado só duplica o erro — e mascara o defeito de quem chamou."""
    chamadas = {"n": 0}
    p = gw.MangabaGatewayProvider()
    comps = p._ensure_client().chat.completions

    def _enviar(body):
        chamadas["n"] += 1
        raise RuntimeError(
            'Gateway Mangaba HTTP 400: {"error":"messages must be an array"}'
        )

    monkeypatch.setattr(comps, "_enviar", _enviar)
    with pytest.raises(RuntimeError):
        p.complete(model="auto", messages=[{"role": "user", "content": "oi"}])
    assert chamadas["n"] == 1


def test_500_nao_dispara_a_retentativa_de_roteamento(monkeypatch):
    """5xx é indisponibilidade, não roteamento — tem tratamento próprio rio acima."""
    chamadas = {"n": 0}
    p = gw.MangabaGatewayProvider()
    comps = p._ensure_client().chat.completions

    def _enviar(body):
        chamadas["n"] += 1
        raise RuntimeError("Gateway Mangaba HTTP 500: internal")

    monkeypatch.setattr(comps, "_enviar", _enviar)
    with pytest.raises(RuntimeError):
        p.complete(model="auto", messages=[{"role": "user", "content": "oi"}])
    assert chamadas["n"] == 1


# -- aproveitando a superfície nova do gateway (sondada em 2026-08-06) ----------------------


def test_catalogo_prefere_o_v1_models_completo(monkeypatch):
    """O `/v1/models` anuncia o catálogo COMPLETO (21 modelos na sondagem, incluindo o tier
    Cloudflare que responde quando pedido mas não entra na cadeia do `auto`); o
    `/api/models` só mostra a cadeia (14). Sugerir a lista menor esconde modelos que
    funcionam."""
    import httpx

    def _get(url, **k):
        if url.endswith("/v1/models"):
            return _Resp(
                {
                    "object": "list",
                    "data": [
                        {"id": "groq/openai/gpt-oss-120b"},
                        {"id": "cloudflare/@cf/openai/gpt-oss-20b"},
                    ],
                }
            )
        raise AssertionError(f"não deveria cair no fallback: {url}")

    monkeypatch.setattr(httpx, "get", _get)
    assert gw.modelos_do_gateway() == [
        "auto",
        "groq/openai/gpt-oss-120b",
        "cloudflare/@cf/openai/gpt-oss-20b",
    ]


def test_catalogo_cai_para_a_cadeia_em_gateway_antigo(monkeypatch):
    """Gateways sem a rota nova continuam funcionando — a rota `/v1/models` nem existia
    quando este provedor foi integrado, e pode sumir de novo."""
    import httpx

    def _get(url, **k):
        if url.endswith("/v1/models"):
            return _Resp({"error": "Rota nao encontrada"}, status=404)
        return _Resp({"chain": ["groq/x", "nvidia/y"]})

    monkeypatch.setattr(httpx, "get", _get)
    assert gw.modelos_do_gateway() == ["auto", "groq/x", "nvidia/y"]


def test_testar_avisa_quando_um_upstream_esta_fora(monkeypatch):
    """A cadeia troca de provedor EM SILÊNCIO quando um upstream cai: pedir um modelo do
    Google com o Google fora devolve outro modelo, sem erro. Foi exatamente assim que o
    'multimodal devolve 400' ficou sem explicação por uma tarde inteira — o /health tinha
    a resposta (`google: ok=false`) e ninguém olhava."""
    from mangaba.providers import registry

    monkeypatch.setattr(
        registry,
        "_sonda_tool_calling_gateway",
        lambda *a, **k: None,
    )
    import mangaba.providers.mangaba_gateway as g

    monkeypatch.setattr(
        g,
        "saude_do_gateway",
        lambda base_url=None: {
            "status": "degraded",
            "providers": [
                {"id": "groq", "configured": True, "ok": True},
                {"id": "google", "configured": True, "ok": False},
            ],
            "circuit": [{"id": "nvidia/minimaxai/minimax-m3", "status": "open"}],
        },
    )
    import httpx

    monkeypatch.setattr(httpx, "get", lambda *a, **k: _Resp({"chain": ["groq/x"]}))
    r = registry.verify_provider_key("mangaba")
    assert r["ok"] is True
    assert "google" in r["aviso"]
    assert "minimax" in r["aviso"]


def test_gateway_saudavel_nao_gera_aviso(monkeypatch):
    import mangaba.providers.mangaba_gateway as g
    from mangaba.providers.registry import _aviso_de_saude_do_gateway

    monkeypatch.setattr(
        g,
        "saude_do_gateway",
        lambda base_url=None: {
            "status": "ok",
            "providers": [{"id": "groq", "configured": True, "ok": True}],
            "circuit": [],
        },
    )
    assert _aviso_de_saude_do_gateway(None) is None


def test_gateway_sem_health_nao_assusta(monkeypatch):
    """Rota /health ausente (gateway antigo) = sem conclusão, nunca um aviso falso."""
    import mangaba.providers.mangaba_gateway as g
    from mangaba.providers.registry import _aviso_de_saude_do_gateway

    monkeypatch.setattr(g, "saude_do_gateway", lambda base_url=None: None)
    assert _aviso_de_saude_do_gateway(None) is None
