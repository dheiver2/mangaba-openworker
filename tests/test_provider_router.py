"""Tests for the multi-provider layer: base_url passthrough, ProviderRouter routing/prefix
strip + caching, Ollama capabilities, and manager get/set_provider. SDK-free."""

from __future__ import annotations

from types import SimpleNamespace

from mangaba.providers import (
    AssistantTurn,
    ModelCapabilities,
    OpenAIProvider,
    ProviderClient,
    ProviderRouter,
    StreamChunk,
    capabilities_for,
)
from mangaba.providers.registry import build_provider_client
from mangaba.providers.openai_provider import _salvage_tool_calls_from_text


# -- base_url passthrough -------------------------------------------------------
def test_base_url_passed_to_sdk(monkeypatch):
    captured: dict = {}

    class FakeOpenAI:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setattr("openai.OpenAI", FakeOpenAI)
    OpenAIProvider(
        api_key="sk-x", base_url="http://localhost:11434/v1"
    )._ensure_client()
    assert captured == {"api_key": "sk-x", "base_url": "http://localhost:11434/v1"}


def test_base_url_omitted_when_none(monkeypatch):
    captured: dict = {}

    class FakeOpenAI:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setattr("openai.OpenAI", FakeOpenAI)
    OpenAIProvider(api_key="sk-x")._ensure_client()
    assert "base_url" not in captured


# -- router routing -------------------------------------------------------------
class _Recorder(ProviderClient):
    def __init__(self, name: str):
        self.name = name
        self.models: list[str] = []

    def complete(self, *, model, messages, tools=None, **settings):
        self.models.append(model)
        return AssistantTurn(text=self.name)

    def stream(self, *, model, messages, tools=None, **settings):
        self.models.append(model)
        yield StreamChunk(turn=AssistantTurn(text=self.name))

    def capabilities(self, model):
        return ModelCapabilities()


def _patch_build(monkeypatch):
    state: dict = {"created": [], "latest": {}}

    def fake_build(name, profile, secrets):
        rec = _Recorder(name)  # a fresh client each build, so rebuilds are observable
        state["created"].append(rec)
        state["latest"][name] = rec
        return rec

    monkeypatch.setattr("mangaba.providers.router.build_provider_client", fake_build)
    return state


def test_router_routes_and_strips_prefix(monkeypatch):
    state = _patch_build(monkeypatch)
    router = ProviderRouter(secrets=None)

    turn = router.complete(model="deepseek:deepseek-chat", messages=[])
    assert turn.text == "deepseek"
    assert state["latest"]["deepseek"].models == [
        "deepseek-chat"
    ]  # prefix stripped before delegating

    router.complete(model="gpt-5.5", messages=[])  # bare → default openai
    assert state["latest"]["openai"].models == ["gpt-5.5"]


def test_router_caches_and_invalidates(monkeypatch):
    state = _patch_build(monkeypatch)
    router = ProviderRouter(secrets=None)

    first = router._client_for("deepseek:a")
    second = router._client_for("deepseek:b")
    assert first is second  # same provider → cached client reused (build called once)
    assert len(state["created"]) == 1

    router.invalidate("deepseek")
    third = router._client_for("deepseek:c")
    assert third is not first  # rebuilt after invalidation
    assert len(state["created"]) == 2


def test_router_bare_only_strips_known_provider():
    r = ProviderRouter(secrets=None)
    assert (
        r._bare("deepseek:qwen2.5-coder:32b") == "qwen2.5-coder:32b"
    )  # strip provider, keep tag
    assert r._bare("gpt-5.5") == "gpt-5.5"
    # a colon that isn't a provider (version tag) must NOT be split — else OpenAI gets "32b"
    assert r._bare("qwen2.5-coder:32b") == "qwen2.5-coder:32b"
    assert r._provider_name("qwen2.5-coder:32b") == "openai"  # unknown prefix → default


