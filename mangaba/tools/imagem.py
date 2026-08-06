"""`ler_imagem` — o agente lê texto de uma imagem do workspace por conta própria.

Diferente do caminho de anexo (pdf_support.adapt_content), que só age sobre o que a pessoa
arrastou para a conversa, esta ferramenta cobre o caso em que a imagem já está no disco: um
print que o próprio agente tirou, uma nota fiscal numa pasta, um lote de comprovantes a
conferir. Sem ela, um agente rodando nos provedores sem chave (ambos de texto puro) sabe que
o arquivo existe, sabe o nome — e não tem como olhar dentro.

O que ela devolve é OCR, não descrição de cena: texto de documento, print de erro, slide,
etiqueta. "Quantas pessoas aparecem na foto?" continua exigindo um provedor com visão. O
retorno diz isso em texto quando não acha nada, para o agente não concluir que a imagem está
vazia quando na verdade ele é que não tem olhos.

Read-only e presa ao workspace, como `read_file`.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import aisuite as ai

_EXTENSOES = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff"}
_MAX_BYTES = 20 * 1024 * 1024

_SCHEMA = {
    "type": "function",
    "function": {
        "name": "ler_imagem",
        "description": (
            "Extract text from an image file in the workspace using local OCR (screenshots, "
            "scanned documents, invoices, slides, labels). Works with text-only models that "
            "have no vision. Returns the recognized text plus format and dimensions. It does "
            "NOT describe scenes, objects or colors — that needs a vision-capable provider."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Image path, relative to the workspace.",
                }
            },
            "required": ["path"],
        },
    },
}


def image_tools(workspace: str) -> list:
    root = Path(workspace).resolve()

    def ler_imagem(path: str) -> dict[str, Any]:
        alvo = (root / path).resolve()
        try:
            alvo.relative_to(root)  # mesma cerca do read_file
        except ValueError:
            return {"error": "path escapes the workspace"}
        if not alvo.is_file():
            return {"error": f"not a file: {path}"}
        if alvo.suffix.lower() not in _EXTENSOES:
            return {
                "error": f"not an image ({alvo.suffix or 'sem extensão'}); "
                f"supported: {', '.join(sorted(_EXTENSOES))}"
            }
        tamanho = alvo.stat().st_size
        if tamanho > _MAX_BYTES:
            return {"error": f"image too large ({tamanho} bytes; limit {_MAX_BYTES})"}

        from .. import ocr

        if not ocr.disponivel():
            # Erro acionável em vez de "não achei texto": as duas coisas levariam o agente a
            # conclusões opostas sobre o conteúdo do arquivo.
            return {
                "error": (
                    "local OCR is not installed — run `pip install 'mangaba[ocr]'`, "
                    "or switch to a vision-capable provider (Claude, Gemini, OpenAI)."
                )
            }
        try:
            dados = alvo.read_bytes()
        except OSError as exc:
            return {"error": f"read failed: {exc}"}

        info = ocr.descrever_imagem(dados)
        resultado: dict[str, Any] = {
            "path": str(alvo.relative_to(root)),
            "format": info.get("formato"),
            "width": info.get("largura"),
            "height": info.get("altura"),
        }
        texto = info.get("texto")
        if texto:
            resultado["text"] = texto
        else:
            resultado["text"] = ""
            resultado["note"] = (
                "OCR found no text in this image. It may be a photo, a diagram without "
                "labels, or too low-resolution. Describing what the image SHOWS (objects, "
                "people, colors) requires a vision-capable provider — this tool only reads text."
            )
        return resultado

    ler_imagem.__name__ = "ler_imagem"
    ler_imagem.__doc__ = _SCHEMA["function"]["description"]
    ler_imagem.__aisuite_tool_metadata__ = ai.ToolMetadata(
        name="ler_imagem",
        category="filesystem",
        risk_level="low",
        capabilities=["read"],
        requires_approval=False,
    )
    ler_imagem.__mangaba_schema__ = _SCHEMA
    return [ler_imagem]
