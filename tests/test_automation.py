"""Tests for automation — models, store, next-run math, scheduler loop, tools, REST.

No network and no LLM: the scheduler's runner is injected with a fake; the agent-facing tools
operate on a real SQLite store; execution policy (catch-up, overlap) is exercised directly.
"""

from __future__ import annotations

import asyncio
import time
from datetime import datetime, timezone

import pytest

from mangaba.automation import (
    Schedule,
    ScheduledTask,
    Scheduler,
    TaskRun,
    TaskStore,
    compute_next_run,
)
from mangaba.automation.tools import scheduling_tools


def _task(**kw) -> ScheduledTask:
    kw.setdefault("title", "Daily brief")
    kw.setdefault("instructions", "search the web and brief me")
    kw.setdefault("schedule", Schedule(kind="cron", cron="10 19 * * *"))
    kw.setdefault("workspace", "/tmp/cw-auto")
    return ScheduledTask(**kw)


# -- model / schedule ----------------------------------------------------------
def test_schedule_human():
    assert Schedule("cron", cron="10 19 * * *").human() == "Every day at ~7:10 PM"
    assert "Monday" in Schedule("cron", cron="0 9 * * 0").human()
    assert Schedule("cron", cron="0 9 5 * *").human() == "Monthly on day 5 at ~9:00 AM"
    assert Schedule("once", fire_at="2026-07-01T09:00:00").human().startswith("Once at")


def test_task_gets_own_thread_id():
    t = _task()
    assert t.task_session_id == f"__task__{t.id}"
    assert t.public()["schedule"] == "Every day at ~7:10 PM"


def test_compute_next_run_cron_explicit_utc():
    t = _task(schedule=Schedule(kind="cron", cron="10 19 * * *", timezone="UTC"))
    after = datetime(2026, 6, 5, 18, 0, tzinfo=timezone.utc).timestamp()
    nxt = compute_next_run(t, after=after)
    assert datetime.fromtimestamp(nxt, tz=timezone.utc) == datetime(
        2026, 6, 5, 19, 10, tzinfo=timezone.utc
    )


def test_compute_next_run_defaults_to_local_time():
    """Default 'local' tz: '7:10pm' fires at 19:10 on the *machine's* clock, not UTC."""
    t = _task()  # Schedule default timezone == "local"
    assert t.schedule.timezone == "local"
    nxt = compute_next_run(t)
    local = datetime.fromtimestamp(nxt).astimezone()
    assert (local.hour, local.minute) == (19, 10)


def test_compute_next_run_once_in_past_is_none():
    past = "2020-01-01T00:00:00+00:00"
    t = _task(schedule=Schedule(kind="once", fire_at=past))
    assert compute_next_run(t) is None


# -- store ---------------------------------------------------------------------
def test_store_crud_and_due(tmp_path):
    store = TaskStore(tmp_path / "auto.db")
    t = _task(
        schedule=Schedule(kind="cron", cron="* * * * *")
    )  # every minute → due soon
    store.save(t)
    assert store.get(t.id).title == "Daily brief"
    assert [x.id for x in store.list()] == [t.id]
    # next_run computed + due() finds it once we're past next_run
    due = store.due(now=t.next_run + 1)
    assert [x.id for x in due] == [t.id]
    # disabled tasks are not due
    t.enabled = False
    store.save(t)
    assert store.due(now=t.next_run + 1 if t.next_run else 9e9) == []
    assert store.delete(t.id) is True and store.get(t.id) is None


def test_store_runs_history(tmp_path):
    store = TaskStore(tmp_path / "auto.db")
    t = _task()
    store.save(t)
    store.add_run(TaskRun(task_id=t.id, status="ok", result_text="hi"))
    store.add_run(TaskRun(task_id=t.id, status="error", error="boom"))
    runs = store.runs(t.id)
    assert len(runs) == 2 and runs[0].status in ("ok", "error")


