"""Sidecar loopback routes that survive the Mangaba Cloud removal: /v1/cloud/status
(local, always signed-out), /v1/cloud/telemetry, the gallery read endpoints, and
signed-out connector disconnect. The interactive sign-in (/auth/callback), the
one-click connect-managed route, and the broker /oauth/callback were removed with
the managed OAuth flow — the broker infrastructure doesn't exist in this fork."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from mangaba.server import SessionManager, create_app


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("MANGABA_STATE_DIR", str(tmp_path / "state"))
    manager = SessionManager(workspace=tmp_path)
    app = create_app(manager)
    with TestClient(app) as c:
        c.manager = manager
        yield c


def test_cloud_status_signed_out(client):
    body = client.get("/v1/cloud/status").json()
    assert body == {
        "signed_in": False,
        "account": "",
        "user_id": "",
        "telemetry_enabled": True,  # local default; nothing is sent while signed out
    }


def test_removed_cloud_routes_are_gone(client):
    """The managed one-click + interactive sign-in surface was removed: these routes
    no longer exist (the manual credential-paste path replaces them)."""
    assert client.post("/v1/connectors/notion/connect-managed").status_code == 404
    assert client.post("/oauth/callback", data={"app_state": "s"}).status_code == 404
    assert (
        client.get("/auth/callback", params={"code": "c", "state": "x"}).status_code
        == 404
    )
    assert client.post("/v1/cloud/login").status_code == 404
    assert client.post("/v1/cloud/logout").status_code == 404


def test_disconnect_works_signed_out(client):
    # manual profile, no cloud session: disconnect must not require the cloud
    client.manager.secrets.put("gmail:default", {"type": "oauth", "access_token": "t"})
    body = client.post("/v1/connectors/gmail/disconnect").json()
    assert body["ok"]
    assert client.manager.secrets.get("gmail:default") is None


SALES_MANIFEST = """---
id: sales
name: Sales Mangaba
icon: chart
tagline: t
family: knowledge
workspace: deliverable
tools: [files, search, todo]
description: d
---
You are the Sales Mangaba."""


def _stub_gallery(monkeypatch, markdown=SALES_MANIFEST, *, hash_ok=True):
    import hashlib

    from mangaba import cloud

    digest = "sha256:" + hashlib.sha256(markdown.encode()).hexdigest()
    manifest = {
        "slug": "sales",
        "version": 1,
        "manifest_markdown": markdown,
        "manifest_hash": digest if hash_ok else "sha256:tampered",
    }
    events = []
    monkeypatch.setattr(cloud, "gallery_manifest", lambda s, c, slug: manifest)
    monkeypatch.setattr(
        cloud, "gallery_install_event", lambda s, c, slug: events.append(slug)
    )
    return events


def test_gallery_install_runs_consent_flow(client, monkeypatch):
    events = _stub_gallery(monkeypatch)
    body = client.post("/v1/personas/install", json={"gallery_slug": "sales"}).json()
    assert body["ok"], body
    assert body["consent"][0]["id"] == "sales"
    installed = {p["id"]: p for p in body["personas"]}
    # lands disabled + unsurfaced pending explicit user approval (trust model)
    assert installed["sales"]["enabled"] is False
    assert events == ["sales"]  # install event fired


def test_gallery_install_rejects_hash_mismatch(client, monkeypatch):
    _stub_gallery(monkeypatch, hash_ok=False)
    body = client.post("/v1/personas/install", json={"gallery_slug": "sales"}).json()
    assert not body["ok"]
    assert "hash" in body["error"]


def test_gallery_install_requires_sign_in(client, monkeypatch):
    from mangaba import cloud

    monkeypatch.setattr(cloud, "gallery_manifest", lambda s, c, slug: None)
    body = client.post("/v1/personas/install", json={"gallery_slug": "sales"}).json()
    assert not body["ok"]
    assert "login" in body["error"]


def test_cloud_gallery_endpoint_signed_out(client):
    body = client.get("/v1/cloud/gallery").json()
    assert not body["ok"]
    assert body["personas"] == []


def test_delete_persona_after_gallery_install(client, monkeypatch):
    _stub_gallery(monkeypatch)
    assert client.post("/v1/personas/install", json={"gallery_slug": "sales"}).json()[
        "ok"
    ]
    body = client.delete("/v1/personas/sales").json()
    assert body["ok"]
    assert "sales" not in {p["id"] for p in body["personas"]}


def test_cloud_status_carries_telemetry_pref_and_toggle_flips_it(client):
    assert client.get("/v1/cloud/status").json()["telemetry_enabled"] is True
    body = client.post("/v1/cloud/telemetry", json={"enabled": False}).json()
    assert body["ok"] and body["telemetry_enabled"] is False
    assert client.get("/v1/cloud/status").json()["telemetry_enabled"] is False


def test_delete_persona_refuses_builtin_and_unknown(client):
    body = client.delete("/v1/personas/cowork").json()
    assert not body["ok"] and "built-in" in body["error"]
    body = client.delete("/v1/personas/ghost").json()
    assert not body["ok"] and "unknown" in body["error"]
