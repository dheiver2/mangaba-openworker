"""OCR local — ler texto de imagem e de PDF escaneado sem modelo de visão.

Por que isto existe: os dois provedores que funcionam sem chave (Mangaba Local e o gateway
Mangaba na nuvem) são de TEXTO PURO. Medido em 2026-08-06: mandar `content` multimodal para
o gateway devolve `HTTP 400`, mesmo pedindo um modelo com visão, porque ele troca o modelo em
silêncio. Sem uma saída local, quem usa o app de graça simplesmente não consegue trabalhar
com print de tela, foto de documento ou PDF escaneado.

Motor: RapidOCR sobre onnxruntime. A escolha foi por empacotamento, não por rótulo — é
instalável só por pip (sem binário de sistema como o Tesseract), roda offline e tem wheels
para as plataformas que a gente distribui, o que mantém em pé o build do Windows feito por
cross-compile no Mac.

Isto NÃO substitui visão de verdade: OCR lê texto, não descreve cena. "Que cor é esta
camisa?" continua exigindo Claude/Gemini/OpenAI. O que ele resolve é o caso comum e chato —
documento, nota fiscal, print de erro, slide, contrato escaneado.

Custos que moldaram o código:
- o primeiro `import` do onnxruntime custa ~19 s. Por isso o import é preguiçoso (dentro da
  função) e o motor fica em cache num singleton: quem nunca anexa imagem nunca paga.
- a inferência em si é rápida (~0,3 s numa imagem de 900×260), mas é CPU-bound e síncrona:
  quem chamar de dentro do laço async tem de jogar numa thread.
"""

from __future__ import annotations

import base64
import hashlib
import io
import logging
import threading
from typing import Any, Optional

logger = logging.getLogger(__name__)

#: Abaixo disto o reconhecimento é chute — some do texto entregue ao modelo, para o agente
#: não construir um raciocínio inteiro em cima de uma palavra inventada.
CONFIANCA_MINIMA = 0.5

#: Teto do texto devolvido. Um PDF escaneado de 100 páginas encheria a janela sozinho.
MAX_CHARS = 100_000

_motor: Any = None
_motor_lock = threading.Lock()
_motor_falhou = False

# hash do conteúdo → texto. O histórico é reprocessado a cada turno; sem cache, a mesma
# imagem passaria pelo OCR em toda mensagem da conversa.
_cache: dict[str, Optional[str]] = {}
_CACHE_MAX = 16


def disponivel() -> bool:
    """O motor pode ser carregado? Nunca levanta — a resposta orienta a mensagem que o
    usuário vê, e 'não instalado' é um estado normal (extra de pip, ambiente enxuto)."""
    if _motor_falhou:
        return False
    try:
        import rapidocr_onnxruntime  # noqa: F401
    except Exception:
        return False
    return True


def _obter_motor() -> Any:
    """Singleton do motor. O `import` e a construção custam caro (~19 s na primeira vez,
    carregando onnxruntime e os modelos), então acontecem uma vez por processo — e sob lock,
    porque duas sessões podem anexar imagem ao mesmo tempo."""
    global _motor, _motor_falhou
    if _motor is not None or _motor_falhou:
        return _motor
    with _motor_lock:
        if _motor is not None or _motor_falhou:
            return _motor
        try:
            from rapidocr_onnxruntime import RapidOCR

            _motor = RapidOCR()
        except Exception as exc:
            # Falta da lib é esperado; qualquer outro erro também não pode derrubar o turno.
            logger.info("OCR indisponível (%s: %s)", type(exc).__name__, exc)
            _motor_falhou = True
        return _motor


def aquecer() -> Optional[threading.Thread]:
    """Carrega o motor em segundo plano, sem bloquear quem chamou.

    O consumo do OCR acontece dentro de `_outbound_messages`, que roda no laço de eventos do
    servidor — pagar ali os ~19 s do primeiro import do onnxruntime congelaria o streaming de
    todas as sessões. Chamado quando uma imagem é ANEXADA, o custo cabe no intervalo entre
    anexar e enviar. Devolve a thread (ou None se não há o que aquecer) para os testes."""
    if _motor is not None or _motor_falhou or not disponivel():
        return None
    t = threading.Thread(target=_obter_motor, daemon=True, name="ocr-warmup")
    t.start()
    return t


def _bytes_de(dado: Any) -> Optional[bytes]:
    """Aceita bytes, data URL (`data:image/png;base64,…`) ou base64 puro."""
    if isinstance(dado, (bytes, bytearray)):
        return bytes(dado)
    if not isinstance(dado, str):
        return None
    texto = dado.strip()
    if texto.startswith("data:"):
        _, _, texto = texto.partition(",")
    try:
        return base64.b64decode(texto, validate=False)
    except Exception:
        return None


def _guardar(chave: str, valor: Optional[str]) -> Optional[str]:
    if len(_cache) >= _CACHE_MAX:
        _cache.pop(next(iter(_cache)))
    _cache[chave] = valor
    return valor


