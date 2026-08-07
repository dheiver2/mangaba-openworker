"""Phase 2 gate — the Inbox: 3 item kinds, the resolve state machine, reconciliation, approver."""

from __future__ import annotations

import asyncio

from mangaba.inbox import (
    KIND_APPROVAL,
    KIND_NOTIFICATION,
    STATE_RESOLVED,
    InboxStore,
    inbox_approver,
)


def test_add_and_filter(tmp_path):
    store = InboxStore(tmp_path / "inbox.json")
    store.add_approval("s1", "Run shell?")
    store.add_question("s1", "Which env?")
    store.add_notification("s2", "Report ready")
    assert len(store.list(session_id="s1")) == 2
    assert len(store.pending("s1")) == 2
    assert store.list(session_id="s2")[0].kind == KIND_NOTIFICATION


def test_resolve_is_idempotent_first_responder_wins(tmp_path):
    store = InboxStore(tmp_path / "inbox.json")
    item = store.add_approval("s1", "Run shell?")
    assert store.resolve(item.id, "allow") is True
    # A second resolution from any surface is a no-op; the first answer stands.
    assert store.resolve(item.id, "deny") is False
    got = store.get(item.id)
    assert got.state == STATE_RESOLVED and got.resolution == "allow"


def test_resolve_unknown_item(tmp_path):
    store = InboxStore(tmp_path / "inbox.json")
    assert store.resolve("nope", "allow") is False


def test_persistence(tmp_path):
    store = InboxStore(tmp_path / "inbox.json")
    item = store.add_approval("s1", "Run shell?")
    store.resolve(item.id, "allow")
    reloaded = InboxStore(tmp_path / "inbox.json")
    assert reloaded.get(item.id).resolution == "allow"


def test_reconcile_on_resume(tmp_path):
    store = InboxStore(tmp_path / "inbox.json")
    answered = store.add_approval("s1", "Deploy?")
    store.resolve(answered.id, "allow")
    store.add_question("s1", "Still pending?")
    store.add_approval("other", "Not mine")
    out = store.reconcile_on_resume("s1")
    assert [i["title"] for i in out["pending"]] == ["Still pending?"]
    assert [i["title"] for i in out["recap"]] == ["Deploy?"]


def test_inbox_approver_allow(tmp_path):
    async def run():
        store = InboxStore(tmp_path / "inbox.json")
        from mangaba.engine import ApprovalOutcome, PermissionRequest

        approver = inbox_approver(store, "s1")
        req = PermissionRequest("run_shell", {}, None, "needs approval")

        async def resolve_soon():
            for _ in range(200):
                pend = store.pending("s1")
                if pend:
                    store.resolve(pend[0].id, "allow")
                    return
                await asyncio.sleep(0.001)

        outcome, _ = await asyncio.gather(approver(req), resolve_soon())
        assert outcome is ApprovalOutcome.ONCE
        # The approval came in as an Inbox item.
        assert store.list(session_id="s1")[0].kind == KIND_APPROVAL

    asyncio.run(run())


def test_inbox_approver_deny(tmp_path):
    async def run():
        store = InboxStore(tmp_path / "inbox.json")
        from mangaba.engine import ApprovalOutcome, PermissionRequest

        approver = inbox_approver(store, "s1")
        req = PermissionRequest("rm", {}, None, "danger")

        async def resolve_soon():
            for _ in range(200):
                pend = store.pending("s1")
                if pend:
                    store.resolve(pend[0].id, "deny")
                    return
                await asyncio.sleep(0.001)

        outcome, _ = await asyncio.gather(approver(req), resolve_soon())
        assert outcome is ApprovalOutcome.DENY

    asyncio.run(run())


def test_args_preview():
    from mangaba.inbox import args_preview

    assert (
        args_preview({"path": "g.txt", "content": "buy milk"})
        == "path: g.txt · content: buy milk"
    )
    assert args_preview(None) == "" and args_preview({}) == ""
    assert "\n" not in args_preview({"x": "a\nb\nc"})  # newlines collapsed
    assert args_preview({"content": "z" * 300}).endswith("…")  # long values truncated


def test_approval_body_includes_tool_args():
    from mangaba.engine import PermissionRequest
    from mangaba.server.manager import _approval_body

    req = PermissionRequest(
        "write_file", {"path": "groceries.txt", "content": "buy milk"}, None, ""
    )
    body = _approval_body(req)
    assert "groceries.txt" in body and "buy milk" in body  # the card now shows *what*

    req2 = PermissionRequest("rm", {"path": "/x"}, None, "destructive")
    assert _approval_body(req2).startswith("destructive")  # reason leads when present


def test_opcoes_em_objeto_viram_texto(tmp_path):
    """Um modelo pode responder ask_user com `{label, description}` no lugar de texto.

    A UI usa cada opção como filho de React e como `key` do botão, então um objeto
    aqui derrubava a janela inteira (React #31 + keys duplicadas) e o item envenenado
    ficava gravado no inbox, tornando o app impossível de abrir.
    """
    store = InboxStore(tmp_path / "inbox.json")
    item = store.add_question(
        "s1",
        "Como seguir?",
        options=[
            {"label": "Reenviar", "description": "anexe de novo"},
            {"label": "Colar texto"},
            "Cancelar",
        ],
    )
    assert item.options == ["Reenviar — anexe de novo", "Colar texto", "Cancelar"]
    assert all(isinstance(o, str) for o in item.options)


def test_inbox_gravado_com_opcoes_ruins_e_saneado_na_leitura(tmp_path):
    """Inboxes já no disco carregam o formato ruim; sanear no load destrava o app."""
    import json

    caminho = tmp_path / "inbox.json"
    caminho.write_text(
        json.dumps(
            {
                "items": [
                    {
                        "id": "x1",
                        "session_id": "s1",
                        "kind": "question",
                        "title": "Como seguir?",
                        "options": [{"label": "A", "description": "faz A"}],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    store = InboxStore(caminho)
    assert store.get("x1").options == ["A — faz A"]


def test_opcoes_duplicadas_sao_colapsadas(tmp_path):
    """Opções repetidas viram `key` duplicada de React — colapsa em vez de avisar."""
    store = InboxStore(tmp_path / "inbox.json")
    item = store.add_question("s1", "Qual?", options=["Sim", "Sim", " Sim ", "Não"])
    assert item.options == ["Sim", "Não"]
