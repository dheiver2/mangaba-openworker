"""Tests for the model API-key settings path (Tauri desktop Phase 2).

A Tauri-launched sidecar doesn't inherit the shell env, so the key may live only in the
SecretStore. These cover: the env→store resolver, the status shape (never leaks the key),
and the REST round-trip. No network, no model calls.
"""

from __future__ import annotations

from pathlib import Path

from mangaba.providers import resolve_api_key
from mangaba.secrets import SecretStore


def test_resolve_api_key_prefers_env(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-env-123")
    secrets = SecretStore(path=tmp_path / "secrets.json")
    secrets.put("provider:openai", {"type": "api_key", "api_key": "sk-store-999"})
    assert resolve_api_key(secrets) == "sk-env-123"


def test_resolve_api_key_falls_back_to_store(monkeypatch, tmp_path):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    secrets = SecretStore(path=tmp_path / "secrets.json")
    assert resolve_api_key(secrets) is None
    secrets.put("provider:openai", {"type": "api_key", "api_key": "sk-store-999"})
    assert resolve_api_key(secrets) == "sk-store-999"


def test_settings_rest_roundtrip(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from mangaba.server.app import create_app
    from mangaba.server.manager import SessionManager

    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("MANGABA_STATE_DIR", str(tmp_path / "state"))
    manager = SessionManager(data_dir=tmp_path / "data")
    client = TestClient(create_app(manager))

    before = client.get("/v1/settings").json()
    assert (
        before["has_key"] is False
        and before["source"] is None
        and before["provider"] == "openai"
    )
    assert before["onboarded"] is False and before["model"] in before["models"]

    set_resp = client.post(
        "/v1/settings/model-key", json={"api_key": "sk-secret-xyz"}
    ).json()
    assert (
        set_resp["ok"] is True
        and set_resp["has_key"] is True
        and set_resp["source"] == "store"
    )

    after = client.get("/v1/settings").json()
    assert after["has_key"] is True
    # the key value is never returned by either endpoint
    assert "sk-secret-xyz" not in str(set_resp) and "api_key" not in after

    # empty key is rejected
    assert (
        client.post("/v1/settings/model-key", json={"api_key": "  "}).json()["ok"]
        is False
    )


def test_default_model_and_onboarding_persist(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from mangaba.server.app import create_app
    from mangaba.server.manager import SessionManager

    monkeypatch.setenv("MANGABA_STATE_DIR", str(tmp_path / "state"))
    data_dir = tmp_path / "data"
    client = TestClient(create_app(SessionManager(data_dir=data_dir)))

    # set a default model + mark onboarded
    assert (
        client.post("/v1/settings/default-model", json={"model": "gpt-4o"}).json()[
            "model"
        ]
        == "gpt-4o"
    )
    assert (
        client.post("/v1/settings/onboarded", json={"value": True}).json()["onboarded"]
        is True
    )
    assert (
        client.post("/v1/settings/default-model", json={"model": " "}).json()["ok"]
        is False
    )

    # a fresh manager over the same data dir restores both from prefs.json
    reborn = SessionManager(data_dir=data_dir)
    assert reborn.model == "gpt-4o"
    s = reborn.get_settings()
    assert s["onboarded"] is True and s["model"] == "gpt-4o"


def test_nav_layout_setting_roundtrips(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from mangaba.server.app import create_app
    from mangaba.server.manager import SessionManager

    monkeypatch.setenv("MANGABA_STATE_DIR", str(tmp_path / "state"))
    data_dir = tmp_path / "data"
    client = TestClient(create_app(SessionManager(data_dir=data_dir)))

    # defaults to "flat"
    assert client.get("/v1/settings").json()["nav_layout"] == "flat"

    resp = client.post("/v1/settings/nav-layout", json={"nav_layout": "grouped"}).json()
    assert resp == {"ok": True, "nav_layout": "grouped"}
    assert client.get("/v1/settings").json()["nav_layout"] == "grouped"

    # unknown value falls back to flat; persists across a restart
    assert (
        client.post("/v1/settings/nav-layout", json={"nav_layout": "bogus"}).json()[
            "nav_layout"
        ]
        == "flat"
    )
    client.post("/v1/settings/nav-layout", json={"nav_layout": "grouped"})
    reborn = SessionManager(data_dir=data_dir)
    assert reborn.get_settings()["nav_layout"] == "grouped"


def test_scratch_base_setting_persists_and_drives_provisioning(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from mangaba.server.app import create_app
    from mangaba.server.manager import SessionManager

    monkeypatch.setenv("MANGABA_STATE_DIR", str(tmp_path / "state"))
    data_dir = tmp_path / "data"
    client = TestClient(create_app(SessionManager(data_dir=data_dir)))

    # defaults to ~/Mangaba
    assert client.get("/v1/settings").json()["scratch_base"] == "~/Mangaba"

    base = tmp_path / "my mangaba files"
    resp = client.post("/v1/settings/scratch-base", json={"path": str(base)}).json()
    assert resp["ok"] is True and resp["scratch_base"] == str(base)
    assert base.is_dir()  # created on set
    assert (
        client.post("/v1/settings/scratch-base", json={"path": " "}).json()["ok"]
        is False
    )

    # persists across a restart and actually drives where scratch dirs are provisioned
    reborn = SessionManager(data_dir=data_dir)
    assert reborn.get_settings()["scratch_base"] == str(base)
    scratch = reborn._provision_scratch("sess-xyz")
    assert Path(scratch) == (base / "sess-xyz").resolve() and Path(scratch).is_dir()


def test_mangaba_models_gated_on_liveness(tmp_path, monkeypatch):
    """`mangaba:*` entries show only while a local Ollama answers — keyless must not mean
    always-present (a stray mangaba:<junk> pref would otherwise render forever)."""
    from mangaba.server.manager import SessionManager

    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("MANGABA_STATE_DIR", str(tmp_path / "state"))
    manager = SessionManager(data_dir=tmp_path / "data")
    manager.add_model("mangaba:llama3.3")

    monkeypatch.setattr(SessionManager, "_mangaba_alive", lambda self: False)
    assert "mangaba:llama3.3" not in manager.get_settings()["models"]

    monkeypatch.setattr(SessionManager, "_mangaba_alive", lambda self: True)
    assert "mangaba:llama3.3" in manager.get_settings()["models"]


def test_lista_modelos_que_o_gateway_oferece(tmp_path, monkeypatch):
    """A lista vem do próprio gateway (`/v1/models`), então o app nunca oferece um modelo que
    aquela instância não serve — e um gateway apontado para outro endereço é respeitado."""
    from mangaba.server.manager import SessionManager

    manager = SessionManager(data_dir=tmp_path / "data")

    class FakeResp:
        status_code = 200

        def json(self):
            return {"data": [{"id": "mangaba-chat"}, {"id": "mangaba-code"}]}

    vistos = []

    def fake_get(url, timeout=None):
        vistos.append(url)
        return FakeResp()

    monkeypatch.setattr("httpx.get", fake_get)
    assert manager._mangaba_models() == ["mangaba:mangaba-chat", "mangaba:mangaba-code"]
    assert vistos and vistos[0].endswith("/v1/models")

def test_detect_persiste_o_perfil_para_os_modelos_aparecerem(tmp_path, monkeypatch):
    """Clicar em Detectar num provedor SEM CHAVE precisa persistir um perfil, senão a busca de
    modelos (que lê esse perfil) volta vazia e o seletor nunca recebe nada — o provedor pode
    reportar `configured: true` para sempre sem um único modelo chegar ao chat."""
    from mangaba.server.manager import SessionManager

    manager = SessionManager(data_dir=tmp_path / "data")
    assert manager.secrets.get("provider:mangaba") is None  # nada salvo ainda

    class FakeResp:
        status_code = 200

        def json(self):
            return {"data": [{"id": "mangaba-chat"}, {"id": "mangaba-code"}]}

    monkeypatch.setattr("httpx.get", lambda url, timeout=None: FakeResp())

    res = manager.set_provider("mangaba", {})
    assert res["ok"] is True
    assert manager.secrets.get("provider:mangaba") is not None  # agora persistido
    assert "mangaba:mangaba-chat" in manager.get_settings()["models"]

def test_settings_rotula_todo_modelo_que_o_gateway_oferece(tmp_path, monkeypatch):
    """A lista de Configurações ▸ Modelos mostra TUDO que o gateway serve, não só o que já foi
    marcado no seletor. Um id cru ao lado de linhas com nome pareceria defeito de rotulagem,
    não escolha — então todo modelo recebe rótulo já na primeira exibição."""
    from mangaba.server.manager import SessionManager

    manager = SessionManager(data_dir=tmp_path / "data")
    manager.secrets.put("provider:mangaba", {})

    class FakeResp:
        status_code = 200

        def json(self):
            return {"data": [{"id": "mangaba-chat"}, {"id": "mangaba-vision"}]}

    monkeypatch.setattr("httpx.get", lambda url, timeout=None: FakeResp())
    monkeypatch.setattr(SessionManager, "_mangaba_alive", lambda self: True)

    labels = manager.get_settings()["model_labels"]
    assert labels["mangaba:mangaba-chat"] == "Mangaba Chat"
    assert labels["mangaba:mangaba-vision"] == "Mangaba Visão"


def test_get_settings_nao_sonda_o_gateway_a_cada_fetch(tmp_path, monkeypatch):
    """`get_settings` roda em TODO fetch da GUI. Sem cache, cada um viraria uma chamada de
    rede ao gateway — e, quando ele está fora do ar, o tempo de espera se repetiria em toda
    abertura de Configurações, deixando a interface com cara de travada."""
    from mangaba.server.manager import SessionManager

    manager = SessionManager(data_dir=tmp_path / "data")
    manager.secrets.put("provider:mangaba", {})
    chamadas = {"n": 0}

    class FakeResp:
        def json(self):
            return {"models": [{"name": "qwen3:4b"}]}

    def contar(url, timeout=None):
        chamadas["n"] += 1
        return FakeResp()

    monkeypatch.setattr("httpx.get", contar)
    monkeypatch.setattr(SessionManager, "_mangaba_alive", lambda self: True)

    for _ in range(5):
        manager.get_settings()
    assert chamadas["n"] == 1, "o resultado deve ficar em cache entre fetches"

    # Detectar/salvar invalida o cache: o modelo recém-baixado não pode demorar 30 s p/ aparecer
    manager.set_provider("mangaba", {})
    manager.get_settings()
    assert chamadas["n"] > 1