def ler_texto(dado: Any) -> Optional[str]:
    """Texto reconhecido na imagem, ou None quando não há motor ou nada legível.

    Devolver None e devolver "" são coisas diferentes de propósito: None é "não consegui
    olhar", "" é "olhei e não tem texto". Quem chama monta mensagens distintas para cada um,
    porque a ação do usuário também é distinta (instalar o extra vs. usar outro modelo).
    """
    dados = _bytes_de(dado)
    if not dados:
        return None
    chave = hashlib.sha256(dados).hexdigest()
    if chave in _cache:
        return _cache[chave]

    motor = _obter_motor()
    if motor is None:
        return None
    try:
        # Os bytes vão direto para o motor, sem passar pelo Pillow: o sidecar empacotado
        # EXCLUI o PIL de propósito (packaging/mangaba-server.spec — tamanho do bundle e
        # superfície de assinatura). Converter aqui faria o OCR funcionar no venv de
        # desenvolvimento e falhar calado no app instalado.
        resultado, _ = motor(dados)
    except Exception as exc:
        logger.info("OCR falhou (%s: %s)", type(exc).__name__, exc)
        return _guardar(chave, None)

    linhas = [
        str(linha[1]).strip()
        for linha in (resultado or [])
        if len(linha) > 2 and float(linha[2] or 0) >= CONFIANCA_MINIMA and str(linha[1]).strip()
    ]
    texto = "\n".join(linhas)[:MAX_CHARS]
    return _guardar(chave, texto)


def _dimensoes(dados: bytes) -> dict[str, Any]:
    """Formato e tamanho lidos do cabeçalho, sem Pillow (excluído do sidecar empacotado).

    `imghdr` saiu da biblioteca padrão no Python 3.13, e puxar Pillow só para isto
    contraria o motivo de o spec o excluir. São dois cabeçalhos de campo fixo — PNG e JPEG
    cobrem print de tela e foto de celular, que é o caso real. O resto degrada para
    "formato desconhecido", nunca para exceção."""
    import struct

    try:
        if dados[:8] == b"\x89PNG\r\n\x1a\n":
            largura, altura = struct.unpack(">II", dados[16:24])
            return {"formato": "PNG", "largura": largura, "altura": altura}
        if dados[:2] == b"\xff\xd8":
            i = 2
            while i + 9 < len(dados):
                if dados[i] != 0xFF:
                    i += 1
                    continue
                marcador = dados[i + 1]
                # SOF0..SOF15, menos os marcadores que não carregam dimensão
                if 0xC0 <= marcador <= 0xCF and marcador not in (0xC4, 0xC8, 0xCC):
                    altura, largura = struct.unpack(">HH", dados[i + 5 : i + 9])
                    return {"formato": "JPEG", "largura": largura, "altura": altura}
                i += 2 + struct.unpack(">H", dados[i + 2 : i + 4])[0]
    except Exception:
        pass
    return {"formato": "?"}


def descrever_imagem(dado: Any) -> dict[str, Any]:
    """Os fatos que dá para afirmar de uma imagem sem modelo de visão: formato, dimensões e
    o texto do OCR. Serve de recheio para a nota que substitui a imagem no turno — uma nota
    genérica ("imagem anexada") não deixa o agente fazer nada; com dimensão e texto ele pelo
    menos sabe se está diante de um print de erro, de um documento ou de uma foto."""
    dados = _bytes_de(dado)
    if not dados:
        return {"erro": "conteúdo de imagem ilegível"}
    info: dict[str, Any] = {"bytes": len(dados)}
    info.update(_dimensoes(dados))
    texto = ler_texto(dados)
    if texto is None:
        info["ocr"] = "indisponível"
    elif texto:
        info["texto"] = texto
    else:
        info["ocr"] = "sem texto reconhecido"
    return info


def nota_para_modelo_sem_visao(dado: Any, nome: str = "imagem") -> str:
    """A nota de texto que entra no lugar da imagem quando o modelo ativo não tem visão.

    Antes desta função a parte `image_url` seguia intacta para um provedor de texto puro e
    virava um `HTTP 400` cru na cara do usuário. Uma imagem nunca pode sumir do turno em
    silêncio — nem derrubá-lo."""
    info = descrever_imagem(dado)
    dimensao = (
        f"{info.get('largura')}×{info.get('altura')}"
        if info.get("largura")
        else "dimensão desconhecida"
    )
    cabecalho = f"[Imagem anexada: {nome} — {info.get('formato', '?')}, {dimensao}. "
    if info.get("texto"):
        return (
            cabecalho
            + "O modelo ativo não enxerga imagens, então o texto foi extraído aqui na "
            + "máquina por OCR:]\n"
            + info["texto"]
        )
    if info.get("ocr") == "indisponível":
        return (
            cabecalho
            + "O modelo ativo não enxerga imagens e o OCR local não está instalado. "
            + "Instale o extra `ocr` (pip install 'mangaba[ocr]') para ler texto de "
            + "imagens sem chave, ou escolha um provedor com visão (Claude, Gemini, OpenAI).]"
        )
    return (
        cabecalho
        + "O modelo ativo não enxerga imagens e o OCR local não achou texto — é provável "
        + "que seja uma foto ou um diagrama sem legenda. Descrever a cena exige um provedor "
        + "com visão (Claude, Gemini, OpenAI).]"
    )
