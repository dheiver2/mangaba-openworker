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


def test_ollama_models_gated_on_liveness(tmp_path, monkeypatch):
    """`ollama:*` entries show only while a local Ollama answers — keyless must not mean
    always-present (a stray ollama:<junk> pref would otherwise render forever)."""
    from mangaba.server.manager import SessionManager

    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("MANGABA_STATE_DIR", str(tmp_path / "state"))
    manager = SessionManager(data_dir=tmp_path / "data")
    manager.add_model("ollama:llama3.3")

    monkeypatch.setattr(SessionManager, "_ollama_alive", lambda self: False)
    assert "ollama:llama3.3" not in manager.get_settings()["models"]

    monkeypatch.setattr(SessionManager, "_ollama_alive", lambda self: True)
    assert "ollama:llama3.3" in manager.get_settings()["models"]


def test_ollama_saved_profile_with_no_custom_fields_still_lists_models(tmp_path, monkeypatch):
    """`{}` is a REAL saved profile (Detect on the default localhost URL — the common case),
    but is falsy in Python. `_ollama_models` used to treat `if not profile` as "never
    configured" and bail before the default URL ever applied, so a user who never typed a
    custom endpoint saw zero local models forever, even with Ollama running and reachable.
    Only an actual `None` (never saved at all) should mean "nothing to look up"."""
    from mangaba.server.manager import SessionManager

    manager = SessionManager(data_dir=tmp_path / "data")
    manager.secrets.put("provider:ollama", {})  # exactly what set_provider("ollama", {}) saves

    class FakeResp:
        def json(self):
            return {"models": [{"name": "qwen2.5:3b-instruct"}]}

    monkeypatch.setattr(
        "httpx.get", lambda url, timeout=None: FakeResp() if "/api/tags" in url else (_ for _ in ()).throw(AssertionError)
    )
    assert manager._ollama_models() == ["ollama:qwen2.5:3b-instruct"]


def test_ollama_detect_persists_profile_so_local_models_surface(tmp_path, monkeypatch):
    """Clicking Detect on a KEYLESS provider must persist a profile, or the live-model lookup
    (which reads that profile) always comes back empty and the composer never gets local
    models — Ollama can report `verify: ok` and `configured: true` forever without a single
    model ever reaching the picker. `configured` is always true for Ollama (usable out of
    the box), so the frontend's old `!info?.configured` save-gate never fired for it; this
    checks the SERVER side of the fix, that persisting on every successful set_provider call
    (regardless of "configured") makes the models actually show up afterwards."""
    from mangaba.server.manager import SessionManager

    manager = SessionManager(data_dir=tmp_path / "data")
    assert manager.secrets.get("provider:ollama") is None  # nothing saved yet

    class FakeResp:
        def json(self):
            return {"models": [{"name": "qwen2.5:3b-instruct"}, {"name": "gemma4:e4b"}]}

    monkeypatch.setattr("httpx.get", lambda url, timeout=None: FakeResp())

    res = manager.set_provider("ollama", {})
    assert res["ok"] is True
    assert manager.secrets.get("provider:ollama") is not None  # now persisted

    # The exact recommended_model (qwen3-coder:30b) almost never matches what a real user has
    # pulled — falling back to whatever IS installed beats leaving the composer empty.
    assert "ollama:qwen2.5:3b-instruct" in manager.get_settings()["models"]


def test_settings_labels_ollama_models_even_before_theyre_curated(tmp_path, monkeypatch):
    """The Settings ▸ Modelos checklist shows every model Ollama reports, not just the ones
    already ticked into the composer picker — an unbranded raw tag sitting next to branded
    rows (because only `selectable`/curated ids got a label) would look like a labeling bug,
    not a deliberate choice. Every model Ollama reports should be labeled up front."""
    from mangaba.server.manager import SessionManager

    manager = SessionManager(data_dir=tmp_path / "data")
    manager.secrets.put("provider:ollama", {})

    class FakeResp:
        def json(self):
            return {"models": [{"name": "qwen2.5:3b-instruct"}, {"name": "mangaba-gemma4:latest"}]}

    monkeypatch.setattr("httpx.get", lambda url, timeout=None: FakeResp())
    monkeypatch.setattr(SessionManager, "_ollama_alive", lambda self: True)

    labels = manager.get_settings()["model_labels"]
    assert labels["ollama:qwen2.5:3b-instruct"] == "Qwen 2.5 3B Instruct · Mangaba Local"
    assert labels["ollama:mangaba-gemma4:latest"] == "Mangaba Gemma 4"