# -- scheduler loop ------------------------------------------------------------
async def test_scheduler_runs_due_task_and_advances(tmp_path):
    store = TaskStore(tmp_path / "auto.db")
    t = _task(schedule=Schedule(kind="cron", cron="* * * * *"))
    store.save(t)
    # force it due now
    t.next_run = 1.0
    store.save(t)
    t.next_run = 1.0  # save() recomputes; push it into the past again
    store._conn.execute("UPDATE scheduled_tasks SET next_run=1.0 WHERE id=?", (t.id,))
    store._conn.commit()

    ran: list[str] = []

    async def runner(task, trigger):
        ran.append(task.id)
        return TaskRun(task_id=task.id, status="ok", trigger=trigger)

    sched = Scheduler(store, runner, tick_seconds=0.05)
    sched.start()
    await asyncio.sleep(0.2)
    await sched.stop()
    assert ran == [t.id]
    advanced = store.get(t.id)
    assert advanced.run_count == 1 and advanced.last_status == "ok"
    assert (
        advanced.next_run is not None and advanced.next_run > 1.0
    )  # moved to the future


async def test_scheduler_skips_overlapping_run(tmp_path):
    store = TaskStore(tmp_path / "auto.db")
    t = _task()
    store.save(t)
    gate = asyncio.Event()
    started = 0

    async def slow_runner(task, trigger):
        nonlocal started
        started += 1
        await gate.wait()
        return TaskRun(task_id=task.id, status="ok")

    sched = Scheduler(store, slow_runner)
    first = asyncio.create_task(sched.run_task(t, trigger="manual"))
    await asyncio.sleep(0.02)
    second = await sched.run_task(t, trigger="manual")  # overlaps → skipped
    assert second is None and started == 1
    gate.set()
    await first


# -- agent-facing tools --------------------------------------------------------
def test_create_and_list_tools(tmp_path):
    store = TaskStore(tmp_path / "auto.db")
    origin = {
        "surface": "cowork",
        "session_id": "s1",
        "workspace": "/tmp/ws",
        "agent": "cowork",
    }
    tools = {
        t.__name__: t
        for t in scheduling_tools(store, origin=origin, default_workspace="/tmp/ws")
    }

    out = tools["create_scheduled_task"](
        title="Brief", instructions="brief me", cron="10 19 * * *"
    )
    assert out["ok"] and out["schedule"] == "Every day at ~7:10 PM"
    # create surfaces a confirm card → gated
    assert (
        tools["create_scheduled_task"].__aisuite_tool_metadata__.requires_approval
        is True
    )

    listed = tools["list_scheduled_tasks"]()["tasks"]
    assert (
        len(listed) == 1
        and listed[0]["origin_session_id" if False else "title"] == "Brief"
    )
    saved = store.list()[0]
    assert saved.origin_session_id == "s1" and saved.workspace == "/tmp/ws"

    bad = tools["create_scheduled_task"](title="x", instructions="y", cron="not-a-cron")
    assert "invalid cron" in bad["error"]
    none = tools["create_scheduled_task"](title="x", instructions="y")
    assert "error" in none  # neither cron nor fire_at


def test_update_and_delete_tools(tmp_path):
    store = TaskStore(tmp_path / "auto.db")
    tools = {
        t.__name__: t
        for t in scheduling_tools(
            store, origin={"workspace": "/tmp/ws"}, default_workspace="/tmp/ws"
        )
    }
    tid = tools["create_scheduled_task"](
        title="X", instructions="do", cron="0 9 * * *"
    )["id"]
    assert (
        tools["update_scheduled_task"](id=tid, enabled=False)["task"]["enabled"]
        is False
    )
    assert store.get(tid).next_run is None  # disabled → no next run
    assert tools["delete_scheduled_task"](id=tid)["ok"] is True
    assert tools["update_scheduled_task"](id=tid)["error"]


