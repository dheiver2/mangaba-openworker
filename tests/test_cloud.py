"""Mangaba Cloud integration: sign-in, managed connect callback, refresh.

Everything is offline: Auth0 and the cloud broker are stubbed at the httpx
boundary. The invariants under test are the product promises — manual paste
works signed out, managed profiles are field-compatible with manual ones, and
manual profiles are never touched by cloud refresh.
"""

from __future__ import annotations

import time

import pytest

from mangaba import cloud
from mangaba.config import Config
from mangaba.connectors.setup import (
    connect_connector,
    connector_list,
    managed_connect_connector,
)
from mangaba.secrets import SecretStore


@pytest.fixture
def secrets(tmp_path, monkeypatch):
    monkeypatch.setenv("MANGABA_STATE_DIR", str(tmp_path / "state"))
    return SecretStore(path=tmp_path / "state" / "secrets.json")


@pytest.fixture
def config():
    return Config(
        cloud_base_url="https://cloud.test",
        cloud_auth_domain="tenant.auth0.test",
        cloud_client_id="client123",
        port=8765,
    )


class FakeResponse:
    def __init__(self, status_code=200, body=None):
        self.status_code = status_code
        self._body = body or {}

    def json(self):
        return self._body


# --- session status --------------------------------------------------------------
# The interactive Mangaba Cloud sign-in (begin_login/complete_login/logout) and the
# managed one-click begin-flow + broker callbacks were removed from this fork — the
# broker infrastructure doesn't exist, so those were dead ends. status() survives to
# back the telemetry route; with no way to sign in it is always signed-out.


def test_status_is_signed_out_without_a_session(secrets):
    assert cloud.status(secrets) == {"signed_in": False, "account": "", "user_id": ""}


# --- managed profile lifecycle (still used by connectors + broker refresh) --------


def test_every_managed_connector_has_a_provider_mapping():
    """A managed=True descriptor without a PROVIDER_FOR_CONNECTOR entry ships a
    dead one-click button ("X has no managed OAuth path") — outlook did exactly
    that. Wire the map in the same change that flips a connector to managed."""
    from mangaba.connectors.descriptors import DESCRIPTORS

    managed = {d.name for d in DESCRIPTORS if d.managed}
    unmapped = managed - set(cloud.PROVIDER_FOR_CONNECTOR)
    assert (
        not unmapped
    ), f"managed connectors missing an OAuth provider: {sorted(unmapped)}"


def test_managed_profile_is_field_compatible_with_manual(secrets):
    form = {
        "provider": "google",
        "connector": "gmail",
        "connection_id": "conn_1",
        "access_token": "ya29.x",
        "refresh_token": "1//r",
        "expires_in": "3599",
        "scope": "gmail.readonly",
        "account": "a@b.c",
    }
    result = managed_connect_connector(
        secrets, "gmail", cloud.managed_profile_from_callback(form)
    )
    assert result["ok"] and result["account"] == "a@b.c"

    listed = {c["name"]: c for c in connector_list(secrets)}
    gmail = listed["gmail"]
    assert gmail["connected"] and gmail["managed"] and gmail["managed_profile"]
    # Multi-account era: listing migrates the tokens into the account profile.
    profile = secrets.get("gmail:account:a@b.c")
    assert profile["access_token"] == "ya29.x"  # same key manual paste writes
    assert profile["connection_id"] == "conn_1"
    assert gmail["accounts"][0]["email"] == "a@b.c" and gmail["accounts"][0]["default"]


def test_managed_connect_rejected_for_unmanaged_connector(secrets):
    # telegram is manual-only (github gained a managed path with the App relay)
    result = managed_connect_connector(secrets, "telegram", {"access_token": "x"})
    assert not result["ok"]


def test_manual_paste_still_works_and_is_not_managed(secrets):
    result = connect_connector(
        secrets, "gmail", {"access_token": "manual-token"}, validate=False
    )
    assert result["ok"]
    listed = {c["name"]: c for c in connector_list(secrets)}
    assert listed["gmail"]["connected"]
    assert not listed["gmail"]["managed_profile"]  # manual profile, managed capable
    assert listed["gmail"]["managed"]


# --- refresh ---------------------------------------------------------------------


def _signed_in(secrets):
    secrets.put(
        cloud.CLOUD_AUTH_PROFILE,
        {"access_token": "cloud-at", "expires": time.time() + 3600},
    )


def test_refresh_updates_expiring_managed_profile(secrets, config, monkeypatch):
    _signed_in(secrets)
    secrets.put(
        "gmail:default",
        {
            "type": "oauth",
            "managed": True,
            "provider": "google",
            "access_token": "old",
            "refresh_token": "1//r",
            "connection_id": "conn_1",
            "expires": time.time() - 10,
        },
    )

    def fake_post(url, **kwargs):
        assert url == "https://cloud.test/v1/oauth/google/refresh"
        assert kwargs["json"]["connection_id"] == "conn_1"
        return FakeResponse(200, {"access_token": "new", "expires_in": 3600})

    monkeypatch.setattr(cloud.httpx, "post", fake_post)
    cloud.ensure_fresh_connector_token(secrets, config, "gmail")
    assert secrets.get("gmail:default")["access_token"] == "new"


