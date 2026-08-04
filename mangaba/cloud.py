"""Mangaba Cloud client — residual helpers only.

The interactive "Mangaba Cloud" sign-in (Auth0 login) and the one-click
"managed connect" begin-flow were REMOVED from this fork: the broker
infrastructure (api.mangaba.ai / api.mangaba.app) does not exist here, so those
paths were dead ends. Every connector now connects by the MANUAL path — paste
the provider's own credential (bot_token, api_token, OAuth access token).

What remains here is the plumbing that other subsystems still call:

- Telemetry (Phase 5): `install_id`, `telemetry_enabled`, `set_telemetry_enabled`,
  `emit_session_created` — content-free, opt-out, no-op when signed out.
- Gallery: the persona-gallery read helpers.
- Managed-profile lifecycle for profiles that already exist locally:
  `managed_profile_from_callback` (parses a broker callback payload into a local
  profile — still exercised by connectors/setup.py and tests), plus the broker
  token refresh / disconnect helpers (`refresh_managed_token`,
  `ensure_fresh_connector_token`, `cloud_disconnect`, GitHub relay tokens). These
  are inert without a signed-in session (`fresh_access_token` returns None), and
  harmless.
"""

from __future__ import annotations

import base64
import hashlib
import secrets as _secrets
import time
from typing import Any, Optional

import httpx

from .config import Config
from .secrets import SecretStore

CLOUD_AUTH_PROFILE = "cloud:auth"

from . import __version__ as APP_VERSION  # noqa: E402

# connector id (canonical, = descriptor name) -> broker provider key
PROVIDER_FOR_CONNECTOR = {
    "gmail": "google",
    "google_calendar": "google",
    "google_drive": "google",
    "slack": "slack",
    "notion": "notion",
    "attio": "attio",
    "hubspot": "hubspot",
    "github": "github",
    "outlook": "microsoft",
}

def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _now() -> float:
    return time.time()


# --- cloud session token (residual: used only by managed-profile refresh) -----


def _store_cloud_tokens(secrets: SecretStore, token: dict) -> None:
    profile = secrets.get(CLOUD_AUTH_PROFILE) or {"type": "oauth", "enabled": True}
    profile["access_token"] = token.get("access_token", "")
    if token.get("refresh_token"):  # rotating refresh tokens: keep the newest
        profile["refresh_token"] = token["refresh_token"]
    profile["expires"] = _now() + int(token.get("expires_in") or 3600) - 60
    secrets.put(CLOUD_AUTH_PROFILE, profile)


def status(secrets: SecretStore) -> dict[str, Any]:
    profile = secrets.get(CLOUD_AUTH_PROFILE) or {}
    return {
        "signed_in": bool(profile.get("access_token")),
        "account": profile.get("account") or "",
        "user_id": profile.get("user_id") or "",
    }


def fresh_access_token(secrets: SecretStore, config: Config) -> Optional[str]:
    """Valid cloud session token, silently refreshed near expiry; None when
    signed out or the session can't be renewed (GUI shows "sign in again")."""
    profile = secrets.get(CLOUD_AUTH_PROFILE) or {}
    if not profile.get("access_token"):
        return None
    if float(profile.get("expires") or 0) > _now():
        return profile["access_token"]
    if not profile.get("refresh_token"):
        return None
    resp = httpx.post(
        f"https://{config.cloud_auth_domain}/oauth/token",
        data={
            "grant_type": "refresh_token",
            "client_id": config.cloud_client_id,
            "refresh_token": profile["refresh_token"],
        },
        timeout=15,
    )
    if resp.status_code != 200:
        return None
    _store_cloud_tokens(secrets, resp.json())
    return (secrets.get(CLOUD_AUTH_PROFILE) or {}).get("access_token")


# --- telemetry (Phase 5) ---------------------------------------------------------
# One sentence: which mangaba type was started and when — nothing else. Signed-in
# users only, default-on with an opt-out; signed out (or opted out) sends NOTHING.
# Never sent: titles, prompts, outputs, tool args, file paths, connector content.

TELEMETRY_PROFILE = "cloud:telemetry"