# -- run persists as a continuable session -------------------------------------
async def test_scheduled_run_persists_continuable_session(tmp_path, monkeypatch):
    from mangaba.providers import AssistantTurn, ModelCapabilities, ProviderClient
    from mangaba.server.manager import SessionManager, _last_assistant_text

    class ScriptedProvider(ProviderClient):
        def __init__(self, turns):
            self._turns = list(turns)

        def complete(self, *, model, messages, tools=None, **settings):
            return self._turns.pop(0)

        def capabilities(self, model):
            return ModelCapabilities()

    monkeypatch.setenv("MANGABA_STATE_DIR", str(tmp_path / "state"))
    ws = tmp_path / "ws"
    ws.mkdir()
    # two turns: the scheduled run, then a follow-up question
    provider = ScriptedProvider(
        [
            AssistantTurn(text="Daily brief: all quiet.", finish_reason="stop"),
            AssistantTurn(text="Sure — here is more detail.", finish_reason="stop"),
        ]
    )
    manager = SessionManager(data_dir=tmp_path / "data", provider=provider)
    task = _task(workspace=str(ws), agent="cowork")
    manager.task_store.save(task)

    run = await manager._run_scheduled_task(task, trigger="manual")
    assert run.status == "ok" and run.session_id == f"__run__{run.run_id}"
    assert run.result_text == "Daily brief: all quiet."

    # the run is now a real, reopenable session with the transcript
    record = manager.session_store.load(run.session_id)
    assert (
        record is not None
        and record.workspace
        and any("Scheduled run" in (m.get("content") or "") for m in record.messages)
    )
    # …and it is continuable: a follow-up turn reuses the same thread
    engine = manager.get_engine(run.session_id, workspace=str(ws), agent="cowork")
    async for _ in engine.run("tell me more"):
        pass
    assert _last_assistant_text(engine.messages) == "Sure — here is more detail."


def test_task_engine_has_no_scheduling_tools(tmp_path, monkeypatch):
    """A scheduled run executes its instructions — it must not be able to (re)schedule. With
    instructions like 'every day at 5:32pm, prepare…', an agent holding create_scheduled_task
    creates another automation instead of doing the task."""
    from mangaba.providers import (
        AssistantTurn as _AT,
        ModelCapabilities,
        ProviderClient,
    )
    from mangaba.server import SessionManager

    class _Provider(ProviderClient):
        def complete(self, *, model, messages, tools=None, **settings):
            return _AT(text="ok", finish_reason="stop")

        def capabilities(self, model):
            return ModelCapabilities()

    monkeypatch.setenv("MANGABA_STATE_DIR", str(tmp_path / "state"))
    ws = tmp_path / "ws"
    ws.mkdir()
    manager = SessionManager(data_dir=tmp_path / "data", provider=_Provider())
    task = _task(workspace=str(ws), agent="cowork")
    manager.task_store.save(task)

    engine = manager._build_task_engine(task, session_id="__run__test")
    names = set(engine.registry.names())
    assert "create_scheduled_task" not in names
    assert "update_scheduled_task" not in names
    assert "write_file" in names  # the deliverable tools are still there


@pytest.mark.asyncio
async def test_scheduled_run_injects_mcp_tools(tmp_path, monkeypatch):
    """Regressão: a run agendada headless precisa receber as ferramentas de MCP/conector-backed,
    igual à sessão ao vivo. Antes, `_run_scheduled_task` nunca chamava `prepare_mcp_tools` nem
    passava `extra_tools` — um fluxo agendado que depende de Granola/Intercom (ou de conector
    MCP-backed como jira/monday) rodava SEM as tools e falhava em silêncio. Este teste prende a
    fiação: o que `prepare_mcp_tools` devolve tem de chegar ao engine da run."""
    from mangaba.providers import (
        AssistantTurn as _AT,
        ModelCapabilities,
        ProviderClient,
    )
    from mangaba.server.manager import SessionManager

    class _Provider(ProviderClient):
        def complete(self, *, model, messages, tools=None, **settings):
            return _AT(text="ok", finish_reason="stop")

        def capabilities(self, model):
            return ModelCapabilities()

    monkeypatch.setenv("MANGABA_STATE_DIR", str(tmp_path / "state"))
    ws = tmp_path / "ws"
    ws.mkdir()
    manager = SessionManager(data_dir=tmp_path / "data", provider=_Provider())
    task = _task(workspace=str(ws), agent="cowork")
    manager.task_store.save(task)

    # Uma tool MCP "de mentira" que só é registrável se `extra_tools` for de fato repassado.
    def mcp__fake__ping() -> str:
        """ferramenta de teste"""
        return "pong"

    sentinela = []
    prep_chamado = {}

    async def _fake_prepare(session_id, *, workspace=None, agent="code"):
        prep_chamado["session_id"] = session_id
        prep_chamado["workspace"] = workspace
        prep_chamado["agent"] = agent
        return [mcp__fake__ping]

    captura = {}
    real_build = manager._build_task_engine

    def _spy_build(task, *, session_id, extra_tools=None):
        captura["extra_tools"] = extra_tools
        return real_build(task, session_id=session_id, extra_tools=extra_tools)

    monkeypatch.setattr(manager, "prepare_mcp_tools", _fake_prepare)
    monkeypatch.setattr(manager, "_build_task_engine", _spy_build)

    run = await manager._run_scheduled_task(task, trigger="manual")

    # A preparação rodou com o workspace e o agente da task…
    assert prep_chamado["workspace"] == str(ws)
    assert prep_chamado["agent"] == "cowork"
    # …e o que ela devolveu chegou ao build do engine (o elo que faltava).
    assert captura["extra_tools"] == [mcp__fake__ping]
    # E a tool MCP existe de fato no engine da run headless.
    engine = manager._engines[run.session_id]
    assert "mcp__fake__ping" in set(engine.registry.names())


