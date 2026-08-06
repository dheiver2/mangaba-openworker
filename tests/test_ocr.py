"""OCR local — a saída para imagem e PDF escaneado nos provedores SEM chave.

Contexto que justifica o módulo: os dois provedores que funcionam sem chave (Mangaba Local e
o gateway Mangaba) são de TEXTO PURO. Sem OCR, quem usa o app de graça não consegue trabalhar
com print de tela, foto de documento ou contrato escaneado — o modelo recebia só um marcador
dizendo que havia uma imagem, o que é honesto e inútil.

O motor (rapidocr-onnxruntime) é um EXTRA de pip, não dependência base: onnxruntime + opencv
passam de 200 MB. Por isso quase todo teste aqui roda sem o motor instalado — o que importa
é que a ausência dele produza uma mensagem acionável, nunca uma exceção. Os testes que
exigem o motor de verdade são marcados e pulados quando ele não está lá.
"""

from __future__ import annotations

import base64
import struct
import zlib

import pytest

from mangaba import ocr


def _png(largura: int, altura: int) -> bytes:
    """PNG mínimo válido, para exercitar a leitura de cabeçalho sem depender do Pillow."""

    def chunk(tag: bytes, payload: bytes) -> bytes:
        return (
            struct.pack(">I", len(payload))
            + tag
            + payload
            + struct.pack(">I", zlib.crc32(tag + payload) & 0xFFFFFFFF)
        )

    linhas = bytearray()
    for _ in range(altura):
        linhas.append(0)
        linhas.extend(b"\xff\xff\xff" * largura)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", largura, altura, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(bytes(linhas), 6))
        + chunk(b"IEND", b"")
    )


@pytest.fixture(autouse=True)
def _limpar_cache():
    ocr._cache.clear()
    yield
    ocr._cache.clear()


# -- leitura de entrada ---------------------------------------------------------------------


def test_aceita_bytes_data_url_e_base64():
    """As três formas que o app produz: bytes (ferramenta lendo do disco), data URL (anexo da
    GUI) e base64 puro (página rasterizada de PDF)."""
    dados = _png(4, 3)
    b64 = base64.b64encode(dados).decode()
    assert ocr._bytes_de(dados) == dados
    assert ocr._bytes_de(f"data:image/png;base64,{b64}") == dados
    assert ocr._bytes_de(b64) == dados


def test_entrada_invalida_nao_levanta():
    assert ocr._bytes_de(None) is None
    assert ocr._bytes_de(12345) is None


def test_dimensoes_de_png_sem_pillow():
    """O sidecar empacotado EXCLUI o Pillow de propósito (packaging/mangaba-server.spec:101).
    Ler o cabeçalho à mão é o que faz o OCR funcionar no app instalado, e não só no venv."""
    info = ocr._dimensoes(_png(37, 11))
    assert info == {"formato": "PNG", "largura": 37, "altura": 11}


def test_dimensoes_de_formato_desconhecido_degrada_sem_erro():
    assert ocr._dimensoes(b"\x00\x01lixo") == {"formato": "?"}


# -- ausência do motor: precisa ser acionável, nunca uma exceção ----------------------------


def test_sem_motor_ler_texto_devolve_none(monkeypatch):
    monkeypatch.setattr(ocr, "_obter_motor", lambda: None)
    assert ocr.ler_texto(_png(4, 4)) is None


def test_nota_sem_motor_diz_como_resolver(monkeypatch):
    """Duas saídas concretas, porque o usuário não tem como adivinhar nenhuma delas."""
    monkeypatch.setattr(ocr, "_obter_motor", lambda: None)
    monkeypatch.setattr(ocr, "empacotado", lambda: False)
    nota = ocr.nota_para_modelo_sem_visao(_png(800, 600), nome="print.png")
    assert "print.png" in nota and "800×600" in nota
    assert "mangaba[ocr]" in nota
    assert "Gemini" in nota or "Claude" in nota


def test_no_app_empacotado_nao_manda_rodar_pip(monkeypatch):
    """O sidecar do desktop é um bundle PyInstaller CONGELADO: não existe `pip` para
    instalar nada dentro dele. Mandar `pip install 'mangaba[ocr]'` para quem instalou pelo
    DMG é uma instrução impossível — e quem tenta segui-la conclui que o app está quebrado.
    Ali a única saída real é trocar de provedor."""
    monkeypatch.setattr(ocr, "empacotado", lambda: True)
    saida = ocr.como_instalar()
    assert "pip install" not in saida
    assert "Gemini" in saida or "Claude" in saida


def test_fora_do_app_empacotado_o_pip_e_a_saida_certa(monkeypatch):
    monkeypatch.setattr(ocr, "empacotado", lambda: False)
    assert "pip install" in ocr.como_instalar()


def test_ferramenta_usa_a_mesma_orientacao_por_contexto(monkeypatch, tmp_path):
    """A ferramenta e a nota de anexo não podem divergir: uma dizendo `pip install` e a
    outra dizendo para trocar de provedor, na mesma instalação, é o tipo de contradição que
    faz a pessoa parar de confiar na mensagem."""
    monkeypatch.setattr(ocr, "disponivel", lambda: False)
    monkeypatch.setattr(ocr, "empacotado", lambda: True)
    (tmp_path / "a.png").write_bytes(_png(4, 4))
    assert "pip install" not in _ferramenta(str(tmp_path))("a.png")["error"]


