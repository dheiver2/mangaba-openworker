"""Gateway Mangaba — provedor de nuvem SEM CHAVE, o mesmo para todo mundo que instala.

Substitui o "Mangaba Nordeste", que exigia uma chave-cliente gerada à mão no Swagger do
gateway (`/docs → /admin/keys`): na prática ninguém que instalava o app conseguia usar o
provedor sem falar com o admin. Este aqui é aberto — `needs_key=False`, zero configuração.

A única diferença em relação a um endpoint OpenAI-compatível comum é o transporte:

- a rota é `POST /api/chat`, não `POST /v1/chat/completions`;
- a resposta NÃO-streaming vem embrulhada em `{"provider": …, "model": …, "data": {…}}`,
  onde `data` é um `chat.completion` OpenAI legítimo;
- a resposta em streaming já é SSE OpenAI cru (sem embrulho nenhum).

Por isso não dá para usar `_compat()`/`OpenAIProvider` direto. Em vez de duplicar todo o
parsing (tool calls, salvamento de tool call em texto, reasoning, streaming acumulado),
plugamos um cliente-sombra com a MESMA forma que o SDK expõe — `.chat.completions.create()`
devolvendo `ChatCompletion` / iterador de `ChatCompletionChunk` — e herdamos de
`OpenAIProvider` sobrescrevendo só `_ensure_client`. Tudo o mais é código já testado.

Modelo `auto` (o recomendado): o campo `model` é OMITIDO do corpo, e aí o gateway usa a
própria cadeia de fallback (`GET /api/models` → `chain`) — se o primeiro provedor está fora
do ar ou sem cota, ele cai para o próximo sozinho. Escolher um modelo específico desliga
esse failover, o que é uma troca consciente, não um bug.

Agenticidade verificada contra o gateway real em 2026-08-06: `tools` no corpo, `tool_calls`
na resposta, mensagens `role:"tool"` aceitas na volta, e `tool_calls` também no streaming.

Por que `.construct()` e não `.model_validate()`: a cadeia inclui a Groq, que devolve
`service_tier: "on_demand"` — valor fora do `Literal` do SDK, e a validação estrita rejeita
a resposta INTEIRA por causa de um campo que não lemos. `construct` monta os modelos
aninhados do mesmo jeito, sem validar; é o mesmo caminho que o próprio SDK usa.
"""

from __future__ import annotations

import json
from typing import Any, Iterator, Optional

from .openai_provider import OpenAIProvider

DEFAULT_BASE_URL = "https://mangaba-chat-gw.ngrok.app"
CHAT_PATH = "/api/chat"
MODELS_PATH = "/api/models"

#: Pseudo-modelo que entrega a escolha (e o failover) ao gateway.
AUTO_MODEL = "auto"

# A cadeia inclui modelos grandes atrás de provedores gratuitos com fila; o primeiro token
# pode demorar. Timeout de conexão curto (ngrok fora do ar falha rápido), leitura longa.
_TIMEOUT_CONNECT = 10.0
_TIMEOUT_READ = 300.0


def _payload(kwargs: dict[str, Any]) -> dict[str, Any]:
    body = {k: v for k, v in kwargs.items() if v is not None}
    model = body.pop("model", None)
    if model and model != AUTO_MODEL:
        body["model"] = model
    return body


# `ngrok-skip-browser-warning` evita a interstitial HTML do túnel gratuito, que chegaria
# aqui como JSON inválido. Sem Authorization: o provedor é sem chave por definição, e um
# header desses só poderia carregar a chave de OUTRO provedor para um endpoint de terceiro.
_CABECALHOS = {
    "Content-Type": "application/json",
    "ngrok-skip-browser-warning": "1",
}


