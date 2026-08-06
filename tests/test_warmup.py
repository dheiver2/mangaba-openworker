"""Pré-aquecimento do cache de prompt na abertura da sessão.

A medição que motiva isto: nos modelos em CPU o gargalo da PRIMEIRA resposta é o prefill do
prefixo (system + tools) — ~23 s no Nordeste-30B, ~3,6 s no Qwen3-4B local para ~3k tokens.
Uma vez prefillado, o mesmo prefixo responde em ~0,6 s (cache quente). O `_warm_engine` paga
esse prefill em background quando a sessão nasce, para a 1ª mensagem real cair no cache.

Estes testes prendem duas coisas que, se quebrarem, matam o ganho em silêncio: (1) o
aquecimento só dispara onde o prefill domina (local/Nordeste), nunca queimando tokens de
nuvem; (2) quando dispara, manda EXATAMENTE o prefixo que a 1ª mensagem real vai mandar —
mesmo system, mesmas tools — senão o cache não casa e o aquecimento não serve para nada.
"""

from __future__ import annotations

import tempfile
from types import SimpleNamespace
from typing import Any

from mangaba.server.manager import SessionManager

TOOLS = [{"type": "function", "function": {"name": "read_file", "parameters": {}}}]
SYSTEM = {"role": "system", "content": "Você é um agente. Regras: ..."}


def _fake_engine(model: str) -> tuple[SimpleNamespace, list[dict[str, Any]]]:
    """Um engine mínimo com só o que _warm_engine toca, e um provider que registra a chamada."""
    chamadas: list[dict[str, Any]] = []

    class _Prov:
        def complete(self, **kw: Any) -> Any:
            chamadas.append(kw)
            return SimpleNamespace(text="", finish_reason="length")

    eng = SimpleNamespace(
        model=model,
        messages=[SYSTEM, {"role": "user", "content": "oi"}],
        registry=SimpleNamespace(schemas=lambda: TOOLS),
        provider=_Prov(),
    )
    return eng, chamadas


def _mgr() -> SessionManager:
    return SessionManager(workspace=tempfile.mkdtemp())


def test_aquece_modelo_local_com_o_prefixo_da_sessao():
    m = _mgr()
    eng, chamadas = _fake_engine("local:Qwen3-4B-Q4_K_M")
    t = m._warm_engine(eng)
    assert t is not None, "modelo local deveria ser aquecido"
    t.join(timeout=5)
    assert len(chamadas) == 1, "deveria ter disparado exatamente um prefill de aquecimento"
    kw = chamadas[0]
    # Mesmo modelo, mesmo system, mesmas tools = mesmo prefixo que a 1ª mensagem real. Se
    # qualquer um divergir, o cache do gateway não casa e o aquecimento vira desperdício.
    assert kw["model"] == "local:Qwen3-4B-Q4_K_M"
    assert kw["messages"][0] == SYSTEM
    assert kw["tools"] == TOOLS
    assert kw["max_tokens"] == 1, "pede só 1 token — o custo é o prefill, não a geração"


def test_aquece_nordeste():
    m = _mgr()
    eng, chamadas = _fake_engine("mangaba-nordeste:Mangaba-Nordeste-30B")
    t = m._warm_engine(eng)
    assert t is not None
    t.join(timeout=5)
    assert len(chamadas) == 1


def test_nao_aquece_provedor_de_nuvem():
    """Aquecer um modelo de nuvem (rápido) só queimaria tokens — o prefill não domina lá."""
    m = _mgr()
    for modelo in ("openai:gpt-5.6-sol", "anthropic:claude-opus-5", "deepseek:deepseek-chat"):
        eng, chamadas = _fake_engine(modelo)
        t = m._warm_engine(eng)
        assert t is None, f"{modelo} não deveria ser aquecido"
        assert chamadas == [], f"{modelo} não deveria receber requisição de aquecimento"


def test_nao_quebra_a_sessao_se_o_aquecimento_falhar():
    """Best-effort: um provider que explode no aquecimento não pode derrubar a criação da
    sessão — a thread engole o erro e a 1ª mensagem só volta a pagar o prefill frio."""
    m = _mgr()
    eng, _ = _fake_engine("local:Qwen3-4B-Q4_K_M")

    def _boom(**kw: Any) -> Any:
        raise RuntimeError("gateway fora do ar")

    eng.provider.complete = _boom
    t = m._warm_engine(eng)
    assert t is not None
    t.join(timeout=5)  # não deve levantar; o erro fica contido na thread
    assert not t.is_alive()


def test_pula_se_nao_ha_system_para_aquecer():
    """Sem prefixo estável (nenhuma mensagem de sistema) não há o que pré-aquecer."""
    m = _mgr()
    eng, chamadas = _fake_engine("local:Qwen3-4B-Q4_K_M")
    eng.messages = [{"role": "user", "content": "oi"}]  # sem system
    assert m._warm_engine(eng) is None
    assert chamadas == []