def test_none_e_vazio_sao_estados_diferentes(monkeypatch):
    """'Não consegui olhar' e 'olhei e não tem texto' levam a ações opostas do usuário —
    instalar o extra vs. trocar de provedor. Colapsar os dois em None esconderia isso."""
    monkeypatch.setattr(ocr, "_obter_motor", lambda: object())
    monkeypatch.setattr(ocr, "_cache", {})

    class _MotorVazio:
        def __call__(self, _):
            return [], None

    monkeypatch.setattr(ocr, "_obter_motor", lambda: _MotorVazio())
    assert ocr.ler_texto(_png(4, 4)) == ""

    nota = ocr.nota_para_modelo_sem_visao(_png(4, 4))
    assert "não achou texto" in nota and "mangaba[ocr]" not in nota


def test_motor_que_explode_nao_derruba_o_turno(monkeypatch):
    class _MotorRuim:
        def __call__(self, _):
            raise RuntimeError("onnx quebrou")

    monkeypatch.setattr(ocr, "_obter_motor", lambda: _MotorRuim())
    assert ocr.ler_texto(_png(4, 4)) is None


# -- confiança e cache ----------------------------------------------------------------------


def test_descarta_reconhecimento_de_baixa_confianca(monkeypatch):
    """Palavra chutada é pior do que palavra ausente: o agente constrói um raciocínio inteiro
    em cima dela e entrega um resultado errado com convicção."""

    class _Motor:
        def __call__(self, _):
            return [
                [None, "Total: R$ 1.284,90", 0.99],
                [None, "rn1lh4o", 0.11],
            ], None

    monkeypatch.setattr(ocr, "_obter_motor", lambda: _Motor())
    texto = ocr.ler_texto(_png(4, 4))
    assert texto == "Total: R$ 1.284,90"


def test_mesma_imagem_so_passa_pelo_motor_uma_vez(monkeypatch):
    """O histórico é reprocessado a cada turno; sem cache, a mesma imagem passaria pelo OCR
    em toda mensagem da conversa."""
    chamadas = {"n": 0}

    class _Motor:
        def __call__(self, _):
            chamadas["n"] += 1
            return [[None, "oi", 0.9]], None

    monkeypatch.setattr(ocr, "_obter_motor", lambda: _Motor())
    dados = _png(6, 6)
    assert ocr.ler_texto(dados) == "oi"
    assert ocr.ler_texto(dados) == "oi"
    assert chamadas["n"] == 1


def test_aquecer_nao_bloqueia_e_some_quando_nao_ha_motor(monkeypatch):
    """O aquecimento existe porque o consumo acontece no laço de eventos do servidor; se ele
    bloqueasse, congelaria o streaming de todas as sessões."""
    monkeypatch.setattr(ocr, "disponivel", lambda: False)
    assert ocr.aquecer() is None


# -- integração com o caminho de anexo ------------------------------------------------------


def test_imagem_vira_nota_de_texto_quando_o_modelo_nao_tem_visao(monkeypatch):
    """Prova no engine, não no módulo: o marcador antigo ('[image attachment — not viewable
    by this model]') dizia que existia uma imagem e não dava nada ao modelo."""
    import tempfile

    from mangaba.server.manager import SessionManager

    class _Motor:
        def __call__(self, _):
            return [[None, "Nota Fiscal 1234", 0.97]], None

    monkeypatch.setattr(ocr, "_obter_motor", lambda: _Motor())

    m = SessionManager(workspace=tempfile.mkdtemp())
    eng = m.get_engine("__ocr__", agent="cowork")
    eng.model = "mangaba:auto"  # texto puro, sem visão
    url = "data:image/png;base64," + base64.b64encode(_png(120, 40)).decode()
    eng.messages.append(
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "o que diz aqui?"},
                {"type": "image_url", "image_url": {"url": url}},
            ],
        }
    )
    saida = eng._outbound_messages()
    textos = [
        p.get("text", "")
        for msg in saida
        if isinstance(msg.get("content"), list)
        for p in msg["content"]
        if isinstance(p, dict)
    ]
    assert not [
        p
        for msg in saida
        if isinstance(msg.get("content"), list)
        for p in msg["content"]
        if isinstance(p, dict) and p.get("type") == "image_url"
    ], "nenhuma parte de imagem pode sobrar para um provedor de texto puro"
    assert any("Nota Fiscal 1234" in t for t in textos)