def install_id(secrets: SecretStore) -> str:
    """Stable random per-install id, minted on first use (spec Phase 5)."""
    profile = secrets.get(TELEMETRY_PROFILE) or {}
    if not profile.get("install_id"):
        profile["install_id"] = "ins_" + _secrets.token_hex(12)
        secrets.put(TELEMETRY_PROFILE, profile)
    return profile["install_id"]


def telemetry_enabled(secrets: SecretStore) -> bool:
    profile = secrets.get(TELEMETRY_PROFILE) or {}
    return bool(profile.get("enabled", True))  # default-on (only matters signed in)


def set_telemetry_enabled(secrets: SecretStore, enabled: bool) -> dict[str, Any]:
    profile = secrets.get(TELEMETRY_PROFILE) or {}
    profile["enabled"] = bool(enabled)
    secrets.put(TELEMETRY_PROFILE, profile)
    return {"ok": True, "telemetry_enabled": bool(enabled)}


def emit_session_created(
    secrets: SecretStore,
    config: Config,
    *,
    session_id: str,
    persona_id: str,
    persona_family: str,
    workspace_kind: str,
) -> bool:
    """Best-effort, content-free session event. Hard no-op unless signed in AND
    the toggle is on; failures are swallowed (telemetry must never break a session)."""
    import platform as _platform
    import sys

    if not telemetry_enabled(secrets):
        return False
    token = fresh_access_token(secrets, config)
    if not token:
        return False  # signed out: local-only users send nothing, by design
    body = {
        "event": "mangaba_session_created",
        "install_id": install_id(secrets),
        "app_version": APP_VERSION,
        "platform": {"darwin": "macos", "win32": "windows"}.get(
            sys.platform, _platform.system().lower() or "unknown"
        ),
        "session": {
            "session_id_hash": "sha256:"
            + hashlib.sha256(session_id.encode()).hexdigest(),
            "persona_id": persona_id,
            "persona_family": persona_family,
            "workspace_kind": workspace_kind,
        },
    }
    try:
        resp = httpx.post(
            config.cloud_base_url.rstrip("/") + "/v1/telemetry/events",
            json=body,
            headers={"Authorization": f"Bearer {token}"},
            timeout=10,
        )
        return resp.status_code == 200
    except httpx.HTTPError:
        return False


# --- managed connectors --------------------------------------------------------


def managed_profile_from_callback(form: dict[str, str]) -> dict[str, Any]:
    """Local connector profile from the broker's form-POST payload.

    Field-compatible with a manual paste (`access_token` etc.) so tools and
    gating treat both paths identically; the managed extras (refresh_token,
    connection_id) are what enable broker refresh and cloud disconnect.
    """
    profile = {
        "type": "oauth",
        "enabled": True,
        "managed": True,
        "access_token": form.get("access_token", ""),
        "refresh_token": form.get("refresh_token", ""),
        "scope": form.get("scope", ""),
        "connection_id": form.get("connection_id", ""),
        "provider": form.get("provider", ""),
        "account": form.get("account", ""),
    }
    if form.get("account_id"):
        # The stable id behind the display name (workspace/portal id) — what
        # the generic accounts layer keys multi-account profiles by.
        profile["account_id"] = form["account_id"]
    if form.get("expires_in"):  # absent ⇒ non-expiring token (e.g. Slack bot tokens)
        profile["expires"] = _now() + int(form["expires_in"]) - 60
    return profile


def refresh_managed_token(
    secrets: SecretStore,
    config: Config,
    connector: str,
    *,
    profile_key: Optional[str] = None,
) -> Optional[dict[str, Any]]:
    """Renew a managed connector token through the broker. Returns the updated
    profile, or None if this profile can't be (or doesn't need to be) renewed
    that way. Manual profiles are never touched. `profile_key` targets an
    account-keyed profile (`gmail:account:<email>`); default = `<name>:default`."""
    key = profile_key or f"{connector}:default"
    profile = secrets.get(key) or {}
    if not (profile.get("managed") and profile.get("refresh_token")):
        return None
    provider = profile.get("provider") or PROVIDER_FOR_CONNECTOR.get(connector)
    token = fresh_access_token(secrets, config)
    if not provider or not token:
        return None
    try:
        resp = httpx.post(
            config.cloud_base_url.rstrip("/") + f"/v1/oauth/{provider}/refresh",
            json={
                "refresh_token": profile["refresh_token"],
                "connection_id": profile.get("connection_id", ""),
                "connector": connector,
            },
            headers={"Authorization": f"Bearer {token}"},
            timeout=20,
        )
    except httpx.HTTPError:
        return None
    if resp.status_code != 200:
        return None
    fresh = resp.json()
    profile["access_token"] = fresh.get("access_token", "")
    if fresh.get("refresh_token"):
        profile["refresh_token"] = fresh["refresh_token"]
    profile["expires"] = _now() + int(fresh.get("expires_in") or 3600) - 60
    secrets.put(key, profile)
    return profile


