"""Tests for MCP (C1): config loading/merge, tool wrapping + bridge, and REST.

No live MCP subprocess is needed — the connection layer is exercised by stubbing the call
coroutine; a live-server smoke test is documented in the plan instead.
"""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from mangaba.mcp import build_callables, load_mcp_servers, tool_name
from mangaba.mcp.config import MCPServerDef
from mangaba.secrets import SecretStore
from mangaba.server.app import create_app
from mangaba.server.manager import SessionManager


def _write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


def _fake_tool(name, schema=None, description="desc", read_only=None):
    ann = SimpleNamespace(readOnlyHint=read_only) if read_only is not None else None
    return SimpleNamespace(
        name=name,
        description=description,
        annotations=ann,
        inputSchema=schema
        or {
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
        },
    )


def test_readonly_tools_skip_approval():
    """readOnlyHint=True → roda sem aprovação (busca de docs não pede 'Permitir?' toda vez);
    escrita e ferramentas sem a anotação seguem o padrão do servidor (aprovação ligada)."""
    server = MCPServerDef(name="notion", transport="http", requires_approval=True)
    fns = build_callables(
        server,
        [
            _fake_tool("search", read_only=True),
            _fake_tool("create_page", read_only=False),
            _fake_tool("mystery"),
        ],
        lambda t, a: None,
        asyncio.new_event_loop(),
    )
    by = {f.__name__: f.__aisuite_tool_metadata__.requires_approval for f in fns}
    assert by["mcp__notion__search"] is False
    assert by["mcp__notion__create_page"] is True
    assert by["mcp__notion__mystery"] is True


def test_server_requires_approval_false_overrides_all():
    """`requires_approval: false` no config desliga a aprovação do servidor inteiro."""
    server = MCPServerDef(name="docs", transport="http", requires_approval=False)
    fns = build_callables(
        server, [_fake_tool("fetch")], lambda t, a: None, asyncio.new_event_loop()
    )
    assert fns[0].__aisuite_tool_metadata__.requires_approval is False


# -- config --------------------------------------------------------------------
def test_load_merges_global_and_workspace(tmp_path, monkeypatch):
    monkeypatch.setenv("MANGABA_STATE_DIR", str(tmp_path / "state"))
    _write_json(
        tmp_path / "state" / "mcp.json",
        {
            "mcpServers": {
                "fs": {"command": "echo", "args": ["global"], "enabled": True},
                "docs": {"type": "http", "url": "https://x/mcp", "enabled": False},
            }
        },
    )
    ws = tmp_path / "ws"
    _write_json(
        ws / ".mangaba" / "mcp.json",
        {
            "mcpServers": {
                "fs": {"command": "echo", "args": ["workspace-loses"]},  # clashes: global wins
                "ws_only": {"command": "echo", "args": ["ws"], "enabled": True},
            }
        },
    )

    servers = {s.name: s for s in load_mcp_servers(ws, secrets=SecretStore())}
    # Global wins on name clash; a non-clashing workspace server still loads.
    assert servers["fs"].args == ["global"]
    assert servers["ws_only"].args == ["ws"]
    assert servers["fs"].transport == "stdio"
    assert servers["docs"].transport == "http" and servers["docs"].enabled is False
    assert servers["docs"].requires_approval is True  # default