def test_router_capabilities_prefix_aware():
    router = ProviderRouter(secrets=None)
    assert router.capabilities("anthropic:claude-fable-5").tools is True
    assert router.capabilities("anthropic:claude-fable-5").streaming is True


# -- capabilities ---------------------------------------------------------------
def test_salvage_bare_json_object():
    calls = _salvage_tool_calls_from_text(
        '{"name": "get_weather", "arguments": {"city": "Paris"}}'
    )
    assert len(calls) == 1
    assert calls[0].name == "get_weather"
    assert calls[0].arguments == {"city": "Paris"}


def test_salvage_tool_call_tags():
    text = '<tool_call>{"name": "a", "arguments": {"x": 1}}</tool_call>'
    calls = _salvage_tool_calls_from_text(text)
    assert [c.name for c in calls] == ["a"]


def test_salvage_multiple_via_array():
    text = '[{"name": "a", "arguments": {}}, {"name": "b", "arguments": {"y": 2}}]'
    calls = _salvage_tool_calls_from_text(text)
    assert [c.name for c in calls] == ["a", "b"]
    assert calls[1].arguments == {"y": 2}


def test_salvage_stringified_arguments():
    calls = _salvage_tool_calls_from_text('{"name": "a", "arguments": "{\\"k\\": 1}"}')
    assert calls[0].arguments == {"k": 1}


def test_salvage_ignores_non_toolcall_json():
    # Valid JSON, but not tool-call shaped → must stay text (no false positives).
    assert _salvage_tool_calls_from_text('{"city": "Paris", "temp": 18}') == []


def test_salvage_ignores_prose():
    assert _salvage_tool_calls_from_text("The weather in Paris is sunny.") == []
    assert _salvage_tool_calls_from_text("") == []


_TODO_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "todo_write",
            "parameters": {
                "type": "object",
                "properties": {"items": {"type": "array"}},
                "required": ["items"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_files",
            "parameters": {
                "type": "object",
                "properties": {"recursive": {"type": "boolean"}},
            },
        },
    },
]


def test_salvage_mixed_prose_and_object():
    # The model wrote prose THEN a bare-JSON tool call in one message.
    text = 'It seems the workspace is empty. {"name": "list_files", "arguments": {"recursive": true}}'
    calls = _salvage_tool_calls_from_text(text, _TODO_TOOLS)
    assert [c.name for c in calls] == ["list_files"]
    assert calls[0].arguments == {"recursive": True}


def test_salvage_toolname_bare_array_shorthand():
    # The exact shape from the user's session: `todo_write [ {…}, {…} ]` (name + bare array).
    text = 'todo_write [{"content": "Understand requirements", "status": "in_progress"}, {"content": "Plan", "status": "pending"}]'
    calls = _salvage_tool_calls_from_text(text, _TODO_TOOLS)
    assert len(calls) == 1 and calls[0].name == "todo_write"
    # bare array mapped onto the tool's sole parameter
    assert calls[0].arguments == {
        "items": [
            {"content": "Understand requirements", "status": "in_progress"},
            {"content": "Plan", "status": "pending"},
        ]
    }


def test_salvage_toolname_object_shorthand():
    calls = _salvage_tool_calls_from_text(
        'list_files {"recursive": false}', _TODO_TOOLS
    )
    assert calls[0].name == "list_files" and calls[0].arguments == {"recursive": False}


def test_salvage_filters_unknown_tool_name():
    # A {name,arguments} object whose name isn't an offered tool must NOT be salvaged.
    text = '{"name": "rm_rf", "arguments": {"path": "/"}}'
    assert _salvage_tool_calls_from_text(text, _TODO_TOOLS) == []


def test_salvage_nested_braces_in_tag():
    text = '<tool_call>{"name": "todo_write", "arguments": {"items": [{"content": "a", "status": "pending"}]}}</tool_call>'
    calls = _salvage_tool_calls_from_text(text, _TODO_TOOLS)
    assert calls[0].name == "todo_write"
    assert calls[0].arguments == {"items": [{"content": "a", "status": "pending"}]}