async def test_manual_run_prepare_and_finalize(tmp_path, monkeypatch):
    from mangaba.providers import AssistantTurn, ModelCapabilities, ProviderClient
    from mangaba.server.manager import SessionManager

    class ScriptedProvider(ProviderClient):
        def __init__(self, turns):
            self._turns = list(turns)

        def complete(self, *, model, messages, tools=None, **settings):
            return self._turns.pop(0)

        def capabilities(self, model):
            return ModelCapabilities()

    monkeypatch.setenv("MANGABA_STATE_DIR", str(tmp_path / "state"))
    ws = tmp_path / "ws"
    ws.mkdir()
    manager = SessionManager(
        data_dir=tmp_path / "data",
        provider=ScriptedProvider(
            [AssistantTurn(text="Done — briefing ready.", finish_reason="stop")]
        ),
    )
    task = _task(workspace=str(ws), agent="cowork")
    manager.task_store.save(task)

    # prepare: a "running" run + a session to open live (NOT executed yet)
    prep = manager.prepare_manual_run(task.id)
    assert prep["ok"] and prep["session_id"] == f"__run__{prep['run_id']}"
    # The prompt wraps the instructions in execute-now framing (so the live agent runs the task
    # instead of re-scheduling it) and carries them verbatim.
    assert prep["agent"] == "cowork"
    assert task.instructions in prep["prompt"]
    assert "do not create or modify any scheduled tasks" in prep["prompt"]
    assert manager.task_store.runs(task.id)[0].status == "running"

    # the GUI drives the run live over the session, then finalize records the outcome
    engine = manager.get_engine(prep["session_id"], workspace=str(ws), agent="cowork")
    async for _ in engine.run(prep["prompt"]):
        pass
    manager.save(prep["session_id"], engine)

    out = manager.finalize_manual_run(task.id, prep["run_id"])
    assert out["ok"] and out["run"]["status"] == "ok"
    assert out["run"]["result_text"] == "Done — briefing ready."
    assert manager.task_store.get(task.id).run_count == 1


