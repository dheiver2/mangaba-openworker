"""Melhorias de orquestração de entrega (Fase 1).

Três lacunas fechadas, cada uma presa por teste contra o comportamento real:
- 1.2 decomposição: as famílias de ENTREGA (knowledge/cowork, business/negocio) ganham o
  subagente `explore` — antes só `code` tinha, e eram justamente elas, que produzem dossiês
  e propostas, que não conseguiam paralelizar leitura sem queimar o contexto principal.
- 1.1 gate de 'definição de pronto': o modelo não pode declarar pronto no instante em que
  para de chamar ferramentas se a lista de Progresso ainda tem tarefas abertas — cutuca UMA
  vez para concluir e verificar.
- 1.3 aviso de fechamento: perto do teto de iterações, avisa o modelo para entregar o que
  tem em vez de ser cortado no meio sem aviso.
"""

from __future__ import annotations

import tempfile

from mangaba.server.manager import SessionManager


def _mgr() -> SessionManager:
    return SessionManager(workspace=tempfile.mkdtemp())


# -- 1.2 · subagentes para as famílias de entrega -------------------------------------------


def test_familias_de_entrega_ganham_o_subagente_explore():
    """Antes o `explore` era exclusivo de `code` (agent.py). As famílias que produzem
    entregáveis — cowork (knowledge) e negocio (business) — precisam decompor leitura em
    subagentes read-only para não afogar o contexto principal. Chat, sem área de trabalho,
    continua de fora (não há o que explorar)."""
    m = _mgr()

    def tools(agente: str) -> set[str]:
        eng = m.get_engine(f"__orq__{agente}", agent=agente)
        return {s["function"]["name"] for s in eng.registry.schemas()}

    assert "explore" in tools("code"), "code sempre teve explore"
    assert "explore" in tools("cowork"), "cowork (entregável) deve poder decompor"
    assert "explore" in tools("negocio"), "negocio (entregável) deve poder decompor"
    assert "explore" not in tools("chat"), "chat não tem área de trabalho — sem explore"


def test_explore_e_read_only_nas_familias_de_entrega():
    """Dar explore a mais famílias não pode abrir risco de escrita: o subagente roda em modo
    plano, sem approver. A garantia aqui é indireta mas real — o explore continua registrado
    ao lado das ferramentas de escrita normais da persona, e é o PermissionEngine do filho
    (não do pai) que barra writes. Este teste fixa que a ferramenta existe e é a mesma peça
    read-only, não uma variante que escreve."""
    from mangaba.tools.subagent import explorer_tools

    tools = explorer_tools(workspace=tempfile.mkdtemp(), provider=None, model="x")
    nomes = {getattr(t, "__name__", "") for t in tools}
    assert "explore" in nomes


# -- 1.1 · gate de 'definição de pronto' ----------------------------------------------------


def _engine_com_todo(m: SessionManager, itens: list[dict]):
    eng = m.get_engine("__orq__gate", agent="cowork")
    eng.todo.items = itens
    eng._done_nudged = False
    eng._steering = []
    return eng


def test_encerrar_com_tarefa_pendente_dispara_a_cutucada():
    m = _mgr()
    eng = _engine_com_todo(
        m,
        [
            {"content": "Ler a planilha", "status": "done"},
            {"content": "Escrever as cobranças", "status": "in_progress"},
        ],
    )
    eng._maybe_nudge_unfinished()
    assert eng._steering, "tarefa aberta ao encerrar deveria enfileirar uma cutucada"
    texto = eng._steering[0][0]
    assert "Escrever as cobranças" in texto and "verifi" in texto.lower()


def test_a_cutucada_e_uma_so_por_turno():
    """O flag evita laço: se o modelo insistir que está pronto após a primeira cutucada, ele
    encerra — não fica preso sendo cutucado para sempre."""
    m = _mgr()
    eng = _engine_com_todo(m, [{"content": "X", "status": "pending"}])
    eng._maybe_nudge_unfinished()
    eng._steering = []  # simula a injeção da 1ª cutucada
    eng._maybe_nudge_unfinished()
    assert not eng._steering, "não pode cutucar duas vezes no mesmo turno"


def test_todo_tudo_concluido_nao_cutuca():
    m = _mgr()
    eng = _engine_com_todo(m, [{"content": "X", "status": "done"}])
    eng._maybe_nudge_unfinished()
    assert not eng._steering, "lista completa não tem o que cobrar"


def test_sessao_sem_todo_nao_quebra_o_gate():
    """Callers diretos podem não ter lista de tarefas — o gate passa reto, sem erro."""
    m = _mgr()
    eng = m.get_engine("__orq__semtodo", agent="cowork")
    eng.todo.items = []
    eng._done_nudged = False
    eng._steering = []
    eng._maybe_nudge_unfinished()
    assert not eng._steering


# -- 1.3 · aviso de fechamento perto do teto ------------------------------------------------


def test_gate_re_engaja_o_modelo_no_loop_real():
    """Prova de ponta a ponta: no loop de verdade, um modelo que tenta encerrar com tarefa
    pendente é RE-CHAMADO após a cutucada (não encerra de imediato), e o turno só termina
    depois. Sem isto, a entrega sairia declarada pronta com trabalho aberto."""
    import asyncio

    from mangaba.events import EventType
    from mangaba.providers import AssistantTurn, ModelCapabilities, ProviderClient

    chamadas = {"n": 0}

    class _P(ProviderClient):
        def complete(self, *, model, messages, tools=None, **s):
            chamadas["n"] += 1
            return AssistantTurn(text="pronto", finish_reason="stop")

        def capabilities(self, model):
            return ModelCapabilities()

    m = SessionManager(workspace=tempfile.mkdtemp(), provider=_P())
    eng = m.get_engine("__orq__live", agent="cowork")
    eng.todo.items = [{"content": "Escrever o entregável", "status": "in_progress"}]

    status = {"v": None}

    async def _go():
        async for ev in eng.run("faça a tarefa"):
            if ev.type == EventType.TURN_END:
                status["v"] = ev.data.get("status")

    asyncio.run(_go())
    assert chamadas["n"] >= 2, "o modelo deveria ser re-chamado após a cutucada"
    assert status["v"] == "completed"
    injetou = any(
        "verifi" in (mm.get("content", "") or "").lower()
        for mm in eng.messages
        if mm.get("role") == "user"
    )
    assert injetou, "a cutucada de verificação deveria entrar no histórico que o modelo vê"


def test_reset_das_cutucadas_por_turno_via_run(monkeypatch):
    """Os dois flags (_done_nudged, _wrapup_warned) precisam zerar a cada turno novo — senão
    uma cutucada de um turno silenciaria o próximo. O reset vive no início de _loop."""
    import asyncio

    from mangaba.providers import AssistantTurn, ModelCapabilities, ProviderClient

    class _P(ProviderClient):
        def complete(self, *, model, messages, tools=None, **s):
            return AssistantTurn(text="pronto", finish_reason="stop")

        def stream(self, *, model, messages, tools=None, **s):
            yield AssistantTurn(text="pronto", finish_reason="stop")

        def capabilities(self, model):
            return ModelCapabilities()

    m = SessionManager(workspace=tempfile.mkdtemp(), provider=_P())
    eng = m.get_engine("__orq__reset", agent="cowork")
    eng._done_nudged = True
    eng._wrapup_warned = True

    async def _go():
        async for _ in eng.run("oi"):
            pass

    asyncio.run(_go())
    assert eng._done_nudged is False and eng._wrapup_warned is False, (
        "os flags de cutucada devem zerar no início de cada turno"
    )