def ensure_fresh_connector_token(
    secrets: SecretStore,
    config: Config,
    connector: str,
    *,
    profile_key: Optional[str] = None,
    leeway: int = 120,
) -> None:
    """Refresh-on-expiry hook for connector tools: if this is a managed profile
    about to expire, renew it in place. No-op for manual profiles."""
    key = profile_key or f"{connector}:default"
    profile = secrets.get(key) or {}
    if not profile.get("managed"):
        return
    expires = float(profile.get("expires") or 0)
    if expires and expires > _now() + leeway:
        return
    refresh_managed_token(secrets, config, connector, profile_key=profile_key)


def cloud_disconnect(
    secrets: SecretStore,
    config: Config,
    connector: str,
    *,
    profile_key: Optional[str] = None,
) -> None:
    """Best-effort: tell the cloud a managed connection is gone so its metadata
    flips to disconnected. Local deletion always proceeds regardless."""
    profile = secrets.get(profile_key or f"{connector}:default") or {}
    connection_id = profile.get("connection_id")
    if not (profile.get("managed") and connection_id):
        return
    token = fresh_access_token(secrets, config)
    if not token:
        return
    try:
        httpx.post(
            config.cloud_base_url.rstrip("/")
            + f"/v1/connections/{connection_id}/disconnect",
            headers={"Authorization": f"Bearer {token}"},
            timeout=10,
        )
    except httpx.HTTPError:
        pass


# installation_id -> (token, expires_epoch). MEMORY ONLY by design: GitHub
# installation tokens live ~1 h and are re-minted from the broker; they must
# never touch the secret store (github-relay-spec §4).
_GITHUB_TOKEN_CACHE: dict[str, tuple[str, float]] = {}
_GITHUB_TOKEN_LEEWAY = 600  # re-mint when < 10 min of life remains


def github_installation_token(
    secrets: SecretStore, config: Config, installation_id: str, *, force: bool = False
) -> str:
    """A live installation access token for GitHub API calls, minted via the
    authenticated broker route and cached in memory (~50 min). `force` skips
    the cache — the 401 retry path. Empty string when unavailable (signed
    out / revoked installation / cloud unreachable)."""
    installation_id = str(installation_id or "").strip()
    if not installation_id:
        return ""
    if not force:
        cached = _GITHUB_TOKEN_CACHE.get(installation_id)
        if cached and cached[1] > _now() + _GITHUB_TOKEN_LEEWAY:
            return cached[0]
    token = fresh_access_token(secrets, config)
    if not token:
        return ""
    try:
        resp = httpx.post(
            config.cloud_base_url.rstrip("/") + "/v1/github/token",
            json={"installation_id": installation_id},
            headers={"Authorization": f"Bearer {token}"},
            timeout=20,
        )
    except httpx.HTTPError:
        return ""
    if resp.status_code != 200:
        return ""
    body = resp.json()
    minted = body.get("token", "")
    # expires_at is ISO-8601 from GitHub; parse defensively, default 1 h.
    expires = _now() + 3600
    try:
        from datetime import datetime

        raw = str(body.get("expires_at", ""))
        if raw:
            expires = datetime.fromisoformat(raw.replace("Z", "+00:00")).timestamp()
    except ValueError:
        pass
    if minted:
        _GITHUB_TOKEN_CACHE[installation_id] = (minted, expires)
    return minted