# -- REST ----------------------------------------------------------------------
def test_automations_rest(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from mangaba.server.app import create_app
    from mangaba.server.manager import SessionManager

    monkeypatch.setenv("MANGABA_STATE_DIR", str(tmp_path / "state"))
    manager = SessionManager(data_dir=tmp_path / "data")
    # seed a task directly via the store
    t = _task(workspace=str(tmp_path / "ws"))
    manager.task_store.save(t)
    client = TestClient(create_app(manager))

    tasks = client.get("/v1/automations").json()["tasks"]
    assert (
        tasks[0]["title"] == "Daily brief"
        and tasks[0]["schedule"] == "Every day at ~7:10 PM"
    )
    assert (
        client.patch(f"/v1/automations/{t.id}", json={"enabled": False}).json()["task"][
            "enabled"
        ]
        is False
    )
    assert client.get(f"/v1/automations/{t.id}").json()["task"]["id"] == t.id
    assert client.delete(f"/v1/automations/{t.id}").json()["ok"] is True


# -- unseen-run tracking (UX-023 sidebar badges) --------------------------------
def test_unseen_runs_counted_and_cleared_by_mark_seen(tmp_path, monkeypatch):
    """list_automations surfaces unseen counts (runs after the seen mark), with
    unseen_failed keyed to the NEWEST unseen run; mark_automation_seen clears them
    and later runs count fresh."""
    monkeypatch.setenv("MANGABA_STATE_DIR", str(tmp_path / "state"))
    from mangaba.server.manager import SessionManager

    manager = SessionManager(data_dir=tmp_path / "data")
    t = manager.task_store.save(_task())
    manager.task_store.add_run(TaskRun(task_id=t.id, status="ok"))
    manager.task_store.add_run(TaskRun(task_id=t.id, status="error"))

    row = manager.list_automations()["tasks"][0]
    assert row["unseen_runs"] == 2
    assert row["unseen_failed"] is True  # newest unseen run errored

    assert manager.mark_automation_seen(t.id)["ok"]
    row = manager.list_automations()["tasks"][0]
    assert row["unseen_runs"] == 0 and row["unseen_failed"] is False

    time.sleep(0.01)  # a run strictly after the seen mark
    manager.task_store.add_run(TaskRun(task_id=t.id, status="ok"))
    row = manager.list_automations()["tasks"][0]
    assert row["unseen_runs"] == 1 and row["unseen_failed"] is False

    assert not manager.mark_automation_seen("task-nope")["ok"]


@pytest.mark.asyncio
async def test_scheduled_run_broadcasts_run_started_event(tmp_path, monkeypatch):
    """UX-026: the moment a scheduled run starts, every /ws/events socket hears
    automation_run_started (the top-right toast). Dead sockets drop silently."""
    from mangaba.providers import AssistantTurn, ModelCapabilities, ProviderClient
    from mangaba.server.manager import SessionManager

    class ScriptedProvider(ProviderClient):
        def complete(self, *, model, messages, tools=None, **settings):
            return AssistantTurn(text="done", finish_reason="stop")

        def capabilities(self, model):
            return ModelCapabilities()

    monkeypatch.setenv("MANGABA_STATE_DIR", str(tmp_path / "state"))
    ws = tmp_path / "ws"
    ws.mkdir()
    manager = SessionManager(data_dir=tmp_path / "data", provider=ScriptedProvider())
    task = _task(workspace=str(ws), agent="cowork")
    manager.task_store.save(task)

    heard: list = []

    async def listener(message):
        heard.append(message)

    async def dead(message):
        raise RuntimeError("socket gone")

    manager.register_event_client(listener)
    manager.register_event_client(dead)
    run = await manager._run_scheduled_task(task, trigger="schedule")

    (event,) = [m for m in heard if m["type"] == "automation_run_started"]
    assert event["data"]["task_id"] == task.id
    assert event["data"]["task_title"] == task.title
    assert event["data"]["session_id"] == run.session_id
    assert event["data"]["trigger"] == "schedule"
    assert dead not in manager._event_clients  # dropped, not fatal


# -- veredito do turno: run truncada não pode ser reportada como sucesso -------
@pytest.mark.asyncio
async def test_run_que_estoura_o_teto_de_rodadas_nao_vira_ok(tmp_path, monkeypatch):
    """A falha mais cara da autonomia: o engine PARA ao bater o teto de rodadas e diz isso
    em TURN_END (`max_iterations_exceeded`), mas o runner headless descartava todos os
    eventos e gravava `status="ok"`. O resultado salvo era a última fala do assistente —
    que, pelo aviso de fechamento em T-2, é justamente um resumo bem-escrito do trabalho
    pela metade — e com `notify_on_completion` o usuário era avisado de que terminou.
    Uma automação que entrega metade tem de dizer que entregou metade.
    """
    from mangaba.providers import AssistantTurn, ModelCapabilities, ProviderClient
    from mangaba.providers.base import ToolCall
    from mangaba.server.manager import SessionManager

    class _NuncaTermina(ProviderClient):
        """Sempre pede mais uma ferramenta — nunca emite um turno final."""

        def complete(self, *, model, messages, tools=None, **settings):
            return AssistantTurn(
                text="",
                tool_calls=[
                    ToolCall(
                        id="c1",
                        name="todo_write",
                        arguments={"todos": [{"content": "seguir", "status": "pending"}]},
                    )
                ],
                finish_reason="tool_calls",
            )

        def capabilities(self, model):
            return ModelCapabilities()

    state = tmp_path / "state"
    state.mkdir()
    (state / "config.toml").write_text("max_iterations = 2\n", encoding="utf-8")
    monkeypatch.setenv("MANGABA_STATE_DIR", str(state))
    ws = tmp_path / "ws"
    ws.mkdir()
    manager = SessionManager(data_dir=tmp_path / "data", provider=_NuncaTermina())
    task = _task(workspace=str(ws), agent="cowork")
    manager.task_store.save(task)

    run = await manager._run_scheduled_task(task, trigger="schedule")

    assert run.status == "partial", (
        f"run truncada gravada como {run.status!r} — o usuário seria avisado de um "
        "sucesso que não houve"
    )
    assert run.error and "rodada" in run.error.lower()


# -- plano carregado ENTRE execuções ------------------------------------------
@pytest.mark.asyncio
async def test_plano_aberto_e_retomado_na_execucao_seguinte(tmp_path, monkeypatch):
    """Cada disparo nascia numa sessão nova e amnésica: o que não coubesse numa execução
    recomeçava do zero na seguinte, para sempre. O plano agora vive na TAREFA — a execução
    que estoura o teto deixa os passos em aberto gravados, e a próxima os recebe semeados
    no engine e citados na abertura, para não refazer o que já está `done`.
    """
    from mangaba.providers import AssistantTurn, ModelCapabilities, ProviderClient
    from mangaba.providers.base import ToolCall
    from mangaba.server.manager import SessionManager

    passos = [
        {"id": "p1", "description": "consolidar planilhas", "status": "done"},
        {"id": "p2", "description": "calcular indicadores", "status": "pending"},
    ]

    class _EscrevePlanoESeArrasta(ProviderClient):
        """Grava o plano na 1ª rodada e depois nunca mais encerra — estoura o teto."""

        def __init__(self):
            self.primeira = True
            self.aberturas: list[str] = []

        def complete(self, *, model, messages, tools=None, **settings):
            if self.primeira:
                self.primeira = False
                self.aberturas.append(
                    next(m["content"] for m in messages if m.get("role") == "user")
                )
                return AssistantTurn(
                    text="",
                    tool_calls=[
                        ToolCall(id="c1", name="plan_write", arguments={"steps": passos})
                    ],
                    finish_reason="tool_calls",
                )
            return AssistantTurn(
                text="",
                tool_calls=[
                    ToolCall(
                        id="c2",
                        name="todo_write",
                        arguments={"todos": [{"content": "x", "status": "pending"}]},
                    )
                ],
                finish_reason="tool_calls",
            )

        def capabilities(self, model):
            return ModelCapabilities()

    state = tmp_path / "state"
    state.mkdir()
    (state / "config.toml").write_text("max_iterations = 2\n", encoding="utf-8")
    monkeypatch.setenv("MANGABA_STATE_DIR", str(state))
    ws = tmp_path / "ws"
    ws.mkdir()
    provider = _EscrevePlanoESeArrasta()
    manager = SessionManager(data_dir=tmp_path / "data", provider=provider)
    task = _task(workspace=str(ws), agent="cowork")
    manager.task_store.save(task)

    primeira = await manager._run_scheduled_task(task, trigger="schedule")
    assert primeira.status == "partial"

    gravada = manager.task_store.get(task.id)
    assert [p["id"] for p in gravada.plan] == ["p1", "p2"], (
        "o plano em aberto tem de sobreviver ao fim da execução, na tarefa"
    )

    # Segundo disparo: o plano volta semeado E a abertura diz o que já está pronto.
    provider.primeira = True
    await manager._run_scheduled_task(gravada, trigger="schedule")
    abertura = provider.aberturas[-1]
    assert "p2" in abertura and "calcular indicadores" in abertura
    assert "não refaça" in abertura.lower() or "nao refaça" in abertura.lower()


def test_plano_fechado_nao_vaza_para_a_proxima_execucao():
    """Plano concluído zera: herdá-lo faria a rodada seguinte abrir com passos de um
    trabalho que já acabou, e o done-gate cobraria o que ninguém pediu."""
    from mangaba.plan import Plan
    from mangaba.server.manager import _plano_pendente

    class _Eng:
        pass

    eng = _Eng()
    eng.plan = Plan()
    eng.plan.replace([{"id": "a", "description": "x", "status": "done"}])
    assert _plano_pendente(eng) == []
    eng.plan.replace([{"id": "a", "description": "x", "status": "blocked"}])
    assert [p["id"] for p in _plano_pendente(eng)] == ["a"]


@pytest.mark.asyncio
async def test_execucao_truncada_deixa_licao_na_memoria(tmp_path, monkeypatch):
    """O caminho não-supervisionado passa a aprender: sem usuário para corrigir, o sinal é
    o veredito da própria execução."""
    from mangaba.memory import Scope
    from mangaba.providers import AssistantTurn, ModelCapabilities, ProviderClient
    from mangaba.providers.base import ToolCall
    from mangaba.server.manager import SessionManager

    class _NuncaTermina(ProviderClient):
        def complete(self, *, model, messages, tools=None, **settings):
            return AssistantTurn(
                text="",
                tool_calls=[
                    ToolCall(
                        id="c1",
                        name="todo_write",
                        arguments={"todos": [{"content": "x", "status": "pending"}]},
                    )
                ],
                finish_reason="tool_calls",
            )

        def capabilities(self, model):
            return ModelCapabilities()

    state = tmp_path / "state"
    state.mkdir()
    (state / "config.toml").write_text("max_iterations = 2\n", encoding="utf-8")
    monkeypatch.setenv("MANGABA_STATE_DIR", str(state))
    ws = tmp_path / "ws"
    ws.mkdir()
    manager = SessionManager(data_dir=tmp_path / "data", provider=_NuncaTermina())
    task = _task(workspace=str(ws), agent="cowork", title="Fechamento do mês")
    manager.task_store.save(task)

    await manager._run_scheduled_task(task, trigger="schedule")

    licoes = manager.memory_store.list(scope=Scope.WORKSPACE, workspace=str(ws))
    assert any("Fechamento do mês" in m.content for m in licoes), (
        "a execução truncada tem de deixar lição — é o único sinal disponível quando "
        "não há usuário para corrigir"
    )


# -- a run MANUAL também para de mentir ----------------------------------------
def test_run_manual_truncada_nao_vira_ok(tmp_path, monkeypatch):
    """A mesma promessa do caminho headless, no botão 'Rodar agora': o finalize gravava
    "ok" às cegas. A pessoa via o aviso de teto ao vivo, mas o histórico da automação
    registrava o contrário do que ela viu."""
    from mangaba.plan import Plan
    from mangaba.server.manager import SessionManager

    monkeypatch.setenv("MANGABA_STATE_DIR", str(tmp_path / "state"))
    ws = tmp_path / "ws"
    ws.mkdir()
    manager = SessionManager(data_dir=tmp_path / "data")
    task = _task(workspace=str(ws), agent="cowork")
    manager.task_store.save(task)

    prep = manager.prepare_manual_run(task.id)
    assert prep["ok"] is True

    # Um engine "vivo" cujo último turno estourou o teto e deixou plano em aberto.
    class _Eng:
        pass

    eng = _Eng()
    eng.last_turn_status = "max_iterations_exceeded"
    eng.plan = Plan()
    eng.plan.replace([
        {"id": "p1", "description": "consolidar", "status": "done"},
        {"id": "p2", "description": "calcular", "status": "pending"},
    ])
    manager._engines[prep["session_id"]] = eng

    out = manager.finalize_manual_run(task.id, prep["run_id"])
    assert out["run"]["status"] == "partial", out["run"]
    assert out["run"]["error"]
    gravada = manager.task_store.get(task.id)
    assert gravada.last_status == "partial"
    assert [p["id"] for p in gravada.plan] == ["p1", "p2"], (
        "a run manual truncada também deixa o plano para o próximo disparo"
    )


def test_rodar_agora_herda_o_plano_da_execucao_anterior(tmp_path, monkeypatch):
    """Cenário real: a execução noturna parou no passo 3 e deixou o plano na tarefa; de
    manhã a pessoa clica 'Rodar agora'. O prompt precisa citar a retomada — sem isso a
    run manual refaz do zero exatamente o que a retomada preserva."""
    from mangaba.server.manager import SessionManager

    monkeypatch.setenv("MANGABA_STATE_DIR", str(tmp_path / "state"))
    ws = tmp_path / "ws"
    ws.mkdir()
    manager = SessionManager(data_dir=tmp_path / "data")
    task = _task(workspace=str(ws), agent="cowork")
    task.plan = [
        {"id": "p1", "description": "consolidar planilhas", "status": "done"},
        {"id": "p2", "description": "calcular indicadores", "status": "pending"},
    ]
    manager.task_store.save(task)

    prep = manager.prepare_manual_run(task.id)
    assert "p2" in prep["prompt"] and "calcular indicadores" in prep["prompt"]
    assert "não refaça" in prep["prompt"].lower() or "nao refaça" in prep["prompt"].lower()

    # E o engine da sessão da run nasce com o plano semeado (não só citado no texto).
    engine = manager.get_engine(prep["session_id"], agent=task.agent)
    assert [s.id for s in engine.plan.steps] == ["p1", "p2"]


@pytest.mark.asyncio
async def test_run_com_erro_de_provedor_nao_vira_ok(tmp_path, monkeypatch):
    """A brecha que a primeira correção não cobriu: erro de provedor no meio do turno não
    emite TURN_END — o engine captura a exceção, emite ERROR e retorna. O veredito ficava
    vazio e a run era gravada como "ok": modelo caiu (rate-limit, chave expirada, gateway
    fora) e o histórico dizia sucesso."""
    from mangaba.providers import AssistantTurn, ModelCapabilities, ProviderClient
    from mangaba.providers.base import ToolCall
    from mangaba.server.manager import SessionManager

    class _CaiNoMeio(ProviderClient):
        def __init__(self):
            self.chamadas = 0

        def complete(self, *, model, messages, tools=None, **settings):
            self.chamadas += 1
            if self.chamadas == 1:
                return AssistantTurn(
                    text="",
                    tool_calls=[
                        ToolCall(
                            id="c1",
                            name="todo_write",
                            arguments={"todos": [{"content": "x", "status": "pending"}]},
                        )
                    ],
                    finish_reason="tool_calls",
                )
            raise RuntimeError("gateway fora do ar")

        def capabilities(self, model):
            return ModelCapabilities()

    monkeypatch.setenv("MANGABA_STATE_DIR", str(tmp_path / "state"))
    ws = tmp_path / "ws"
    ws.mkdir()
    manager = SessionManager(data_dir=tmp_path / "data", provider=_CaiNoMeio())
    task = _task(workspace=str(ws), agent="cowork")
    manager.task_store.save(task)

    run = await manager._run_scheduled_task(task, trigger="schedule")
    assert run.status == "error", (
        f"modelo caiu no meio e a run foi gravada como {run.status!r}"
    )
    assert run.error and "gateway" in run.error


def test_run_retomada_apos_restart_e_fechada_no_historico(tmp_path, monkeypatch):
    """Run agendada parkeou numa aprovação e o servidor reiniciou: o runner original morreu
    e seu `finally` nunca roda. O durable resume termina o turno — mas o TaskRun ficava
    "running" para sempre no histórico, e o plano não voltava para a tarefa."""
    from mangaba.plan import Plan
    from mangaba.server.manager import SessionManager

    monkeypatch.setenv("MANGABA_STATE_DIR", str(tmp_path / "state"))
    ws = tmp_path / "ws"
    ws.mkdir()
    manager = SessionManager(data_dir=tmp_path / "data")
    task = _task(workspace=str(ws), agent="cowork")
    manager.task_store.save(task)
    run = TaskRun(task_id=task.id, trigger="schedule")  # "running", como o restart deixou
    manager.task_store.add_run(run)

    class _Eng:
        messages = [{"role": "assistant", "content": "terminei o que dava"}]

    eng = _Eng()
    eng.last_turn_status = "completed"
    eng.plan = Plan()
    eng.plan.replace([
        {"id": "p1", "description": "a", "status": "done"},
        {"id": "p2", "description": "b", "status": "pending"},
    ])

    manager._fechar_run_orfa(run.session_id, eng)

    fechada = manager.task_store.find_run(run.run_id)
    assert fechada.status == "ok" and fechada.finished_at is not None
    assert fechada.result_text == "terminei o que dava"
    gravada = manager.task_store.get(task.id)
    assert gravada.last_status == "ok" and gravada.run_count == 1
    assert [p["id"] for p in gravada.plan] == ["p1", "p2"]

    # Sessão que NÃO é run de automação: intocada (nada explode, nada é gravado).
    manager._fechar_run_orfa("sessao-comum", eng)
    # E fechar duas vezes não conta duas vezes.
    manager._fechar_run_orfa(run.session_id, eng)
    assert manager.task_store.get(task.id).run_count == 1