class _FakeOAClient:
    def __init__(self, *, content=None, tool_calls=None):
        msg = SimpleNamespace(content=content, tool_calls=tool_calls)
        resp = SimpleNamespace(
            choices=[SimpleNamespace(message=msg, finish_reason="stop")]
        )
        self.chat = SimpleNamespace(
            completions=SimpleNamespace(create=lambda **k: resp)
        )


def test_complete_salvages_only_when_tools_requested():
    blob = '{"name": "get_weather", "arguments": {"city": "Paris"}}'
    tools = [{"type": "function", "function": {"name": "get_weather"}}]

    # tools requested + no structured calls → salvage, clear text
    p = OpenAIProvider(client=_FakeOAClient(content=blob))
    turn = p.complete(model="custom:x", messages=[], tools=tools)
    assert turn.has_tool_calls and turn.tool_calls[0].name == "get_weather"
    assert turn.text is None

    # no tools requested → identical content stays plain text (gate holds)
    p2 = OpenAIProvider(client=_FakeOAClient(content=blob))
    turn2 = p2.complete(model="custom:x", messages=[])
    assert not turn2.has_tool_calls
    assert turn2.text == blob


# -- manager get/set_provider ---------------------------------------------------
def test_manager_provider_config(tmp_path, monkeypatch):
    monkeypatch.setenv("MANGABA_STATE_DIR", str(tmp_path / "state"))
    from mangaba.server.manager import SessionManager

    mgr = SessionManager(data_dir=tmp_path)
    assert isinstance(mgr.provider, ProviderRouter)

    res = mgr.set_provider("openai", {"api_key": "sk-x"})
    assert res["ok"] is True

    provs = {p["name"]: p for p in mgr.get_providers()}
    assert provs["openai"]["configured"] is True
    assert provs["openai"]["needs_key"] is True
    # never leak secret values
    assert "api_key" not in provs["openai"].get("values", {})

    assert mgr.set_provider("nope", {})["ok"] is False  # unknown provider rejected


def test_manager_curated_models(tmp_path, monkeypatch):
    """O seletor é a matriz curada, filtrada aos provedores com chave, mais os ids que o
    usuário adicionou. Instalação nova mostra os modelos da casa (sem chave, prontos) e
    nada de terceiro."""
    monkeypatch.setenv("MANGABA_STATE_DIR", str(tmp_path / "state"))
    from mangaba.providers.registry import provider_descriptors

    for d in provider_descriptors():  # ambient dev-shell keys must not leak in
        if d.env_key:
            monkeypatch.delenv(d.env_key, raising=False)
    from mangaba.server.manager import SessionManager

    mgr = SessionManager(data_dir=tmp_path)
    # sem chave nenhuma: nada além do padrão ativo (mantido selecionável)
    modelos = mgr.get_settings()["models"]
    assert mgr.model in modelos

    # a provider key unlocks exactly that provider's matrix models
    mgr.set_provider("anthropic", {"api_key": "sk-ant-test"})
    models = mgr.get_settings()["models"]
    assert "anthropic:claude-opus-4-8" in models
    assert "gpt-4o" not in models  # no OpenAI seed anywhere

    added = mgr.add_model("anthropic:claude-x-custom")  # configured provider → selectable
    assert added["ok"] and "anthropic:claude-x-custom" in added["models"]

    n = len(mgr.get_settings()["models"])
    mgr.add_model("anthropic:claude-x-custom")  # idempotent
    assert len(mgr.get_settings()["models"]) == n

    # removing a matrix model hides it persistently; re-adding unhides it
    removed = mgr.remove_model("anthropic:claude-haiku-4-5")
    assert "anthropic:claude-haiku-4-5" not in removed["models"]
    mgr2 = SessionManager(data_dir=tmp_path)  # survives a restart
    assert "anthropic:claude-haiku-4-5" not in mgr2.get_settings()["models"]
    mgr.add_model("anthropic:claude-haiku-4-5")
    assert "anthropic:claude-haiku-4-5" in mgr.get_settings()["models"]

    # removing a custom id drops it
    mgr.remove_model("anthropic:claude-x-custom")
    assert "anthropic:claude-x-custom" not in mgr.get_settings()["models"]

    # the active default stays selectable even if removed from the curated list
    mgr.remove_model(mgr.model)
    assert mgr.model in mgr.get_settings()["models"]

    assert mgr.add_model("  ")["ok"] is False  # empty rejected