class _Completions:
    """A superfície `client.chat.completions` que o `OpenAIProvider` consome."""

    def __init__(self, base_url: str) -> None:
        self._url = base_url.rstrip("/") + CHAT_PATH
        self._http: Any = None

    def _cliente(self) -> Any:
        """Cliente com pool, criado uma vez. Um `httpx.Client` novo por chamada refazia o
        handshake TLS a cada hop: medido em 2026-08-06, 278 ms contra 130 ms reaproveitando
        — 148 ms jogados fora por chamada, ~1,5 s num laço agêntico de 10 hops."""
        if self._http is None:
            import httpx

            self._http = httpx.Client(
                timeout=httpx.Timeout(_TIMEOUT_READ, connect=_TIMEOUT_CONNECT),
                limits=httpx.Limits(max_keepalive_connections=10, keepalive_expiry=120.0),
                headers=_CABECALHOS,
            )
        return self._http

    def create(self, **kwargs: Any) -> Any:
        body = _payload(kwargs)
        try:
            return self._enviar(body)
        except RuntimeError as exc:
            # Failover de roteamento QUEBRADO do próprio gateway. A cadeia dele já anunciou
            # ids malformados com prefixo duplicado (`nvidia/nvidia/nemotron-...`, visto em
            # 2026-08-06): quando o `auto` cai num desses elos, o gateway devolve HTTP 400
            # com o id defeituoso na mensagem — e sem isto o turno MORRIA no meio da tarefa
            # por um defeito que não é do app nem do usuário. Uma nova tentativa costuma
            # cair num elo são; se o usuário fixou um modelo e ELE é o quebrado, repetimos
            # em `auto`, porque uma resposta de outro modelo é melhor que turno morto.
            if not _erro_de_roteamento(exc):
                raise
            corpo2 = {k: v for k, v in body.items() if k != "model"}
            return self._enviar(corpo2)

    def _enviar(self, body: dict[str, Any]) -> Any:
        http = self._cliente()
        if body.get("stream"):
            # A requisição é ABERTA aqui, não dentro do gerador. Se ficasse lá, o
            # `create()` devolveria um gerador sem ter tocado a rede — e o laço de
            # param-fix-retry do OpenAIProvider, que envolve exatamente esta chamada,
            # nunca veria erro nenhum: um 5xx do gateway só estouraria durante a
            # iteração, longe do único ponto que sabe consertar e repetir.
            resp = http.send(
                http.build_request("POST", self._url, json=body), stream=True
            )
            if resp.status_code >= 400:
                resp.read()
                resp.close()
                _raise_for_status(resp)
            return self._chunks(resp)

        resp = http.post(self._url, json=body)
        _raise_for_status(resp)
        data = resp.json()
        # Embrulho do gateway; um `chat.completion` cru também é aceito, caso ele mude.
        if isinstance(data, dict) and isinstance(data.get("data"), dict):
            data = data["data"]
        from openai.types.chat import ChatCompletion

        return ChatCompletion.construct(**data)

    def _chunks(self, resp: Any) -> Iterator[Any]:
        from openai.types.chat import ChatCompletionChunk

        try:
            for line in resp.iter_lines():
                if not line or not line.startswith("data:"):
                    continue
                payload = line[5:].strip()
                if not payload or payload == "[DONE]":
                    continue
                try:
                    obj = json.loads(payload)
                except json.JSONDecodeError:
                    continue
                if isinstance(obj, dict) and isinstance(obj.get("data"), dict):
                    obj = obj["data"]
                if not isinstance(obj, dict) or "choices" not in obj:
                    continue
                yield ChatCompletionChunk.construct(**obj)
        finally:
            # Fecha mesmo se quem consome abandonar o gerador no meio (Parar no meio de uma
            # resposta é o caso comum) — senão a conexão fica pendurada no pool.
            resp.close()


def _erro_de_roteamento(exc: Exception) -> bool:
    """O 400 veio do roteamento da cadeia (id de modelo inválido), e não do NOSSO corpo?

    A distinção importa: repetir um corpo malformado só duplica o erro, mas repetir quando o
    gateway escolheu um elo defeituoso resolve. A mensagem do gateway carrega o id que ele
    tentou (`{"error":"nvidia/nvidia/... 400: ..."}`), então 400 + cara de id de modelo na
    mensagem = roteamento."""
    texto = str(exc)
    if "HTTP 400" not in texto:
        return False
    baixo = texto.lower()
    return (
        "model" in baixo
        or "não encontrado" in baixo
        or "not found" in baixo
        or "/" in texto.split("400", 1)[-1]  # ids de modelo têm barra (org/nome)
    )


def _raise_for_status(resp: Any) -> None:
    """Erro com a mensagem do gateway no texto — `_param_fix_retry` decide o retry lendo
    a string da exceção, então ela precisa carregar o que o servidor de fato reclamou."""
    if resp.status_code < 400:
        return
    detalhe = (resp.text or "")[:400]
    raise RuntimeError(f"Gateway Mangaba HTTP {resp.status_code}: {detalhe}")


class _Chat:
    def __init__(self, base_url: str) -> None:
        self.completions = _Completions(base_url)


class _GatewayClient:
    def __init__(self, base_url: str) -> None:
        self.chat = _Chat(base_url)


class MangabaGatewayProvider(OpenAIProvider):
    """`OpenAIProvider` falando com `/api/chat` em vez de `/v1/chat/completions`."""

    def __init__(self, base_url: Optional[str] = None) -> None:
        super().__init__(default_model=AUTO_MODEL)
        self._gateway_base = (base_url or "").strip().rstrip("/") or DEFAULT_BASE_URL

    def _ensure_client(self) -> Any:
        if self._client is None:
            self._client = _GatewayClient(self._gateway_base)
        return self._client


def modelos_do_gateway(base_url: Optional[str] = None) -> list[str]:
    """Modelos anunciados pelo gateway, com `auto` na frente. Nunca levanta: alimenta um
    datalist de sugestões, e ficar sem sugestão é melhor do que quebrar a tela."""
    import httpx

    base = (base_url or "").strip().rstrip("/") or DEFAULT_BASE_URL
    try:
        resp = httpx.get(
            base + MODELS_PATH,
            headers={"ngrok-skip-browser-warning": "1"},
            timeout=10.0,
        )
        if resp.status_code >= 300:
            return [AUTO_MODEL]
        dados = resp.json() or {}
        cadeia = [m for m in (dados.get("chain") or []) if isinstance(m, str)]
    except Exception:
        return [AUTO_MODEL]
    return list(dict.fromkeys([AUTO_MODEL, *cadeia]))