def test_var_resolution(tmp_path, monkeypatch):
    monkeypatch.setenv("MANGABA_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("DOCS_TOKEN", "sekret")
    _write_json(
        tmp_path / "state" / "mcp.json",
        {
            "mcpServers": {
                "docs": {
                    "type": "http",
                    "url": "https://x/mcp",
                    "headers": {"Authorization": "Bearer ${DOCS_TOKEN}"},
                },
            }
        },
    )
    docs = load_mcp_servers(None, secrets=SecretStore())[0]
    assert docs.headers["Authorization"] == "Bearer sekret"


# -- tool wrapping + bridge ----------------------------------------------------
def test_tool_name_sanitizes():
    assert tool_name("fs", "read_file") == "mcp__fs__read_file"
    assert "." not in tool_name("a.b", "c.d")


def test_schema_and_metadata():
    server = MCPServerDef(name="fs", transport="stdio", requires_approval=True)
    fns = build_callables(
        server, [_fake_tool("read_file")], lambda t, a: None, asyncio.new_event_loop()
    )
    fn = fns[0]
    assert fn.__name__ == "mcp__fs__read_file"
    meta = fn.__aisuite_tool_metadata__
    assert meta.category == "mcp" and meta.requires_approval is True
    schema = fn.__mangaba_schema__["function"]
    assert schema["name"] == "mcp__fs__read_file"
    assert schema["parameters"]["required"] == ["path"]


def test_include_exclude_filter():
    server = MCPServerDef(name="fs", transport="stdio", include_tools=["read_file"])
    fns = build_callables(
        server,
        [_fake_tool("read_file"), _fake_tool("delete_file")],
        lambda t, a: None,
        asyncio.new_event_loop(),
    )
    assert [f.__name__ for f in fns] == ["mcp__fs__read_file"]


async def test_bridge_invokes_session_on_loop():
    loop = asyncio.get_running_loop()
    seen = []

    async def call_async(tool, args):
        seen.append((tool, args))
        return {"echo": args}

    server = MCPServerDef(name="fs", transport="stdio")
    fn = build_callables(server, [_fake_tool("read_file")], call_async, loop)[0]
    # The engine runs tools via to_thread; the wrapper bridges back to this loop.
    result = await asyncio.to_thread(fn, path="a.txt")
    assert result == {"echo": {"path": "a.txt"}}
    assert seen == [("read_file", {"path": "a.txt"})]


# -- REST ----------------------------------------------------------------------
def test_rest_crud(tmp_path, monkeypatch):
    monkeypatch.setenv("MANGABA_STATE_DIR", str(tmp_path / "state"))
    manager = SessionManager(data_dir=tmp_path / "data")
    client = TestClient(create_app(manager))

    assert client.get("/v1/mcp").json()["servers"] == []

    r = client.post(
        "/v1/mcp",
        json={
            "name": "fs",
            "config": {"command": "echo", "args": ["x"], "env": {"SECRET": "shh"}},
        },
    )
    assert r.json()["ok"] is True

    servers = client.get("/v1/mcp").json()["servers"]
    assert servers[0]["name"] == "fs" and servers[0]["status"] == "configured"
    assert servers[0]["config"]["env"]["SECRET"] == "***"  # redacted

    assert client.patch("/v1/mcp/fs", json={"enabled": False}).json()["ok"] is True
    assert client.get("/v1/mcp").json()["servers"][0]["enabled"] is False

    assert client.delete("/v1/mcp/fs").json()["ok"] is True
    assert client.get("/v1/mcp").json()["servers"] == []
    assert client.delete("/v1/mcp/fs").json()["ok"] is False


def test_runtime_ausente_nomeia_o_que_instalar(monkeypatch):
    """Servidor MCP publicado quase sempre roda por `npx` (Node) — que a máquina de um
    dev tem e a de um usuário comum não. Sem isto o erro na tela era o do SO, e no
    Windows é '[WinError 2] O sistema não pode encontrar o arquivo especificado':
    não diz o que instalar, e o MCP parecia simplesmente não funcionar."""
    from mangaba.mcp import client

    monkeypatch.setattr(client.shutil if hasattr(client, "shutil") else __import__("shutil"), "which", lambda c: None)
    import shutil as _sh

    monkeypatch.setattr(_sh, "which", lambda c: None)

    msg = client._runtime_ausente("npx")
    assert msg and "Node.js" in msg and "nodejs.org" in msg

    msg_uv = client._runtime_ausente("uvx")
    assert msg_uv and "uv" in msg_uv

    generico = client._runtime_ausente("servidor-proprio")
    assert generico and "caminho completo" in generico


def test_runtime_presente_nao_reclama(monkeypatch):
    from mangaba.mcp import client
    import shutil as _sh

    monkeypatch.setattr(_sh, "which", lambda c: "/usr/bin/" + c)
    assert client._runtime_ausente("npx") is None
    assert client._runtime_ausente("") is None


def test_catalogo_e_dominado_por_http_que_nao_exige_runtime():
    """A correção do relato dos usuários: servidor HTTP não precisa de NADA instalado.
    Catalogar só servidores `npx` teria mantido o problema — no Windows falta Node,
    e o erro que chega é '[WinError 2]', que não diz o que instalar."""
    from mangaba.mcp import catalog

    itens = catalog.listar()
    http = [i for i in itens if i["transport"] == "http"]
    assert len(http) >= 12, "o catálogo precisa ser dominado por HTTP"
    assert all(i["runtime_pronto"] for i in http), "HTTP nunca depende de runtime local"

    # e existe um caminho 'instala e já usa': HTTP sem OAuth
    sem_login = [i for i in http if not i["oauth"]]
    assert len(sem_login) >= 5


def test_catalogo_monta_config_http_com_oauth():
    from mangaba.mcp import catalog

    cfg = catalog.montar_config("notion")
    assert cfg["type"] == "http" and cfg["auth"] == "oauth"
    assert cfg["url"].startswith("https://")

    aberto = catalog.montar_config("context7")
    assert "auth" not in aberto and aberto["requires_approval"] is False


def test_catalogo_tem_servidores_prontos_para_instalar():
    """A aba MCP nascia VAZIA e só aceitava JSON digitado à mão — tarefa de
    desenvolvedor. Quem instalou o app abria, lia 'nenhum servidor' e não tinha o que
    fazer ali; na máquina de quem desenvolve o mcp.json já existia, então só os
    usuários sentiram."""
    from mangaba.mcp import catalog

    itens = catalog.listar()
    assert len(itens) >= 5
    for i in itens:
        assert i["titulo"] and i["blurb"]
        assert "runtime_pronto" in i and "runtime_url" in i
        assert "config" not in i  # a config só é montada na instalação


def test_catalogo_monta_config_substituindo_campos():
    from mangaba.mcp import catalog

    cfg = catalog.montar_config("filesystem", {"pasta": "/tmp/liberado"})
    assert cfg["command"] == "npx"
    assert "/tmp/liberado" in cfg["args"]


def test_catalogo_recusa_campo_obrigatorio_vazio():
    import pytest

    from mangaba.mcp import catalog

    with pytest.raises(ValueError, match="Pasta liberada"):
        catalog.montar_config("filesystem", {})
    with pytest.raises(ValueError, match="desconhecido"):
        catalog.montar_config("nao-existe", {})


def test_catalogo_marca_runtime_ausente(monkeypatch):
    """O aviso precisa vir ANTES de instalar: no Windows sem Node, tentar e falhar
    devolvia '[WinError 2]', que não diz o que instalar."""
    import shutil as _sh

    from mangaba.mcp import catalog

    monkeypatch.setattr(_sh, "which", lambda c: None)
    itens = {i["name"]: i for i in catalog.listar()}
    assert itens["filesystem"]["runtime_pronto"] is False
    assert "nodejs.org" in itens["filesystem"]["runtime_url"]
    # ...mas os HTTP seguem instaláveis mesmo sem Node/uv na máquina
    assert itens["context7"]["runtime_pronto"] is True
    assert itens["notion"]["runtime_pronto"] is True


def test_catalogo_de_crm_so_tem_endpoint_que_respondeu():
    """Cada URL de CRM foi testada antes de entrar: um POST de `initialize` que volta 401
    prova que o servidor existe e só falta login. O do Salesforce ficou de FORA — a
    imprensa o dá como oficial, mas mcp.salesforce.com não resolveu (05/08/2026).
    Catalogar endereço que não responde é prometer o que não existe."""
    from mangaba.mcp import catalog

    crm = [i for i in catalog.listar() if i["categoria"] == "CRM e vendas"]
    assert len(crm) >= 8
    nomes = {i["titulo"] for i in crm}
    assert {"HubSpot", "Pipedrive", "Attio", "Close", "Intercom"} <= nomes
    assert "Salesforce" not in nomes, "endpoint não verificado não entra no catálogo"

    # CRM mexe em dado de cliente: login e aprovação são obrigatórios
    for i in crm:
        assert i["oauth"] is True, f"{i['titulo']} tem de exigir login"
        assert i["requires_approval"] is True, f"{i['titulo']} tem de pedir aprovação"
        assert i["transport"] == "http"