def test_provider_builders(monkeypatch):
    import pytest

    from mangaba.providers import AnthropicProvider, GeminiProvider
    from mangaba.providers.registry import build_provider_client

    # anthropic and gemini are native: key resolution deferred to first call
    p = build_provider_client("anthropic", {"api_key": "sk-ant-x"}, None)
    assert isinstance(p, AnthropicProvider) and p._api_key == "sk-ant-x"
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="Anthropic"):
        build_provider_client("anthropic", {}, None)._ensure_client()

    g = build_provider_client("gemini", {"api_key": "AIza-x"}, None)
    assert isinstance(g, GeminiProvider) and g._api_key == "AIza-x"
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="Gemini"):
        build_provider_client("gemini", {}, None)._ensure_client()

    # OpenAI custom endpoint (Azure /openai/v1, OpenRouter, vLLM, …) passes through
    o = build_provider_client(
        "openai", {"base_url": "https://my.azure.example/openai/v1"}, None
    )
    assert o._base_url == "https://my.azure.example/openai/v1"
    assert build_provider_client("openai", {}, None)._base_url is None


def test_anthropic_gemini_capabilities():
    for m in ("anthropic:claude-sonnet-4-6", "gemini:gemini-2.5-flash"):
        caps = capabilities_for(m)
        assert caps.tools is True and caps.vision is True and caps.streaming is True
        assert caps.parallel_tool_calls is True  # both native: results fold correctly