def test_pdf_escaneado_cai_no_ocr_antes_de_desistir(monkeypatch):
    """Antes desta rota, PDF escaneado terminava em 'use um modelo com visão' — um beco sem
    saída para quem usa os provedores sem chave."""
    from mangaba import pdf_support

    monkeypatch.setattr(pdf_support, "extract_text", lambda _: "")
    monkeypatch.setattr(
        pdf_support, "rasterize", lambda _d, max_pages=1: ["data:image/png;base64,AAAA"]
    )
    monkeypatch.setattr(ocr, "disponivel", lambda: True)
    monkeypatch.setattr(ocr, "ler_texto", lambda _: "CONTRATO DE PRESTACAO")

    class _Caps:
        pdf = False
        vision = False

    saida = pdf_support.adapt_content(
        [{"type": "file", "file": {"filename": "contrato.pdf", "file_data": "x"}}],
        _Caps(),
    )
    assert "CONTRATO DE PRESTACAO" in saida[0]["text"]
    assert "escaneado" in saida[0]["text"]


def test_pdf_escaneado_sem_motor_mantem_a_mensagem_antiga(monkeypatch):
    from mangaba import pdf_support

    monkeypatch.setattr(pdf_support, "extract_text", lambda _: "")
    monkeypatch.setattr(ocr, "disponivel", lambda: False)

    class _Caps:
        pdf = False
        vision = False

    saida = pdf_support.adapt_content(
        [{"type": "file", "file": {"filename": "c.pdf", "file_data": "x"}}], _Caps()
    )
    assert "no extractable text" in saida[0]["text"]


# -- ferramenta ler_imagem ------------------------------------------------------------------


def _ferramenta(ws: str):
    from mangaba.tools.imagem import image_tools

    return image_tools(ws)[0]


def test_ler_imagem_nao_escapa_do_workspace(tmp_path):
    (tmp_path / "dentro").mkdir()
    fora = tmp_path / "segredo.png"
    fora.write_bytes(_png(4, 4))
    f = _ferramenta(str(tmp_path / "dentro"))
    assert "escapes the workspace" in f("../segredo.png")["error"]


def test_ler_imagem_recusa_o_que_nao_e_imagem(tmp_path):
    (tmp_path / "notas.txt").write_text("oi")
    assert "not an image" in _ferramenta(str(tmp_path))("notas.txt")["error"]


def test_ler_imagem_sem_motor_da_erro_acionavel(tmp_path, monkeypatch):
    """Devolver texto vazio faria o agente concluir que a imagem não tem texto — e seguir
    adiante com a conclusão errada. O erro tem de dizer o que fazer."""
    monkeypatch.setattr(ocr, "disponivel", lambda: False)
    monkeypatch.setattr(ocr, "empacotado", lambda: False)
    (tmp_path / "a.png").write_bytes(_png(4, 4))
    erro = _ferramenta(str(tmp_path))("a.png")["error"]
    assert "mangaba[ocr]" in erro and ("Gemini" in erro or "Claude" in erro)


def test_ler_imagem_sem_texto_avisa_que_ocr_nao_descreve_cena(tmp_path, monkeypatch):
    monkeypatch.setattr(ocr, "disponivel", lambda: True)
    monkeypatch.setattr(ocr, "ler_texto", lambda _: "")
    (tmp_path / "foto.png").write_bytes(_png(50, 20))
    r = _ferramenta(str(tmp_path))("foto.png")
    assert r["text"] == "" and "vision-capable provider" in r["note"]
    assert r["width"] == 50 and r["height"] == 20


def test_ler_imagem_devolve_o_texto(tmp_path, monkeypatch):
    monkeypatch.setattr(ocr, "disponivel", lambda: True)
    monkeypatch.setattr(ocr, "ler_texto", lambda _: "R$ 1.284,90")
    (tmp_path / "nota.png").write_bytes(_png(90, 30))
    r = _ferramenta(str(tmp_path))("nota.png")
    assert r["text"] == "R$ 1.284,90" and r["format"] == "PNG"


def test_ler_imagem_esta_nas_familias_de_entrega():
    """Um agente nos provedores sem chave enxerga o nome do print na pasta; sem esta
    ferramenta, não tem como olhar dentro. Chat, sem área de trabalho, fica de fora."""
    import tempfile

    from mangaba.server.manager import SessionManager

    m = SessionManager(workspace=tempfile.mkdtemp())

    def nomes(agente: str) -> set[str]:
        eng = m.get_engine(f"__img__{agente}", agent=agente)
        return {s["function"]["name"] for s in eng.registry.schemas()}

    assert "ler_imagem" in nomes("code")
    assert "ler_imagem" in nomes("cowork")
    assert "ler_imagem" in nomes("negocio")
    assert "ler_imagem" not in nomes("chat")


# -- prova com o motor de verdade (pulada quando o extra não está instalado) -----------------


@pytest.mark.skipif(not ocr.disponivel(), reason="extra `ocr` não instalado")
def test_motor_real_le_um_documento_gerado_na_hora():
    """A única prova que vale de verdade: texto renderizado numa imagem e lido de volta pelo
    motor real, sem stub em lugar nenhum."""
    pil = pytest.importorskip("PIL")
    from PIL import Image, ImageDraw

    img = Image.new("RGB", (700, 120), "white")
    ImageDraw.Draw(img).text((20, 40), "TOTAL R$ 1284,90", fill="black")
    import io as _io

    buf = _io.BytesIO()
    img.save(buf, format="PNG")

    texto = ocr.ler_texto(buf.getvalue()) or ""
    assert "1284" in texto.replace(".", "").replace(" ", "")