def clear_github_token(installation_id: str) -> None:
    """Drop a cached installation token (disconnect / revocation)."""
    _GITHUB_TOKEN_CACHE.pop(str(installation_id or "").strip(), None)


def github_disconnect_installation(
    secrets: SecretStore, config: Config, installation_id: str
) -> None:
    """Best-effort: delete this user's relay routing rows for one installation
    so the cloud stops pushing its events. Local profile deletion always
    proceeds regardless (the row only routes)."""
    clear_github_token(installation_id)
    token = fresh_access_token(secrets, config)
    if not token:
        return
    try:
        httpx.post(
            config.cloud_base_url.rstrip("/") + "/v1/relay/github/disconnect",
            json={"installation_id": installation_id},
            headers={"Authorization": f"Bearer {token}"},
            timeout=10,
        )
    except httpx.HTTPError:
        pass


def slack_disconnect_workspace(
    secrets: SecretStore, config: Config, team_id: str
) -> None:
    """Best-effort: delete this user's relay routing row for one workspace so the
    cloud stops pushing its events. Local token deletion always proceeds regardless
    (the row only routes; without the desktop token nothing can be sent anyway)."""
    token = fresh_access_token(secrets, config)
    if not token:
        return
    try:
        httpx.post(
            config.cloud_base_url.rstrip("/") + "/v1/relay/slack/uninstall",
            json={"team_id": team_id},
            headers={"Authorization": f"Bearer {token}"},
            timeout=10,
        )
    except httpx.HTTPError:
        pass


# --- persona gallery -----------------------------------------------------------


def _gallery_get(secrets: SecretStore, config: Config, path: str) -> Optional[dict]:
    token = fresh_access_token(secrets, config)
    if not token:
        return None
    try:
        resp = httpx.get(
            config.cloud_base_url.rstrip("/") + path,
            headers={"Authorization": f"Bearer {token}"},
            timeout=15,
        )
    except httpx.HTTPError:
        return None
    return resp.json() if resp.status_code == 200 else None


def gallery_list(secrets: SecretStore, config: Config) -> Optional[dict]:
    """Curated persona cards visible to this user's tenant; None when signed
    out or the cloud is unreachable (gallery requires sign-in by design)."""
    return _gallery_get(secrets, config, "/v1/personas/gallery")


def gallery_manifest(secrets: SecretStore, config: Config, slug: str) -> Optional[dict]:
    return _gallery_get(secrets, config, f"/v1/personas/gallery/{slug}/manifest")


def gallery_install_event(secrets: SecretStore, config: Config, slug: str) -> None:
    """Best-effort product telemetry (slug/version only, no content)."""
    token = fresh_access_token(secrets, config)
    if not token:
        return
    try:
        httpx.post(
            config.cloud_base_url.rstrip("/")
            + f"/v1/personas/gallery/{slug}/install-events",
            json={"platform": __import__("sys").platform},
            headers={"Authorization": f"Bearer {token}"},
            timeout=10,
        )
    except httpx.HTTPError:
        pass


def gallery_detail(secrets: SecretStore, config: Config, slug: str) -> Optional[dict]:
    """Solo-page payload: the cloud card + publisher pitch, with capability
    facts derived LOCALLY from the manifest via the desktop's own strict
    parser — the pitch can never advertise what install-time consent wouldn't
    show, because both views come from the same parsed manifest."""
    card = _gallery_get(secrets, config, f"/v1/personas/gallery/{slug}")
    manifest = gallery_manifest(secrets, config, slug)
    if card is None or manifest is None:
        return None
    try:
        from .personas.loading import consent_summary
        from .personas.manifest import parse_manifest

        m = parse_manifest(manifest.get("manifest_markdown", ""), fallback_id=slug)
        capabilities = consent_summary(m)
        recommends = [
            {"kind": r.kind, "ref": r.ref, "reason": r.reason, "tier": r.tier}
            for r in m.recommends
        ]
    except Exception as exc:  # malformed manifest: surface, don't crash
        return {"ok": False, "error": f"manifest failed local validation: {exc}"}
    return {
        "ok": True,
        "card": card,
        "capabilities": capabilities,
        "recommends": recommends,
    }