def test_anthropic_gemini_provider_config(tmp_path, monkeypatch):
    monkeypatch.setenv("MANGABA_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    from mangaba.server.manager import SessionManager

    mgr = SessionManager(data_dir=tmp_path)
    provs = {p["name"]: p for p in mgr.get_providers()}
    assert provs["anthropic"]["configured"] is False
    assert provs["gemini"]["needs_key"] is True
    assert "claude-sonnet-4-6" in provs["anthropic"]["suggested_models"]
    assert "gemini-2.5-flash" in provs["gemini"]["suggested_models"]

    res = mgr.set_provider("anthropic", {"api_key": "sk-ant-test"})
    assert res["ok"] is True and res["recommended_model"] == "claude-fable-5"
    provs = {p["name"]: p for p in mgr.get_providers()}
    assert provs["anthropic"]["configured"] is True
    assert "api_key" not in provs["anthropic"].get("values", {})  # secrets never leak
    # the recommended model is auto-added to the curated list with its provider prefix
    assert "anthropic:claude-fable-5" in mgr.get_settings()["models"]

    # env var alone marks a provider configured
    monkeypatch.setenv("GEMINI_API_KEY", "AIza-env")
    provs = {p["name"]: p for p in mgr.get_providers()}
    assert provs["gemini"]["configured"] is True


def test_first_configured_provider_wins_default(tmp_path, monkeypatch):
    monkeypatch.setenv("MANGABA_STATE_DIR", str(tmp_path / "state"))
    for var in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GEMINI_API_KEY"):
        monkeypatch.delenv(var, raising=False)
    from mangaba.server.manager import SessionManager

    mgr = SessionManager(data_dir=tmp_path)
    # Instalação nova: o padrão de fábrica ainda não tem provedor configurado,
    # então o primeiro provedor com chave assume o padrão.
    assert mgr.model == "gpt-5.6-sol"

    mgr.set_provider("anthropic", {"api_key": "sk-ant-x"})
    assert mgr.model == "anthropic:claude-fable-5"

    # but a default that already works is never stolen by the next provider
    mgr.set_provider("gemini", {"api_key": "AIza-x"})
    assert mgr.model == "anthropic:claude-fable-5"


def test_surface_visibility(tmp_path, monkeypatch):
    monkeypatch.setenv("MANGABA_STATE_DIR", str(tmp_path / "state"))
    from mangaba.server.manager import SessionManager

    mgr = SessionManager(data_dir=tmp_path)
    # default: Cowork only
    s = mgr.get_settings()["surfaces"]
    assert s == {"cowork": True, "chat": False, "code": False}

    mgr.set_surfaces(chat=True)
    assert mgr.get_settings()["surfaces"]["chat"] is True
    assert mgr.get_settings()["surfaces"]["code"] is False  # untouched

    mgr.set_surfaces(code=True)
    assert mgr.get_settings()["surfaces"] == {
        "cowork": True,
        "chat": True,
        "code": True,
    }

    mgr.set_surfaces(chat=False)
    assert mgr.get_settings()["surfaces"]["chat"] is False
    # cowork is always on regardless
    assert mgr.get_settings()["surfaces"]["cowork"] is True


def test_provider_suggested_models(tmp_path, monkeypatch):
    monkeypatch.setenv("MANGABA_STATE_DIR", str(tmp_path / "state"))
    from mangaba.server.manager import SessionManager

    mgr = SessionManager(data_dir=tmp_path)
    provs = {p["name"]: p for p in mgr.get_providers()}
    assert "gpt-5.5" in provs["openai"]["suggested_models"]


# -- last-used tracking (router on_use hook + manager persistence) ----------------


def test_router_on_use_fires_with_provider_name():
    seen: list[str] = []
    router = ProviderRouter(on_use=seen.append)
    router._clients["openai"] = OpenAIProvider(client=_FakeOAClient(content="hi"))
    router._clients["zai"] = OpenAIProvider(client=_FakeOAClient(content="hi"))

    router.complete(model="gpt-5.5", messages=[])
    router.complete(model="zai:glm-5.2", messages=[])
    assert seen == ["openai", "zai"]


def test_router_on_use_failures_never_break_the_call():
    def boom(_name):
        raise RuntimeError("telemetry down")

    router = ProviderRouter(on_use=boom)
    router._clients["openai"] = OpenAIProvider(client=_FakeOAClient(content="ok"))
    assert router.complete(model="gpt-5.5", messages=[]).text == "ok"


def test_manager_key_hygiene_stamps(tmp_path, monkeypatch):
    """set_provider stamps key_set_at; _note_provider_use records (throttled) last_used_at;
    get_providers exposes both for the Settings pane."""
    monkeypatch.setenv("MANGABA_STATE_DIR", str(tmp_path / "state"))
    from datetime import date

    from mangaba.server.manager import SessionManager

    mgr = SessionManager(data_dir=tmp_path)
    mgr.set_provider("deepseek", {"api_key": "ds-key"})
    provs = {p["name"]: p for p in mgr.get_providers()}
    assert provs["deepseek"]["configured"] is True
    assert provs["deepseek"]["key_set_at"] == date.today().isoformat()
    assert provs["deepseek"]["last_used_at"] is None  # configured but never used

    # Endpoint-only re-save keeps the original stamp (the key wasn't touched).
    mgr.set_provider("deepseek", {"base_url": "https://api.deepseek.com/v1"})
    provs = {p["name"]: p for p in mgr.get_providers()}
    assert provs["deepseek"]["key_set_at"] == date.today().isoformat()

    mgr._note_provider_use("deepseek")
    first = mgr._prefs["provider_last_used"]["deepseek"]
    mgr._note_provider_use("deepseek")  # within the 60s throttle window → unchanged
    assert mgr._prefs["provider_last_used"]["deepseek"] == first
    provs = {p["name"]: p for p in mgr.get_providers()}
    assert provs["deepseek"]["last_used_at"] == first
    # and it survives a reload (persisted to prefs.json)
    mgr2 = SessionManager(data_dir=tmp_path)
    provs2 = {p["name"]: p for p in mgr2.get_providers()}
    assert provs2["deepseek"]["last_used_at"] == first


def test_ferramentas_viram_protocolo_no_prompt_para_api_sem_suporte_nativo(monkeypatch):
    """Endpoints que aceitam `tools` e o ignoram deixavam o modelo INVENTAR o resultado.
    Em vez de calar as ferramentas (que tiraria do agente ler arquivo, rodar comando e
    usar conector), ensinamos o protocolo no prompt: o parâmetro nativo não vai, mas a
    descrição das ferramentas vai, e a resposta é convertida de volta em chamadas reais."""
    from mangaba.providers.openai_provider import (
        OpenAIProvider,
        _mensagens_com_protocolo,
        _salvage_tool_calls_from_text,
    )

    ferramentas = [
        {
            "type": "function",
            "function": {
                "name": "read_file",
                "description": "Lê um arquivo do disco",
                "parameters": {
                    "type": "object",
                    "properties": {"path": {"type": "string"}},
                    "required": ["path"],
                },
            },
        }
    ]

    capturado = {}

    class ClienteFalso:
        class chat:  # noqa: N801 - espelha a forma do SDK
            class completions:
                @staticmethod
                def create(**kwargs):
                    capturado.update(kwargs)
                    raise RuntimeError("parar aqui: só queremos inspecionar a requisição")

    prov = OpenAIProvider(client=ClienteFalso(), api_key="x")
    # nenhum modelo curado declara tools=False hoje; simulamos um endpoint sem suporte
    sem_nativo = ModelCapabilities(tools=False, streaming=True)
    monkeypatch.setattr(
        "mangaba.providers.openai_provider.capabilities_for",
        lambda m: sem_nativo if m.startswith("semnativo:") else capabilities_for(m),
    )
    try:
        prov.complete(
            model="semnativo:chat",
            messages=[{"role": "user", "content": "leia o README.md"}],
            tools=ferramentas,
        )
    except Exception:
        pass

    # o parâmetro nativo NÃO vai (a API o ignoraria)...
    assert "tools" not in capturado
    # ...mas o protocolo e a assinatura da ferramenta vão, no sistema
    sistema = capturado["messages"][0]
    assert sistema["role"] == "system"
    assert "<tool_call>" in sistema["content"]
    assert "read_file(" in sistema["content"]

    # e a resposta do modelo volta a ser uma chamada de verdade
    calls = _salvage_tool_calls_from_text(
        '<tool_call>{"name": "read_file", "arguments": {"path": "README.md"}}</tool_call>',
        ferramentas,
    )
    assert [(c.name, c.arguments) for c in calls] == [("read_file", {"path": "README.md"})]

    # já um modelo COM suporte nativo continua recebendo o parâmetro, sem protocolo no prompt
    capturado.clear()
    try:
        prov.complete(
            model="anthropic:claude-fable-5",
            messages=[{"role": "user", "content": "oi"}],
            tools=ferramentas,
        )
    except Exception:
        pass
    assert capturado.get("tools") == ferramentas
    assert not any("<tool_call>" in (m.get("content") or "") for m in capturado["messages"])


def test_protocolo_preserva_a_mensagem_de_sistema_existente():
    """O prompt do agente é a mensagem de sistema — o protocolo se soma a ele, nunca o
    substitui, senão o agente perderia suas instruções."""
    from mangaba.providers.openai_provider import _mensagens_com_protocolo

    msgs = _mensagens_com_protocolo(
        [{"role": "system", "content": "VOCE E O MANGABA"}, {"role": "user", "content": "oi"}],
        [{"type": "function", "function": {"name": "f", "parameters": {}}}],
    )
    assert len(msgs) == 2
    assert "VOCE E O MANGABA" in msgs[0]["content"] and "<tool_call>" in msgs[0]["content"]
