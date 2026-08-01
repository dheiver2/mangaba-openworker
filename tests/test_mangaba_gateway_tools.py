"""Ferramentas servidas pelo gateway Mangaba."""

from __future__ import annotations

import pathlib

from mangaba.tools.mangaba_gateway import gateway_tools


class SegredosFalsos:
    def get(self, chave):
        return {}


def _fn(ws):
    ferr = gateway_tools(SegredosFalsos(), ws)[0]
    return getattr(ferr, "__wrapped__", None) or ferr


class RespFalsa:
    def __init__(self, status=200, tipo="image/png", corpo=b"\x89PNG\r\n\x1a\nfake"):
        self.status_code, self.headers, self.content = status, {"content-type": tipo}, corpo


def test_gerar_imagem_salva_o_arquivo_na_pasta_da_conversa(tmp_path, monkeypatch):
    """A capacidade é nova (o app não gerava imagem), e o resultado precisa virar ARQUIVO —
    é assim que todo entregável do Mangaba chega ao usuário."""
    enviado = {}

    def fake_post(url, data=None, timeout=None):
        enviado.update(url=url, data=data)
        return RespFalsa()

    monkeypatch.setattr("httpx.post", fake_post)
    res = _fn(str(tmp_path))("uma manga madura", 512, 512, "manga")
    assert res["bytes"] > 0
    caminho = pathlib.Path(res["arquivo"])
    assert caminho.exists() and caminho.suffix == ".png"  # extensão garantida
    assert enviado["url"].endswith("/image/generate")
    assert enviado["data"]["prompt"] == "uma manga madura"


def test_gerar_imagem_recusa_html_disfarcado_de_imagem(tmp_path, monkeypatch):
    """Um túnel fora do ar devolve a página de erro com status 200. Salvar isso como .png
    entregaria um "artefato" que não abre — o erro tem de aparecer, com a causa."""
    monkeypatch.setattr(
        "httpx.post",
        lambda url, data=None, timeout=None: RespFalsa(tipo="text/html", corpo=b"<!DOCTYPE html>"),
    )
    res = _fn(str(tmp_path))("qualquer coisa")
    assert "erro" in res and "não devolveu uma imagem" in res["erro"]
    assert not list(tmp_path.glob("*.png"))  # nada de lixo salvo


def test_gerar_imagem_nao_escapa_da_pasta_da_conversa(tmp_path, monkeypatch):
    """O nome do arquivo vem do MODELO: `../../algo.png` não pode escrever fora da pasta."""
    monkeypatch.setattr("httpx.post", lambda url, data=None, timeout=None: RespFalsa())
    res = _fn(str(tmp_path))("x", 512, 512, "../../fuga.png")
    assert pathlib.Path(res["arquivo"]).parent == tmp_path


def test_gerar_imagem_sem_prompt_nao_chama_o_gateway(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "httpx.post",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("não devia chamar")),
    )
    assert "erro" in _fn(str(tmp_path))("   ")
