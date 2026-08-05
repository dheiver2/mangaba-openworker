#!/usr/bin/env python3
"""Verifica se um endpoint serve para ser provedor do Mangaba — e com quais capacidades.

Por que existe: "é compatível com a API da OpenAI" não quer dizer nada na prática. Vários
gateways aceitam o parâmetro `tools` sem reclamar e NUNCA devolvem `tool_calls` — em vez de
falhar, o modelo INVENTA o resultado (pedimos uma listagem de arquivos e ele escreveu uma
saída de `ls` que nunca rodou). Isso já aconteceu neste projeto e custou caro. A única forma
honesta de saber é exercitar o endpoint de verdade, que é o que este script faz.

Uso:
    python3 packaging/verificar_provedor.py \\
        --base-url https://api.exemplo.com/v1 \\
        --api-key sk-... \\
        --model nome-do-modelo

    # provedor local sem chave (llama-server, vLLM, LM Studio…)
    python3 packaging/verificar_provedor.py --base-url http://127.0.0.1:8778/v1 --model qwen3-4b

Saída: um relatório por requisito, e no fim o veredito — se dá para usar como provedor
agêntico pleno, só como chat, ou se não serve.
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any, Optional

try:
    import httpx
except ImportError:  # pragma: no cover
    print("instale httpx: pip install httpx", file=sys.stderr)
    raise SystemExit(2)


VERDE, VERMELHO, AMARELO, CINZA, FIM = "\033[32m", "\033[31m", "\033[33m", "\033[90m", "\033[0m"

FERRAMENTA_TESTE = {
    "type": "function",
    "function": {
        "name": "obter_clima",
        "description": "Retorna o clima atual de uma cidade.",
        "parameters": {
            "type": "object",
            "properties": {
                "cidade": {"type": "string", "description": "Nome da cidade"},
            },
            "required": ["cidade"],
        },
    },
}

DUAS_FERRAMENTAS = [
    FERRAMENTA_TESTE,
    {
        "type": "function",
        "function": {
            "name": "obter_populacao",
            "description": "Retorna a população de uma cidade.",
            "parameters": {
                "type": "object",
                "properties": {"cidade": {"type": "string"}},
                "required": ["cidade"],
            },
        },
    },
]


class Relatorio:
    def __init__(self) -> None:
        self.itens: list[tuple[str, str, str, bool]] = []  # (id, titulo, detalhe, essencial)
        self.resultados: dict[str, bool] = {}

    def registra(
        self, ident: str, titulo: str, ok: bool, detalhe: str = "", *, essencial: bool = True
    ) -> None:
        self.resultados[ident] = ok
        cor = VERDE if ok else (VERMELHO if essencial else AMARELO)
        marca = "PASSA" if ok else ("FALHA" if essencial else "não tem")
        print(f"  {cor}{marca:8s}{FIM} {titulo}")
        if detalhe:
            print(f"           {CINZA}{detalhe}{FIM}")
        self.itens.append((ident, titulo, detalhe, essencial))


def _post(base: str, key: Optional[str], corpo: dict[str, Any], *, stream: bool = False):
    headers = {"Content-Type": "application/json"}
    if key:
        headers["Authorization"] = f"Bearer {key}"
    url = base.rstrip("/") + "/chat/completions"
    if stream:
        return httpx.stream("POST", url, headers=headers, json=corpo, timeout=120)
    return httpx.post(url, headers=headers, json=corpo, timeout=120)


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--base-url", required=True, help="base OpenAI-compatível, terminando em /v1")
    p.add_argument("--api-key", default=None)
    p.add_argument("--model", required=True)
    a = p.parse_args()

    base, key, modelo = a.base_url.rstrip("/"), a.api_key, a.model
    r = Relatorio()

    print(f"\nVerificando {base}  ·  modelo {modelo}\n")

    # -- 1. catálogo de modelos ------------------------------------------------------
    # O app usa esta rota para validar a chave ANTES de salvar (o botão "Testar").
    print("Essenciais")
    try:
        resp = httpx.get(
            base + "/models",
            headers={"Authorization": f"Bearer {key}"} if key else {},
            timeout=30,
        )
        ok = resp.status_code < 300
        ids = [m.get("id") for m in (resp.json().get("data") or [])][:3] if ok else []
        r.registra("models", "GET /v1/models", ok, f"HTTP {resp.status_code}" + (f" · ex.: {', '.join(str(i) for i in ids)}" if ids else ""))
    except Exception as exc:
        r.registra("models", "GET /v1/models", False, str(exc)[:90])

    # -- 2. chat básico ---------------------------------------------------------------
    try:
        # max_tokens generoso de propósito: modelo de raciocínio (Qwen3, o1, R1) gasta os
        # primeiros tokens no bloco de pensamento, e um teto apertado devolve `content`
        # vazio num endpoint que está perfeitamente saudável — falso negativo que este
        # próprio script deu na primeira versão.
        resp = _post(base, key, {
            "model": modelo,
            "messages": [{"role": "user", "content": "Diga apenas: ok"}],
            "max_tokens": 512,
        })
        corpo = resp.json() if resp.status_code < 300 else {}
        escolha = (corpo.get("choices") or [{}])[0]
        msg = escolha.get("message", {}) or {}
        # Vale como resposta: texto, raciocínio, ou uma parada legítima por limite.
        respondeu = bool(
            msg.get("content")
            or msg.get("reasoning_content")
            or escolha.get("finish_reason") in {"stop", "length"}
        )
        ok = resp.status_code < 300 and respondeu
        motivo = escolha.get("finish_reason") or "?"
        r.registra("chat", "POST /v1/chat/completions", ok, f"HTTP {resp.status_code} · finish_reason={motivo}")
    except Exception as exc:
        r.registra("chat", "POST /v1/chat/completions", False, str(exc)[:90])

    # -- 3. tool calling NATIVO -------------------------------------------------------
    # O requisito que separa "chat" de "agente". Aceitar o parâmetro não basta: tem de
    # VOLTAR `tool_calls` estruturado. Endpoint que aceita e ignora é o pior caso — o
    # modelo inventa o resultado da ferramenta e a fabricação passa por trabalho feito.
    chamada: Optional[dict[str, Any]] = None
    try:
        resp = _post(base, key, {
            "model": modelo,
            "messages": [{"role": "user", "content": "Qual o clima em Maceió? Use a ferramenta."}],
            "tools": [FERRAMENTA_TESTE],
            "tool_choice": "auto",
        })
        corpo = resp.json()
        msg = (corpo.get("choices") or [{}])[0].get("message", {}) or {}
        tcs = msg.get("tool_calls") or []
        ok = bool(tcs) and bool(tcs[0].get("function", {}).get("name"))
        if ok:
            chamada = tcs[0]
            nome = tcs[0]["function"]["name"]
            args = tcs[0]["function"].get("arguments")
            r.registra("tools", "Tool calling nativo (devolve tool_calls)", True, f"{nome}({args})")
        else:
            texto = (msg.get("content") or "")[:70].replace("\n", " ")
            r.registra("tools", "Tool calling nativo (devolve tool_calls)", False,
                       f"aceitou `tools` mas não devolveu tool_calls · respondeu texto: {texto!r}")
    except Exception as exc:
        r.registra("tools", "Tool calling nativo (devolve tool_calls)", False, str(exc)[:90])

    # -- 4. volta do resultado da ferramenta ------------------------------------------
    # O laço agêntico é multi-turno: mandamos de volta a assistant com tool_calls e um
    # `role: "tool"` com o mesmo tool_call_id. Endpoint que rejeita esse formato trava
    # o agente na primeira ferramenta.
    if chamada:
        try:
            resp = _post(base, key, {
                "model": modelo,
                "messages": [
                    {"role": "user", "content": "Qual o clima em Maceió? Use a ferramenta."},
                    {"role": "assistant", "content": None, "tool_calls": [chamada]},
                    {"role": "tool", "tool_call_id": chamada.get("id", ""), "content": "32 graus, ensolarado"},
                ],
                "tools": [FERRAMENTA_TESTE],
            })
            ok = resp.status_code < 300 and bool(
                (resp.json().get("choices") or [{}])[0].get("message", {}).get("content")
            )
            r.registra("tool_result", "Aceita o resultado de volta (role=tool + tool_call_id)", ok, f"HTTP {resp.status_code}")
        except Exception as exc:
            r.registra("tool_result", "Aceita o resultado de volta (role=tool + tool_call_id)", False, str(exc)[:90])
    else:
        r.registra("tool_result", "Aceita o resultado de volta (role=tool + tool_call_id)", False, "não testável sem tool_calls")

    # -- 5. streaming -----------------------------------------------------------------
    try:
        pedacos = 0
        with _post(base, key, {"model": modelo, "messages": [{"role": "user", "content": "Conte de 1 a 5."}], "stream": True, "max_tokens": 60}, stream=True) as s:
            for linha in s.iter_lines():
                if linha and str(linha).startswith("data: ") and "[DONE]" not in str(linha):
                    pedacos += 1
        r.registra("stream", "Streaming (SSE com deltas)", pedacos > 1, f"{pedacos} eventos")
    except Exception as exc:
        r.registra("stream", "Streaming (SSE com deltas)", False, str(exc)[:90])

    # -- 6. streaming + ferramenta ----------------------------------------------------
    # O app SEMPRE streama. Um endpoint que devolve tool_calls no modo normal mas não no
    # streaming quebra só em produção — por isso é teste separado.
    try:
        viu = False
        with _post(base, key, {
            "model": modelo,
            "messages": [{"role": "user", "content": "Qual o clima em Maceió? Use a ferramenta."}],
            "tools": [FERRAMENTA_TESTE], "stream": True,
        }, stream=True) as s:
            for linha in s.iter_lines():
                t = str(linha)
                if t.startswith("data: ") and "[DONE]" not in t and "tool_calls" in t:
                    viu = True
                    break
        r.registra("stream_tools", "Tool calling DENTRO do streaming", viu,
                   "" if viu else "devolve tool_calls sem stream, mas não com stream — o app sempre streama")
    except Exception as exc:
        r.registra("stream_tools", "Tool calling DENTRO do streaming", False, str(exc)[:90])

    # -- janela de contexto REAL --------------------------------------------------------
    # Anúncio não é medida. Um gateway já declarou `context_window: 32768` servindo 8192
    # (o `-c` do llama-server é dividido entre os slots de `--parallel`), e confiar no
    # anúncio fez a compactação nunca disparar: o turno morria num 400 cru. Aqui a janela
    # é sondada de verdade, com prompts crescentes até o endpoint recusar.
    print("\nJanela de contexto (medida, não a anunciada)")
    anunciada = None
    try:
        dados = httpx.get(
            base + "/models",
            headers={"Authorization": f"Bearer {key}"} if key else {},
            timeout=30,
        ).json()
        for m in dados.get("data") or []:
            if m.get("id") == modelo:
                anunciada = m.get("context_window") or m.get("max_context_length")
    except Exception:
        pass

    medida_min = None
    for alvo in (4_000, 8_000, 16_000, 32_000):
        try:
            resp = _post(base, key, {
                "model": modelo,
                "messages": [{"role": "user", "content": "palavra " * int(alvo * 0.95)}],
                "max_tokens": 5,
            })
            if resp.status_code == 400 and "context" in resp.text.lower():
                break
            if resp.status_code < 300:
                medida_min = alvo
            else:
                break
        except Exception:
            break  # timeout num prompt grande é latência, não limite — paramos aqui

    if medida_min:
        detalhe = f"aceitou ~{medida_min:,} tokens"
        if anunciada:
            detalhe += f" · anunciada: {anunciada:,}"
            if medida_min < int(anunciada) * 0.5:
                detalhe += "  ← DIVERGE do anúncio"
        r.registra("janela", "Janela de contexto", True, detalhe, essencial=False)
        if anunciada and medida_min < int(anunciada) * 0.5:
            print(f"           {AMARELO}Declare a MEDIDA em providers/matrix.py, não a anunciada.{FIM}")
            print(f"           {CINZA}Dica: no llama-server o `-c` é dividido entre os slots de --parallel.{FIM}")
    else:
        r.registra("janela", "Janela de contexto", False,
                   "não consegui medir (timeout ou recusa cedo)", essencial=False)

    # -- opcionais ---------------------------------------------------------------------
    print("\nOpcionais (o app funciona sem, com menos recursos)")

    try:
        resp = _post(base, key, {
            "model": modelo,
            "messages": [{"role": "user", "content": "Clima e população de Maceió? Use as duas ferramentas."}],
            "tools": DUAS_FERRAMENTAS,
        })
        n = len(((resp.json().get("choices") or [{}])[0].get("message", {}) or {}).get("tool_calls") or [])
        r.registra("paralelo", "Várias ferramentas numa resposta (paralelo)", n > 1, f"{n} chamada(s)", essencial=False)
    except Exception as exc:
        r.registra("paralelo", "Várias ferramentas numa resposta (paralelo)", False, str(exc)[:90], essencial=False)

    px = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
    try:
        resp = _post(base, key, {
            "model": modelo,
            "messages": [{"role": "user", "content": [
                {"type": "text", "text": "Que cor é esta imagem?"},
                {"type": "image_url", "image_url": {"url": px}},
            ]}],
            "max_tokens": 30,
        })
        r.registra("visao", "Visão (aceita image_url)", resp.status_code < 300, f"HTTP {resp.status_code}", essencial=False)
    except Exception as exc:
        r.registra("visao", "Visão (aceita image_url)", False, str(exc)[:90], essencial=False)

    # -- veredito -----------------------------------------------------------------------
    g = r.resultados
    base_ok = g.get("models") and g.get("chat") and g.get("stream")
    agentico = base_ok and g.get("tools") and g.get("tool_result") and g.get("stream_tools")

    print()
    if agentico:
        print(f"{VERDE}VEREDITO: serve como provedor agêntico pleno.{FIM}")
        print("  Todas as capacidades funcionam: arquivos, shell, conectores, MCP, artefatos e automações.")
        cap = "tools=True"
        if g.get("paralelo"):
            cap += ", parallel_tool_calls=True"
        if g.get("visao"):
            cap += ", vision=True"
        print(f"  Declare em providers/capabilities.py: {CINZA}{cap}{FIM}")
    elif base_ok:
        print(f"{AMARELO}VEREDITO: serve só para CONVERSA, não para agente.{FIM}")
        print("  Sem tool calling nativo o agente não lê arquivo, não roda comando e não usa conector.")
        print("  Declare tools=False — o motor então CALA as ferramentas em vez de deixar o modelo")
        print("  inventar o resultado delas (foi o que aconteceu com o gateway antigo deste projeto).")
    else:
        print(f"{VERMELHO}VEREDITO: não serve como provedor.{FIM}")
        print("  Os requisitos essenciais de base (models, chat, streaming) não passaram.")

    print()
    return 0 if agentico else (1 if base_ok else 2)


if __name__ == "__main__":
    raise SystemExit(main())
