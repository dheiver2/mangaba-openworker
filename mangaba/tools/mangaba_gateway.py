"""Ferramentas servidas pelo gateway Mangaba — capacidades que o app não tinha.

O gateway expõe, além do chat compatível com OpenAI, endpoints especializados. Alguns viram
FERRAMENTAS do agente, e essa direção é deliberada: os modelos do próprio gateway não executam
chamada de ferramenta, mas os provedores agênticos (Claude, OpenAI, Gemini) executam — então
quem roda o agente num deles ganha estas capacidades **sem precisar de mais nenhuma chave**.

O que entrou e por quê:

- `gerar_imagem` — o app não gerava imagem de jeito nenhum. Capacidade nova, sem custo para
  o usuário, e o resultado é um arquivo no diretório da conversa, como qualquer artefato.

O que ficou de fora, e a razão (revisitar se mudar):

- `/audio/transcribe` — a entrada de voz já é local (sidecar `stt/`, em Rust). Trocá-la por
  uma chamada de rede pioraria privacidade e mataria o uso offline: seria mudança para pior.
- `/embeddings` — só valeria acoplada a uma busca semântica, que o app ainda não tem; e
  mandaria o texto das conversas para fora sem ganho visível hoje.
- `/moderate` — filtrar o que o usuário escreve na própria máquina não é serviço que ele pediu.
- `/vision/analyze` — imagens já são analisadas pelo caminho normal de chat, com o modelo que
  o usuário escolheu; um segundo caminho só dividiria o comportamento.
"""

from __future__ import annotations

import mimetypes
import time
from pathlib import Path
from typing import Any, Optional

import aisuite as ai

_TIMEOUT_IMAGEM = 180.0  # difusão é lenta; o teto existe para não pendurar o turno


def _base(secrets: Any) -> str:
    """Raiz do gateway (sem `/v1`): os endpoints especializados vivem na raiz."""
    from ..providers.registry import DEFAULT_MANGABA_URL

    perfil = {}
    try:
        perfil = secrets.get("provider:mangaba") or {}
    except Exception:
        pass
    base = (perfil.get("base_url") or DEFAULT_MANGABA_URL).strip().rstrip("/")
    return base[: -len("/v1")] if base.endswith("/v1") else base


def gateway_tools(secrets: Any, workspace: Optional[str] = None) -> list:
    """Ferramentas do gateway. `workspace` é onde a imagem gerada é salva."""

    def gerar_imagem(
        prompt: str, largura: int = 768, altura: int = 768, arquivo: str = ""
    ) -> dict:
        """Gera uma imagem a partir de uma descrição em texto e salva como arquivo PNG.
        Use para ilustrações, diagramas conceituais, mockups e imagens de apoio."""
        import httpx

        if not (prompt or "").strip():
            return {"erro": "descreva a imagem que você quer gerar"}
        destino = Path(workspace or ".").expanduser()
        destino.mkdir(parents=True, exist_ok=True)
        nome = (arquivo or "").strip() or f"imagem-{int(time.time())}.png"
        if not nome.lower().endswith(".png"):
            nome += ".png"
        # Nome de arquivo vem do modelo: só o nome final entra, nada de subir diretórios.
        caminho = destino / Path(nome).name

        try:
            resp = httpx.post(
                _base(secrets) + "/image/generate",
                data={"prompt": prompt, "width": int(largura), "height": int(altura)},
                timeout=_TIMEOUT_IMAGEM,
            )
        except Exception as exc:
            return {"erro": f"não consegui falar com o gateway ({exc.__class__.__name__})"}

        if resp.status_code >= 300:
            return {"erro": f"o gateway respondeu HTTP {resp.status_code}"}
        tipo = resp.headers.get("content-type", "")
        if not tipo.startswith("image/"):
            # Um túnel fora do ar devolve HTML com status 200 — salvar isso como .png
            # entregaria um "artefato" que não abre. Melhor falhar com a causa.
            return {"erro": f"o gateway não devolveu uma imagem (veio {tipo or 'algo desconhecido'})"}
        if ext := mimetypes.guess_extension(tipo.split(";")[0]):
            if ext not in (".png", ".jpe") and not nome.lower().endswith(ext):
                caminho = caminho.with_suffix(ext)

        caminho.write_bytes(resp.content)
        return {
            "arquivo": str(caminho),
            "bytes": len(resp.content),
            "prompt": prompt,
        }

    return [
        ai.tool(
            gerar_imagem,
            metadata=ai.ToolMetadata(
                category="media",
                risk_level="low",  # escreve um arquivo na pasta da própria conversa
                capabilities=["image"],
            ),
        )
    ]
