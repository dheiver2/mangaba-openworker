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


def test_aquecimento_usa_a_visao_outbound_completa():
    """Numa sessão retomada o prefixo frio é o HISTÓRICO inteiro, não só o system — aquecer
    só com o system pagaria uma fração do prefill e a 1ª mensagem real pagaria o resto.
    Quando o engine expõe a visão outbound (a mesma que o próximo turno envia), o
    aquecimento tem de usá-la por inteiro."""
    m = _mgr()
    eng, chamadas = _fake_engine("local:Qwen3-4B-Q4_K_M")
    historia = [
        SYSTEM,
        {"role": "user", "content": "faça a análise"},
        {"role": "assistant", "content": "feito — segue o resumo"},
    ]
    eng._outbound_messages = lambda: list(historia)
    t = m._warm_engine(eng)
    assert t is not None
    t.join(timeout=5)
    kw = chamadas[0]
    assert kw["messages"][:3] == historia, "o prefixo aquecido deve ser a visão outbound inteira"
    assert kw["messages"][-1]["role"] == "user"


def test_aquece_tambem_sessao_retomada(monkeypatch):
    """A lacuna que motivou isto: o aquecimento disparava só em sessão NOVA. Reabrir uma
    conversa de ontem depois de o app/motor reiniciar reconstrói o engine com o cache do
    provedor frio — e um prefixo ainda maior (o histórico). Todo engine CONSTRUÍDO aquece;
    engine já vivo em memória (retorno de cache do get_engine) não re-aquece."""
    import tempfile as _tf
    from types import SimpleNamespace as _NS

    from mangaba.permissions import Mode

    m = _mgr()
    aquecidos: list[str] = []
    monkeypatch.setattr(m, "_warm_engine", lambda eng: aquecidos.append(eng.model) or None)

    eng = m.get_engine("s_ret", agent="cowork")
    assert len(aquecidos) == 1, "sessão nova aquece"

    # Engine vivo: get_engine devolve o cache — sem novo aquecimento.
    m.get_engine("s_ret")
    assert len(aquecidos) == 1, "engine já vivo não re-aquece"

    # Simula reinício: engine despejado, mas o registro da sessão existe no disco.
    ws = _tf.mkdtemp()
    registro = _NS(
        agent="cowork",
        workspace=ws,
        model=eng.model,
        mode=Mode.INTERACTIVE.value,
        messages=[{"role": "system", "content": "x"}, {"role": "user", "content": "oi"}],
        extra_roots=[],
        grants=None,
        compaction=None,
    )
    del m._engines["s_ret"]
    monkeypatch.setattr(m.session_store, "load", lambda sid: registro if sid == "s_ret" else None)
    m.get_engine("s_ret")
    assert len(aquecidos) == 2, "sessão RETOMADA (rebuild) também aquece"


# -- compactação proativa pós-turno ---------------------------------------------------------
#
# O "de repente ficou lento de novo" das sessões longas: um turno termina acima do gatilho
# de compactação e o SEGUINTE abre pagando o resumidor + o re-prefill da visão compactada na
# frente do usuário. O caminho proativo paga isso em background enquanto ele lê a resposta,
# e re-aquece o cache com a visão nova.


def _provider_roteirizado(ordem: list[str]):
    from mangaba.providers import AssistantTurn, ModelCapabilities, ProviderClient

    class _P(ProviderClient):
        def complete(self, *, model, messages, tools=None, **s):
            ordem.append("modelo")
            return AssistantTurn(text="pronto", finish_reason="stop")

        def capabilities(self, model):
            return ModelCapabilities()

    return _P()


def test_turno_acima_do_gatilho_compacta_e_reaquece_em_background():
    import asyncio

    ordem: list[str] = []
    m = SessionManager(workspace=tempfile.mkdtemp(), provider=_provider_roteirizado(ordem))
    eng = m.get_engine("s_pos", agent="cowork")

    # 1ª chamada = checkpoint no topo da iteração (não compacta no meio do turno);
    # 2ª = o gate pós-turno (aí sim, acima do gatilho).
    chamadas = {"n": 0}

    def _due():
        chamadas["n"] += 1
        return chamadas["n"] >= 2

    eng._compaction_due = _due
    feito = {"compact": 0, "warm": 0}

    async def _fake_compact(force=False, ask_on_failure=True):
        assert ask_on_failure is False, "pós-turno NUNCA pode abrir prompt de Retry/Aparar"
        feito["compact"] += 1
        return "Contexto compactado"

    eng._compact_now = _fake_compact
    eng.prewarm_hook = lambda: feito.__setitem__("warm", feito["warm"] + 1)

    async def _go():
        async for _ in eng.run("oi"):
            pass
        task = eng._post_turn_task
        assert task is not None, "turno acima do gatilho deveria agendar a task pós-turno"
        await task

    asyncio.run(_go())
    assert feito["compact"] == 1, "compactou em background"
    assert feito["warm"] == 1, "re-aqueceu o cache com a visão compactada"
    assert any(mm.get("kind") == "compacted" for mm in eng.messages if mm.get("role") == "notice")


def test_turno_abaixo_do_gatilho_nao_agenda_nada():
    import asyncio

    ordem: list[str] = []
    m = SessionManager(workspace=tempfile.mkdtemp(), provider=_provider_roteirizado(ordem))
    eng = m.get_engine("s_semgat", agent="cowork")
    eng._compaction_due = lambda: False

    async def _go():
        async for _ in eng.run("oi"):
            pass

    asyncio.run(_go())
    assert eng._post_turn_task is None, "abaixo do gatilho não há custo a antecipar"


def test_proximo_turno_espera_a_compactacao_em_voo():
    """Se o usuário mandar a próxima mensagem com a compactação ainda rodando, o turno novo
    ESPERA — abrir o turno lendo o estado no meio da troca veria história pela metade. No
    pior caso ele espera o que esperaria de qualquer jeito (a compactação do início de turno
    de antes)."""
    import asyncio

    ordem: list[str] = []
    m = SessionManager(workspace=tempfile.mkdtemp(), provider=_provider_roteirizado(ordem))
    eng = m.get_engine("s_espera", agent="cowork")

    async def _go():
        async def _compactando():
            await asyncio.sleep(0.05)
            ordem.append("compactou")

        eng._post_turn_task = asyncio.get_running_loop().create_task(_compactando())
        async for _ in eng.run("próxima"):
            pass

    asyncio.run(_go())
    assert ordem == ["compactou", "modelo"], (
        f"o modelo só pode rodar DEPOIS da compactação em voo terminar; veio {ordem}"
    )
    assert eng._post_turn_task is None, "a task consumida deve ser limpa"


def test_compact_now_nao_pergunta_quando_ask_on_failure_false(monkeypatch):
    """O caminho proativo roda sem turno aberto — um prompt de Retry/Aparar do nada seria um
    susto. Com ask_on_failure=False, falha do resumidor cai no comportamento não-atendido
    (aparar e seguir), mesmo com a sessão atendida."""
    import asyncio

    ordem: list[str] = []
    m = SessionManager(workspace=tempfile.mkdtemp(), provider=_provider_roteirizado(ordem))
    eng = m.get_engine("s_askoff", agent="cowork")
    eng.is_attended = lambda: True

    def _nunca(*a, **k):
        raise AssertionError("question_asker não pode ser chamado no caminho proativo")

    eng.question_asker = _nunca
    monkeypatch.setattr(
        "mangaba.compaction.build_state",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("resumidor fora do ar")),
    )
    # Não pode levantar (nem perguntar): falha → tenta aparar → segue.
    asyncio.run(eng._compact_now(ask_on_failure=False))