def test_refresh_never_touches_manual_profiles(secrets, config, monkeypatch):
    _signed_in(secrets)
    secrets.put("gmail:default", {"type": "oauth", "access_token": "manual"})

    def boom(url, **kwargs):  # any network call would be a bug
        raise AssertionError("manual profiles must not trigger cloud refresh")

    monkeypatch.setattr(cloud.httpx, "post", boom)
    cloud.ensure_fresh_connector_token(secrets, config, "gmail")
    assert secrets.get("gmail:default")["access_token"] == "manual"


def test_fresh_profile_not_refreshed(secrets, config, monkeypatch):
    _signed_in(secrets)
    secrets.put(
        "gmail:default",
        {
            "managed": True,
            "provider": "google",
            "access_token": "current",
            "refresh_token": "1//r",
            "expires": time.time() + 3600,
        },
    )
    monkeypatch.setattr(
        cloud.httpx, "post", lambda *a, **k: (_ for _ in ()).throw(AssertionError())
    )
    cloud.ensure_fresh_connector_token(secrets, config, "gmail")
    assert secrets.get("gmail:default")["access_token"] == "current"


# --- telemetry (Phase 5) ------------------------------------------------------


def test_install_id_stable_across_calls(secrets):
    first = cloud.install_id(secrets)
    assert first.startswith("ins_")
    assert cloud.install_id(secrets) == first


def test_emit_sends_nothing_signed_out(secrets, config, monkeypatch):
    def boom(*a, **k):  # any network call would violate the local-only promise
        raise AssertionError("signed-out users must send no telemetry")

    monkeypatch.setattr(cloud.httpx, "post", boom)
    assert (
        cloud.emit_session_created(
            secrets,
            config,
            session_id="s1",
            persona_id="sales",
            persona_family="knowledge",
            workspace_kind="deliverable",
        )
        is False
    )


def test_emit_sends_nothing_when_opted_out(secrets, config, monkeypatch):
    _signed_in(secrets)
    cloud.set_telemetry_enabled(secrets, False)
    monkeypatch.setattr(
        cloud.httpx, "post", lambda *a, **k: (_ for _ in ()).throw(AssertionError())
    )
    assert not cloud.emit_session_created(
        secrets,
        config,
        session_id="s1",
        persona_id="sales",
        persona_family="knowledge",
        workspace_kind="deliverable",
    )


def test_emit_is_content_free_and_hashes_session_id(secrets, config, monkeypatch):
    _signed_in(secrets)
    sent = {}

    def fake_post(url, **kwargs):
        sent["url"] = url
        sent["body"] = kwargs["json"]
        return FakeResponse(200, {"ok": True})

    monkeypatch.setattr(cloud.httpx, "post", fake_post)
    ok = cloud.emit_session_created(
        secrets,
        config,
        session_id="sess-secret-id",
        persona_id="sales",
        persona_family="knowledge",
        workspace_kind="deliverable",
    )
    assert ok
    assert sent["url"] == "https://cloud.test/v1/telemetry/events"
    body = sent["body"]
    assert body["event"] == "mangaba_session_created"
    assert body["install_id"].startswith("ins_")
    assert "sess-secret-id" not in str(body)  # raw id never leaves the device
    assert body["session"]["session_id_hash"].startswith("sha256:")
    assert set(body["session"]) == {
        "session_id_hash",
        "persona_id",
        "persona_family",
        "workspace_kind",
    }


# --- gallery solo page ------------------------------------------------------


def test_gallery_detail_derives_capabilities_locally(secrets, config, monkeypatch):
    manifest_md = """---
id: sales
name: Sales Mangaba
tools: [files, search, todo]
messaging: true
connectors: true
default_permission_mode: interactive
recommends:
  - connector: hubspot
    reason: read deals
    tier: core
---
You are the Sales Mangaba."""

    def fake_get(s, c, path):
        if path.endswith("/manifest"):
            return {
                "slug": "sales",
                "manifest_markdown": manifest_md,
                "manifest_hash": "",
            }
        return {
            "slug": "sales",
            "name": "Sales Mangaba",
            "pitch_markdown": "**pitch**",
        }

    monkeypatch.setattr(cloud, "_gallery_get", fake_get)
    out = cloud.gallery_detail(secrets, config, "sales")
    assert out["ok"]
    assert out["card"]["pitch_markdown"] == "**pitch**"
    caps = out["capabilities"]
    assert caps["tools"] == ["files", "search", "todo"]
    assert caps["messaging"] is True
    assert out["recommends"] == [
        {"kind": "connector", "ref": "hubspot", "reason": "read deals", "tier": "core"}
    ]


def test_gallery_detail_rejects_malformed_manifest(secrets, config, monkeypatch):
    def fake_get(s, c, path):
        if path.endswith("/manifest"):
            return {"slug": "bad", "manifest_markdown": "no frontmatter here"}
        return {"slug": "bad"}

    monkeypatch.setattr(cloud, "_gallery_get", fake_get)
    out = cloud.gallery_detail(secrets, config, "bad")
    assert not out["ok"]
    assert "validation" in out["error"]
