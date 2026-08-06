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

Custos MEDIDOS em 2026-08-06 (o primeiro texto deste módulo dizia "~19 s para carregar" e
usava isso para justificar o aquecimento — o número era de uma leitura fria única, não o
custo real, e a auditoria o derrubou):
- `import rapidocr_onnxruntime`: ~0,3 s. Construir o `RapidOCR()`: ~0,4 s com o disco quente.
  Ainda assim o import é preguiçoso e o motor fica num singleton — quem nunca anexa imagem
  não paga nada, e a primeira vez de todas (modelos frios) chegou a ~19 s.
- a INFERÊNCIA é o custo de verdade e escala com a página: ~0,3 s numa faixa de 900×260,
  mas ~4,4 s numa página A4 cheia de texto. É CPU-bound e síncrona — quem chamar de dentro
  do laço async TEM de jogar numa thread, senão congela todas as sessões (foi o que
  aconteceu com PDF escaneado até a 0.1.36).
"""

from __future__ import annotations

import base64
import hashlib
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
    """Singleton do motor: ~0,4 s com o disco quente, e bem mais na primeira vez de todas
    (modelos frios). Acontece uma vez por processo, sob lock — duas sessões podem anexar
    imagem ao mesmo tempo."""
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


def empacotado() -> bool:
    """Estamos rodando dentro do sidecar congelado (PyInstaller) do app de desktop?"""
    import sys

    return bool(getattr(sys, "frozen", False))


def como_instalar() -> str:
    """A saída que a pessoa tem, escrita para o lugar onde ela de fato está.

    Isto não é firula de texto: o OCR é um EXTRA de pip, e no app de desktop o sidecar é um
    bundle PyInstaller CONGELADO — não existe `pip` para instalar nada dentro dele. Mandar
    `pip install 'mangaba[ocr]'` para quem instalou pelo DMG é uma instrução impossível, e
    quem a segue conclui que o app está quebrado. Instalação por linha de comando só faz
    sentido em instalação por código-fonte/CLI."""
    if empacotado():
        return (
            "o OCR local não vem embutido neste instalador. Para ler texto de imagem, "
            "use um provedor com visão (Claude, Gemini ou OpenAI) em Configurações ▸ "
            "Modelos, ou rode o Mangaba a partir do código-fonte com o extra `ocr`."
        )
    return (
        "o OCR local não está instalado. Rode `pip install 'mangaba[ocr]'` para ler texto "
        "de imagens sem chave, ou escolha um provedor com visão (Claude, Gemini, OpenAI)."
    )


def aquecer() -> Optional[threading.Thread]:
    """Carrega o motor em segundo plano, sem bloquear quem chamou.

    Chamado quando uma imagem ou um PDF é ANEXADO, o custo de subir o motor cabe no intervalo
    entre anexar e enviar, em vez de aparecer como demora na primeira resposta. Isto NÃO é o
    que protege o laço de eventos — quem faz isso é o `asyncio.to_thread` em torno de
    `_outbound_messages` (engine.py), porque o peso está na inferência, não na carga.
    Devolve a thread (ou None se não há o que aquecer) para os testes."""
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
    contraria o motivo de o spec o excluir. Cobre os formatos que `ler_imagem` aceita —
    antes só PNG e JPEG, e um .webp ou .bmp saía com formato "?" e dimensões nulas mesmo
    tendo o OCR funcionado. O que não for reconhecido degrada para "formato desconhecido",
    nunca para exceção."""
    import struct

    try:
        if dados[:4] == b"RIFF" and dados[8:12] == b"WEBP":
            tipo = dados[12:16]
            if tipo == b"VP8X":
                largura = int.from_bytes(dados[24:27], "little") + 1
                altura = int.from_bytes(dados[27:30], "little") + 1
                return {"formato": "WEBP", "largura": largura, "altura": altura}
            if tipo == b"VP8L":
                b = int.from_bytes(dados[21:25], "little")
                return {
                    "formato": "WEBP",
                    "largura": (b & 0x3FFF) + 1,
                    "altura": ((b >> 14) & 0x3FFF) + 1,
                }
            if tipo == b"VP8 ":
                largura, altura = struct.unpack("<HH", dados[26:30])
                return {
                    "formato": "WEBP",
                    "largura": largura & 0x3FFF,
                    "altura": altura & 0x3FFF,
                }
            return {"formato": "WEBP"}
        if dados[:2] == b"BM":
            largura, altura = struct.unpack("<ii", dados[18:26])
            return {"formato": "BMP", "largura": abs(largura), "altura": abs(altura)}
        if dados[:6] in (b"GIF87a", b"GIF89a"):
            largura, altura = struct.unpack("<HH", dados[6:10])
            return {"formato": "GIF", "largura": largura, "altura": altura}
        if dados[:4] in (b"II*\x00", b"MM\x00*"):
            # TIFF guarda as dimensões em IFD, longe do cabeçalho; o formato já ajuda.
            return {"formato": "TIFF"}
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

    Antes desta função o engine trocava a imagem por "[image attachment — not viewable by
    this model]": honesto e inútil, porque o modelo ficava sabendo que havia uma imagem sem
    ter o que fazer com ela. Uma imagem nunca pode sumir do turno em silêncio."""
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
        return cabecalho + "O modelo ativo não enxerga imagens e " + como_instalar() + "]"
    return (
        cabecalho
        + "O modelo ativo não enxerga imagens e o OCR local não achou texto — é provável "
        + "que seja uma foto ou um diagrama sem legenda. Descrever a cena exige um provedor "
        + "com visão (Claude, Gemini, OpenAI).]"
    )
