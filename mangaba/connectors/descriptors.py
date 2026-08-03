"""Connector descriptors — data that drives the guided setup wizard.

Adding a connector is (mostly) data, not UI code: a descriptor declares its auth method,
the fields the user pastes, step-by-step instructions, and a `validate` that confirms the
token by a real API call (and returns the bot identity to show back). Designed so a managed
one-click OAuth (`auth="oauth"`) can slot in later for the cloud product without changing the
data model — only the connect action differs.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Optional


@dataclass
class Field:
    key: str
    label: str
    secret: bool = False
    required: bool = True
    help: str = ""
    placeholder: str = ""

    def to_dict(self) -> dict:
        return {
            "key": self.key,
            "label": self.label,
            "secret": self.secret,
            "required": self.required,
            "help": self.help,
            "placeholder": self.placeholder,
        }


@dataclass
class ValidationResult:
    ok: bool
    identity: Optional[str] = (
        None  # e.g. "@mybot" — shown back to the user, never a secret
    )
    error: Optional[str] = None


@dataclass
class ConnectorDescriptor:
    name: str
    title: str
    icon: str
    blurb: str
    auth: str  # "bot_token" | "socket_app" | "oauth" | "token" | "api_token" | "none"
    two_way: bool
    fields: list[Field]
    instructions: list[str]
    available: bool = True  # False → shown as "soon"
    # Chat-platform capability, narrower than two_way: sessions can SUBSCRIBE to this
    # connector's channels (Sources ▸ Channels, listening-sessions block). GitHub is
    # two_way via the relay (inbound mentions) but has no channel semantics.
    channels: bool = False
    validate: Optional[Callable[[dict], ValidationResult]] = None
    # Registry metadata (UI-Refresh §1): the connector's brand color (hex; fallback gray) and a
    # stable logo id (e.g. "slack") the frontend maps to a bundled SVG. Empty logo → UI fallback.
    brand_color: str = "#6b7280"
    logo: str = ""
    # Extra search terms for the catalog typeahead — capability words the title
    # doesn't carry (e.g. "calendar" must surface Outlook, not just Google Calendar).
    aliases: tuple = ()
    # Vendor-hosted MCP server URL → this connector is MCP-BACKED: one-click connect
    # runs the local MCP OAuth flow (DCR, tokens on this computer — no broker), and the
    # tool surface is the PINNED subset in tool_defs (names `mcp__<name>__<tool>`),
    # never the vendor's full catalog (drift can only shrink capability, not grow it).
    # A connector may carry BOTH mcp_url and manual fields (jira): the profile's
    # mode decides which tool set is live.
    mcp_url: str = ""
    # Experimental connectors are hidden unless the user enables them in settings, require an
    # explicit risk acknowledgment to connect, and ship in a separate package
    # (connectors/experimental/) that release builds exclude entirely.
    experimental: bool = False
    risk_notice: str = ""
    # One-click managed OAuth via Mangaba Cloud (requires cloud sign-in).
    # Manual token paste ALWAYS remains available — signed out or in — managed
    # is an extra path, never a replacement (local-only open-source flow is
    # sacred).
    managed: bool = False
    # One-click temporarily unavailable (e.g. Google pending CASA verification):
    # the GUI shows a disabled button with a "Coming soon" badge, the server
    # refuses begin_managed_connect, and the manual path is unaffected.
    managed_paused: bool = False
    # Multi-account (accounts.py generic layer): the creds field that names an
    # account (e.g. "project_id"), or "@identity" = the validator's identity
    # string. Non-empty → profiles live at `<name>:account:<id>` and the
    # `:default` profile is pointer-only. Empty → single-profile connector.
    account_field: str = ""


# -- validators (sync httpx, one-shot) -----------------------------------------
def _validate_telegram(creds: dict) -> ValidationResult:
    import httpx

    token = creds.get("bot_token", "")
    try:
        data = httpx.get(
            f"https://api.telegram.org/bot{token}/getMe", timeout=15
        ).json()
    except Exception as exc:
        return ValidationResult(False, error=str(exc))
    if data.get("ok"):
        return ValidationResult(
            True, identity="@" + str(data["result"].get("username", "bot"))
        )
    return ValidationResult(False, error=data.get("description") or "invalid bot token")


def _validate_email(creds: dict) -> ValidationResult:
    from .email_tools import validate_email_account

    ok, identity, error = validate_email_account(creds)
    return ValidationResult(ok, identity=identity or None, error=error or None)


def _validate_slack(creds: dict) -> ValidationResult:
    import httpx

    token = creds.get("bot_token", "")
    try:
        data = httpx.post(
            "https://slack.com/api/auth.test",
            headers={"Authorization": f"Bearer {token}"},
            timeout=15,
        ).json()
    except Exception as exc:
        return ValidationResult(False, error=str(exc))
    if data.get("ok"):
        return ValidationResult(
            True, identity=f"{data.get('team', '?')} / {data.get('user', 'bot')}"
        )
    return ValidationResult(False, error=data.get("error") or "invalid bot token")


def _validate_whoami(
    method: str,
    url: str,
    *,
    headers: dict,
    identity: Callable[[dict], str],
    json: Optional[dict] = None,
) -> ValidationResult:
    """Shared one-shot whoami check: 2xx + extractable identity, else a failure."""
    import httpx

    try:
        resp = httpx.request(method, url, headers=headers, json=json, timeout=15)
        data = resp.json()
    except Exception as exc:
        return ValidationResult(False, error=str(exc))
    if resp.status_code >= 400:
        detail = (
            (data.get("message") or data.get("error") or data.get("error_summary"))
            if isinstance(data, dict)
            else None
        )
        return ValidationResult(False, error=str(detail or f"HTTP {resp.status_code}"))
    try:
        return ValidationResult(True, identity=str(identity(data)))
    except Exception:
        return ValidationResult(False, error="unexpected response from API")


def _validate_notion(creds: dict) -> ValidationResult:
    return _validate_whoami(
        "GET",
        "https://api.notion.com/v1/users/me",
        headers={
            "Authorization": f"Bearer {creds.get('access_token', '')}",
            "Notion-Version": "2022-06-28",
        },
        identity=lambda d: (d.get("bot") or {}).get("workspace_name") or d["name"],
    )


def _validate_attio(creds: dict) -> ValidationResult:
    return _validate_whoami(
        "GET",
        "https://api.attio.com/v2/self",
        headers={"Authorization": f"Bearer {creds.get('access_token', '')}"},
        identity=lambda d: d.get("workspace_name") or d["workspace_id"],
    )


def _validate_posthog(creds: dict) -> ValidationResult:
    base = str(creds.get("base_url") or "https://us.posthog.com").rstrip("/")
    return _validate_whoami(
        "GET",
        f"{base}/api/users/@me/",
        headers={"Authorization": f"Bearer {creds.get('api_key', '')}"},
        identity=lambda d: d["email"],
    )


def _validate_mixpanel(creds: dict) -> ValidationResult:
    import base64 as _b64

    pair = f"{creds.get('username', '')}:{creds.get('secret', '')}"
    return _validate_whoami(
        "GET",
        "https://mixpanel.com/api/app/me",
        headers={"Authorization": "Basic " + _b64.b64encode(pair.encode()).decode()},
        identity=lambda d, u=creds.get("username", ""): u,
    )


def _validate_amplitude(creds: dict) -> ValidationResult:
    import base64 as _b64

    pair = f"{creds.get('api_key', '')}:{creds.get('secret_key', '')}"
    return _validate_whoami(
        "GET",
        "https://amplitude.com/api/2/annotations",
        headers={"Authorization": "Basic " + _b64.b64encode(pair.encode()).decode()},
        # No user identity on this API — name the account by the key's tail so
        # two projects stay tellable-apart in the accounts list.
        identity=lambda d, k=str(creds.get("api_key", "")): f"key …{k[-6:]}",
    )


def _validate_apollo(creds: dict) -> ValidationResult:
    return _validate_whoami(
        "GET",
        "https://api.apollo.io/api/v1/auth/health",
        headers={"X-Api-Key": creds.get("api_key", "")},
        identity=lambda d: str(creds.get("label") or "").strip() or "default",
    )


def _validate_hunter(creds: dict) -> ValidationResult:
    return _validate_whoami(
        "GET",
        f"https://api.hunter.io/v2/account?api_key={creds.get('api_key', '')}",
        headers={},
        identity=lambda d: d["data"]["email"],
    )


def _validate_linear(creds: dict) -> ValidationResult:
    return _validate_whoami(
        "POST",
        "https://api.linear.app/graphql",
        headers={
            "Authorization": creds.get("api_key", ""),
            "Content-Type": "application/json",
        },
        json={"query": "{ viewer { name } }"},
        identity=lambda d: d["data"]["viewer"]["name"],
    )


def _validate_gitlab(creds: dict) -> ValidationResult:
    base = str(creds.get("base_url") or "https://gitlab.com").rstrip("/")
    return _validate_whoami(
        "GET",
        f"{base}/api/v4/user",
        headers={"PRIVATE-TOKEN": creds.get("token", "")},
        identity=lambda d: "@" + d["username"],
    )


def _validate_discord(creds: dict) -> ValidationResult:
    return _validate_whoami(
        "GET",
        "https://discord.com/api/v10/users/@me",
        headers={"Authorization": f"Bot {creds.get('bot_token', '')}"},
        identity=lambda d: d["username"],
    )


def _validate_asana(creds: dict) -> ValidationResult:
    return _validate_whoami(
        "GET",
        "https://app.asana.com/api/1.0/users/me",
        headers={"Authorization": f"Bearer {creds.get('token', '')}"},
        identity=lambda d: d["data"]["name"],
    )


def _validate_hubspot(creds: dict) -> ValidationResult:
    return _validate_whoami(
        "GET",
        "https://api.hubapi.com/account-info/v3/details",
        headers={"Authorization": f"Bearer {creds.get('token', '')}"},
        identity=lambda d: f"portal {d['portalId']}",
    )


def _validate_dropbox(creds: dict) -> ValidationResult:
    return _validate_whoami(
        "POST",
        "https://api.dropboxapi.com/2/users/get_current_account",
        headers={"Authorization": f"Bearer {creds.get('access_token', '')}"},
        identity=lambda d: d["email"],
    )


def _quickbooks_host(creds: dict) -> str:
    env = str(creds.get("environment", "")).lower()
    return (
        "sandbox-quickbooks.api.intuit.com"
        if env.startswith("sand")
        else "quickbooks.api.intuit.com"
    )


def _validate_quickbooks(creds: dict) -> ValidationResult:
    realm = creds.get("realm_id", "")
    return _validate_whoami(
        "GET",
        f"https://{_quickbooks_host(creds)}/v3/company/{realm}/companyinfo/{realm}",
        headers={
            "Authorization": f"Bearer {creds.get('access_token', '')}",
            "Accept": "application/json",
        },
        identity=lambda d: d["CompanyInfo"]["CompanyName"],
    )


def _validate_box(creds: dict) -> ValidationResult:
    return _validate_whoami(
        "GET",
        "https://api.box.com/2.0/users/me",
        headers={"Authorization": f"Bearer {creds.get('access_token', '')}"},
        identity=lambda d: d["login"],
    )


def _validate_whatsapp(creds: dict) -> ValidationResult:
    return _validate_whoami(
        "GET",
        f"https://graph.facebook.com/v21.0/{creds.get('phone_number_id', '')}",
        headers={"Authorization": f"Bearer {creds.get('access_token', '')}"},
        identity=lambda d: d["display_phone_number"],
    )


def _validate_clickup(creds: dict) -> ValidationResult:
    return _validate_whoami(
        "GET",
        "https://api.clickup.com/api/v2/user",
        headers={"Authorization": creds.get("api_token", "")},
        identity=lambda d: d["user"]["username"],
    )


def _validate_close(creds: dict) -> ValidationResult:
    import base64 as _b64

    # Close authenticates with HTTP basic auth: the API key is the username, blank password.
    pair = f"{creds.get('api_key', '')}:"
    return _validate_whoami(
        "GET",
        "https://api.close.com/api/v1/me/",
        headers={"Authorization": "Basic " + _b64.b64encode(pair.encode()).decode()},
        identity=lambda d: d["email"],
    )


def _validate_figma(creds: dict) -> ValidationResult:
    return _validate_whoami(
        "GET",
        "https://api.figma.com/v1/me",
        headers={"X-Figma-Token": creds.get("access_token", "")},
        identity=lambda d: d["email"],
    )


def _validate_google_drive(creds: dict) -> ValidationResult:
    return _validate_whoami(
        "GET",
        "https://www.googleapis.com/drive/v3/about?fields=user",
        headers={"Authorization": f"Bearer {creds.get('access_token', '')}"},
        identity=lambda d: d["user"]["emailAddress"],
    )


def _validate_docusign(creds: dict) -> ValidationResult:
    # userinfo also carries accounts[] (account_id + base_uri); the tool layer
    # re-fetches and caches those on first use, so validation only needs identity.
    return _validate_whoami(
        "GET",
        "https://account.docusign.com/oauth/userinfo",
        headers={"Authorization": f"Bearer {creds.get('access_token', '')}"},
        identity=lambda d: d["email"],
    )


def _validate_canva(creds: dict) -> ValidationResult:
    return _validate_whoami(
        "GET",
        "https://api.canva.com/rest/v1/users/me/profile",
        headers={"Authorization": f"Bearer {creds.get('access_token', '')}"},
        identity=lambda d: d["profile"]["display_name"],
    )


def _validate_outlook(creds: dict) -> ValidationResult:
    return _validate_whoami(
        "GET",
        "https://graph.microsoft.com/v1.0/me",
        headers={"Authorization": f"Bearer {creds.get('access_token', '')}"},
        identity=lambda d: d.get("mail") or d["userPrincipalName"],
    )


_ALLOWED_FIELD = Field(
    key="allowed_users",
    label="Allowed user IDs",
    required=False,
    help="Comma-separated IDs allowed to message the bot. Leave empty, then DM the bot and use Capture.",
    placeholder="123456789",
)

DESCRIPTORS: list[ConnectorDescriptor] = [
    ConnectorDescriptor(
        name="telegram",
        title="Telegram",
        icon="✈",
        blurb="Mensagens nos dois sentidos com um bot do Telegram.",
        auth="bot_token",
        two_way=True,
        channels=True,
        brand_color="#229ed9",
        logo="telegram",
        fields=[
            Field(
                "bot_token",
                "Bot token",
                secret=True,
                help="From @BotFather.",
                placeholder="123456:ABC-DEF…",
            ),
            _ALLOWED_FIELD,
        ],
        instructions=[
            "Abra o Telegram e mande mensagem para o @BotFather.",
            "Envie /newbot e escolha um nome e um usuário.",
            "Copie o token da HTTP API que ele fornecer e cole abaixo.",
            "Depois de conectar, mande uma DM ao seu novo bot e use o Capturar para pegar seu ID de usuário.",
        ],
        validate=_validate_telegram,
    ),
    ConnectorDescriptor(
        name="slack",
        title="Slack",
        icon="💬",
        blurb="Mensagens nos dois sentidos — com um clique via Mangaba Cloud ou com um app do Slack manual (Socket Mode).",
        auth="socket_app",
        two_way=True,
        channels=True,
        brand_color="#611f69",
        logo="slack",
        # One-click managed OAuth (the cloud relay): signed in, the GUI shows
        # "Connect Slack with one click" (no tokens). The manual Socket-Mode
        # fields below stay as the always-available fallback (slack → slack in
        # PROVIDER_FOR_CONNECTOR drives the broker start).
        managed=True,
        fields=[
            Field(
                "bot_token",
                "Bot token",
                secret=True,
                help="Bot User OAuth Token.",
                placeholder="xoxb-…",
            ),
            Field(
                "app_token",
                "App token",
                secret=True,
                help="App-level token for Socket Mode.",
                placeholder="xapp-…",
            ),
            _ALLOWED_FIELD,
        ],
        instructions=[
            "Acesse api.slack.com/apps → Create New App (from scratch).",
            "Settings → Socket Mode: ative e gere um token de nível de app (xapp-) com connections:write.",
            "Features → Interactivity & Shortcuts: ative a Interactivity (não é preciso Request URL no Socket Mode) — necessário para os botões Aprovar/Negar.",
            "OAuth & Permissions: adicione os escopos de bot chat:write, files:write, app_mentions:read, im:history, channels:history, groups:history, users:read, channels:read, groups:read (files:write permite ao agente enviar arquivos; os três últimos resolvem os nomes de remetentes e canais).",
            "Instale no workspace e copie o Bot User OAuth Token (xoxb-).",
            "Cole os dois tokens abaixo e clique em Conectar; depois convide o bot para um canal ou mande uma DM.",
        ],
        validate=_validate_slack,
    ),
    ConnectorDescriptor(
        name="email",
        title="E-mail (IMAP)",
        icon="✉",
        blurb="Ler, buscar e enviar e-mails de qualquer conta IMAP — Gmail, iCloud, Fastmail ou personalizada.",
        auth="app_password",
        two_way=False,
        logo="email",
        fields=[
            Field("address", "Email address", placeholder="you@gmail.com"),
            Field(
                "app_password",
                "App password",
                secret=True,
                help="Gmail/iCloud: generate an app password (requires 2-step verification). Not your account password.",
            ),
            Field(
                "display_name",
                "Display name",
                required=False,
                help="Shown as the From name on sent mail.",
            ),
            Field(
                "imap_host",
                "IMAP host (advanced)",
                required=False,
                help="Only needed for providers we don't auto-detect.",
                placeholder="imap.example.com",
            ),
            Field(
                "imap_port", "IMAP port (advanced)", required=False, placeholder="993"
            ),
            Field(
                "smtp_host",
                "SMTP host (advanced)",
                required=False,
                placeholder="smtp.example.com",
            ),
            Field(
                "smtp_port", "SMTP port (advanced)", required=False, placeholder="587"
            ),
        ],
        instructions=[
            "Gmail: ative a verificação em duas etapas e crie uma senha de app em myaccount.google.com/apppasswords.",
            "iCloud: gere uma senha específica de app em account.apple.com → Início de Sessão e Segurança.",
            "Informe seu endereço e a senha de app abaixo. Os servidores de Gmail, iCloud e Fastmail são detectados automaticamente; para outros provedores, preencha os hosts IMAP/SMTP.",
            "Observação: contas do Google Workspace e do Microsoft 365 costumam ter IMAP ou senhas de app desativados pelo administrador.",
        ],
        validate=_validate_email,
    ),
    ConnectorDescriptor(
        name="gmail",
        title="Gmail",
        icon="✉",
        blurb="Buscar, resumir, redigir e enviar e-mails.",
        auth="oauth",
        two_way=False,
        brand_color="#ea4335",
        aliases=("email", "mail", "google"),
        logo="gmail",
        fields=[
            Field(
                "access_token",
                "OAuth access token",
                secret=True,
                help="Google OAuth token with Gmail scopes.",
            ),
        ],
        instructions=[
            "Use um token de acesso OAuth do Google com escopos de leitura e envio do Gmail.",
            "Cole o token de acesso abaixo.",
        ],
        available=True,
        managed=True,
        # Google OAuth verification (CASA) pending — one-click off until it clears.
        managed_paused=True,
    ),
    ConnectorDescriptor(
        name="google_calendar",
        title="Google Calendar",
        icon="◷",
        blurb="Ler disponibilidade, resumir agendas e criar eventos.",
        auth="oauth",
        two_way=False,
        brand_color="#4285f4",
        logo="google_calendar",
        fields=[
            Field(
                "access_token",
                "OAuth access token",
                secret=True,
                help="Google OAuth token with Calendar scopes.",
            ),
        ],
        instructions=[
            "Use um token de acesso OAuth do Google com escopos de leitura/escrita do Calendar.",
            "Cole o token de acesso abaixo.",
        ],
        available=True,
        managed=True,
        managed_paused=True,  # same Google app as Gmail — paused until CASA clears
    ),
    ConnectorDescriptor(
        name="browser",
        title="Navegador",
        icon="⌕",
        blurb="Permite que os agentes naveguem, leiam e ajam em sites com aprovação.",
        auth="none",
        two_way=False,
        brand_color="#0ea5e9",
        logo="browser",
        fields=[],
        instructions=[
            "Sem configuração. As ferramentas de navegador ficam disponíveis nas sessões Cowork."
        ],
        available=True,
    ),
    ConnectorDescriptor(
        name="github",
        title="GitHub",
        icon="⌘",
        blurb="Trabalhar com issues, pull requests, arquivos do repositório e status de CI.",
        auth="token",
        # Managed relay makes GitHub two-way: @-mentions and the agent label
        # reach the desktop through the cloud relay (github-relay-spec §2.3);
        # the manual PAT path stays request/response only.
        two_way=True,
        brand_color="#1f2328",
        logo="github",
        fields=[
            Field(
                "token",
                "Personal access token",
                secret=True,
                help="Fine-grained or classic GitHub token.",
            ),
        ],
        instructions=[
            "Crie um token de acesso pessoal do GitHub com acesso aos repositórios desejados.",
            "Para ações de escrita, inclua permissões de escrita em Issues ou Pull Requests conforme necessário.",
        ],
        available=True,
        # One-click managed path: install the GitHub App — no tokens typed.
        managed=True,
    ),
    ConnectorDescriptor(
        name="outlook",
        title="Outlook",
        icon="◎",
        blurb="E-mail e calendário do Microsoft 365: buscar, redigir e enviar e-mails; "
        "gerenciar eventos e responder a convites.",
        auth="oauth",
        two_way=False,
        brand_color="#0078d4",
        logo="outlook",
        aliases=("calendar", "email", "mail", "microsoft", "office"),
        fields=[
            Field(
                "access_token",
                "OAuth access token",
                secret=True,
                help="Microsoft Graph access token.",
            ),
        ],
        instructions=[
            "Com um clique, conecta via Mangaba Cloud (recomendado).",
            "Manual: cole um token de acesso do Microsoft Graph com escopos de Mail e Calendar.",
        ],
        validate=_validate_outlook,
        available=True,
        managed=True,
        # Key each connected mailbox by its email (the broker's `account` field,
        # from the Microsoft id_token) — same multi-account shape as Gmail/Drive.
        account_field="@identity",
    ),
    ConnectorDescriptor(
        name="jira",
        title="Jira",
        icon="◆",
        blurb="Buscar, resumir, criar e atualizar issues.",
        auth="api_token",
        two_way=False,
        brand_color="#0052cc",
        logo="jira",
        aliases=("issues", "tickets", "atlassian", "project management"),
        mcp_url="https://mcp.atlassian.com/v1/mcp",
        fields=[
            Field(
                "base_url",
                "Atlassian site URL",
                secret=False,
                help="Example: https://example.atlassian.net",
            ),
            Field("email", "Account email", secret=False),
            Field("api_token", "API token", secret=True, help="Atlassian API token."),
        ],
        instructions=[
            "Com um clique, conecta pelo login da Atlassian no seu navegador (recomendado).",
            "Manual: crie um token de API da Atlassian e cole abaixo a URL do site, o e-mail da conta e o token.",
        ],
        available=True,
    ),
    ConnectorDescriptor(
        name="monday",
        title="monday.com",
        icon="▦",
        blurb="Ler quadros e itens, acompanhar o trabalho, criar itens e publicar atualizações.",
        auth="oauth",
        two_way=False,
        brand_color="#6161ff",
        logo="monday",
        aliases=("project management", "tasks", "boards", "work management"),
        mcp_url="https://mcp.monday.com/mcp",
        fields=[],
        instructions=[
            "Com um clique, conecta pelo login do monday.com no seu navegador.",
            "O login é totalmente local — os tokens ficam neste computador.",
        ],
        available=True,
    ),
    ConnectorDescriptor(
        name="confluence",
        title="Confluence",
        icon="◫",
        blurb="Buscar espaços, ler páginas e redigir documentação.",
        auth="api_token",
        two_way=False,
        brand_color="#172b4d",
        logo="confluence",
        fields=[
            Field(
                "base_url",
                "Atlassian site URL",
                secret=False,
                help="Example: https://example.atlassian.net",
            ),
            Field("email", "Account email", secret=False),
            Field("api_token", "API token", secret=True, help="Atlassian API token."),
        ],
        instructions=[
            "Crie um token de API da Atlassian para a sua conta.",
            "Cole abaixo a URL do site, o e-mail da conta e o token de API.",
        ],
        available=True,
    ),
    ConnectorDescriptor(
        name="zendesk",
        title="Zendesk",
        icon="◇",
        blurb="Buscar tickets, resumir o contexto do cliente e redigir respostas.",
        auth="api_token",
        two_way=False,
        brand_color="#03363d",
        logo="zendesk",
        fields=[
            Field(
                "subdomain",
                "Zendesk subdomain",
                secret=False,
                help="For example, 'acme' for acme.zendesk.com.",
            ),
            Field("email", "Agent email", secret=False),
            Field("api_token", "API token", secret=True),
        ],
        instructions=[
            "Crie um token de API do Zendesk.",
            "Cole abaixo o subdomínio, o e-mail do agente e o token de API.",
        ],
        available=True,
    ),
    ConnectorDescriptor(
        name="linear",
        title="Linear",
        icon="⟋",
        blurb="Buscar, ler e criar issues no Linear.",
        auth="api_token",
        two_way=False,
        brand_color="#5e6ad2",
        logo="linear",
        fields=[
            Field(
                "api_key",
                "API key",
                secret=True,
                help="Personal API key from Linear settings.",
                placeholder="lin_api_…",
            ),
        ],
        instructions=[
            "No Linear, abra Settings → Security & access → Personal API keys.",
            "Crie uma chave e cole abaixo.",
        ],
        validate=_validate_linear,
    ),
    ConnectorDescriptor(
        name="gitlab",
        title="GitLab",
        icon="▲",
        blurb="Trabalhar com issues e merge requests no GitLab.com ou em instalação própria.",
        auth="token",
        two_way=False,
        brand_color="#fc6d26",
        logo="gitlab",
        fields=[
            Field(
                "base_url",
                "GitLab URL",
                required=False,
                help="Leave empty for gitlab.com.",
                placeholder="https://gitlab.example.com",
            ),
            Field(
                "token",
                "Personal access token",
                secret=True,
                help="Token with read_api scope (api for write actions).",
                placeholder="glpat-…",
            ),
        ],
        instructions=[
            "Crie um token de acesso pessoal do GitLab com o escopo read_api (api para ações de escrita).",
            "Para GitLab em instalação própria, informe a URL da instância; deixe vazio para gitlab.com.",
        ],
        validate=_validate_gitlab,
    ),
    ConnectorDescriptor(
        name="discord",
        title="Discord",
        icon="✦",
        blurb="Ler canais e enviar mensagens por um bot do Discord.",
        auth="bot_token",
        two_way=False,
        brand_color="#5865f2",
        logo="discord",
        fields=[
            Field(
                "bot_token",
                "Bot token",
                secret=True,
                help="From the Bot tab of your Discord application.",
            ),
        ],
        instructions=[
            "Acesse discord.com/developers/applications → New Application → Bot.",
            "Copie o token do bot e cole abaixo.",
            "Use o gerador de URL OAuth2 para convidar o bot ao seu servidor com permissões de ler e enviar mensagens.",
        ],
        validate=_validate_discord,
    ),
    ConnectorDescriptor(
        name="stripe",
        title="Stripe",
        icon="≋",
        blurb="Acesso somente leitura a clientes, cobranças e faturas.",
        auth="api_token",
        two_way=False,
        brand_color="#635bff",
        logo="stripe",
        fields=[
            Field(
                "api_key",
                "Restricted API key",
                secret=True,
                help="Read-only restricted key recommended.",
                placeholder="rk_live_…",
            ),
        ],
        instructions=[
            "No painel da Stripe, crie uma chave de API restrita com acesso de leitura a Customers, Charges e Invoices.",
            "Cole a chave abaixo. O conector expõe apenas ferramentas de leitura.",
        ],
    ),
    ConnectorDescriptor(
        name="asana",
        title="Asana",
        icon="⊙",
        blurb="Buscar e ler tarefas e projetos; criar, atualizar e comentar.",
        auth="token",
        two_way=False,
        brand_color="#f06a6a",
        logo="asana",
        aliases=("project management", "tasks", "work management"),
        # NO mcp_url (2026-07-20): Asana's V2 MCP server rejects Dynamic Client
        # Registration — it needs a pre-registered "MCP app" with an EXACT redirect
        # URI, which our dynamic sidecar port can't provide. One-click returns when
        # the broker-routed callback lands; the pinned mcp__asana__* defs sit
        # dormant until then. Manual token stays the connect path.
        fields=[
            Field(
                "token",
                "Personal access token",
                secret=True,
                help="From the Asana developer console.",
            ),
        ],
        instructions=[
            "No Asana, abra My Settings → Apps → Manage developer apps.",
            "Crie um token de acesso pessoal e cole abaixo.",
        ],
        validate=_validate_asana,
    ),
    ConnectorDescriptor(
        name="hubspot",
        title="HubSpot",
        icon="⊚",
        blurb="Buscar registros do CRM; registrar notas e tarefas, atualizar registros. Sem exclusões.",
        auth="token",
        two_way=False,
        brand_color="#ff7a59",
        logo="hubspot",
        fields=[
            Field(
                "token",
                "Private app token",
                secret=True,
                help="Access token of a HubSpot private app.",
                placeholder="pat-…",
            ),
        ],
        instructions=[
            "No HubSpot, vá em Settings → Integrations → Private Apps e crie um app.",
            "Conceda os escopos de leitura de objetos do CRM (adicione os escopos .write para notas, tarefas e atualizações).",
            "Copie o token de acesso e cole abaixo.",
        ],
        validate=_validate_hubspot,
        managed=True,
    ),
    ConnectorDescriptor(
        name="dropbox",
        title="Dropbox",
        icon="▣",
        blurb="Buscar, navegar e ler arquivos no Dropbox.",
        auth="oauth",
        two_way=False,
        brand_color="#0061ff",
        logo="dropbox",
        fields=[
            Field(
                "access_token",
                "OAuth access token",
                secret=True,
                help="Dropbox token with files.metadata.read and files.content.read scopes.",
            ),
        ],
        instructions=[
            "Crie um app no Dropbox App Console com os escopos files.metadata.read e files.content.read.",
            "Gere um token de acesso e cole abaixo. O login gerenciado vai substituir este passo manual mais adiante.",
        ],
        validate=_validate_dropbox,
    ),
    ConnectorDescriptor(
        name="box",
        title="Box",
        icon="▢",
        blurb="Buscar, navegar e ler arquivos no Box.",
        auth="oauth",
        two_way=False,
        brand_color="#0061d5",
        logo="box",
        fields=[
            Field(
                "access_token",
                "OAuth access token",
                secret=True,
                help="Box developer token or OAuth access token.",
            ),
        ],
        instructions=[
            "Crie um app do Box em app.box.com/developers/console.",
            "Gere um token de desenvolvedor (ou token de acesso OAuth) e cole abaixo. O login gerenciado vai substituir este passo manual mais adiante.",
        ],
        validate=_validate_box,
    ),
    ConnectorDescriptor(
        name="whatsapp",
        title="WhatsApp",
        icon="◌",
        blurb="Enviar mensagens de WhatsApp pela Cloud API oficial da Meta (apenas envio).",
        auth="token",
        two_way=False,
        brand_color="#25d366",
        logo="whatsapp",
        fields=[
            Field(
                "access_token",
                "Access token",
                secret=True,
                help="From your Meta app's WhatsApp setup page (a system-user token for long-lived access).",
            ),
            Field(
                "phone_number_id",
                "Phone number ID",
                help="The Cloud API phone number ID (not the phone number itself).",
            ),
        ],
        instructions=[
            "Crie um app da Meta em developers.facebook.com e adicione o produto WhatsApp.",
            "Copie o token de acesso e o ID do número de telefone na página de configuração da API.",
            "O número de teste gratuito pode enviar mensagens para até 5 destinatários verificados sem verificação de empresa.",
            "Mensagens livres só chegam a quem escreveu para o seu número nas últimas 24 horas; fora dessa janela, apenas modelos aprovados são entregues.",
        ],
        validate=_validate_whatsapp,
    ),
    ConnectorDescriptor(
        name="quickbooks",
        title="QuickBooks",
        icon="◴",
        blurb="Acesso somente leitura a clientes, faturas e relatórios financeiros.",
        auth="oauth",
        two_way=False,
        brand_color="#2ca01c",
        logo="quickbooks",
        fields=[
            Field(
                "access_token",
                "OAuth access token",
                secret=True,
                help="Intuit OAuth token with the com.intuit.quickbooks.accounting scope. Expires hourly.",
            ),
            Field(
                "realm_id",
                "Company ID (realm ID)",
                help="Shown during OAuth authorization and in the developer playground.",
            ),
            Field(
                "environment",
                "Environment",
                required=False,
                help="production (default) or sandbox.",
                placeholder="production",
            ),
        ],
        instructions=[
            "Crie um app em developer.intuit.com e autorize-o na sua empresa (o OAuth playground serve para testes).",
            "Copie o token de acesso e o ID da empresa (realm ID) e cole abaixo.",
            "Os tokens da Intuit expiram em cerca de uma hora. O login gerenciado vai substituir este passo manual mais adiante.",
        ],
        validate=_validate_quickbooks,
    ),
    # -- placeholders (available=False) --------------------------------------------
    # Not yet shipped, but referenced by persona `recommends` (e.g. Ops → datadog/pagerduty) so
    # the GUI can render a brand badge + a "connect to enable" state. A placeholder has no fields,
    # no validate, and `available=False`, so there is no connect path (connect_connector rejects an
    # unavailable connector and _profile_connected reports it disconnected). github/hubspot are NOT
    # placeholders here — they already ship as real connectors above.
    ConnectorDescriptor(
        name="datadog",
        title="Datadog",
        icon="◍",
        blurb="Puxar alertas disparados, monitores e a linha do tempo do incidente.",
        auth="none",
        two_way=False,
        fields=[],
        instructions=[],
        available=False,
        brand_color="#632ca6",
        logo="datadog",
    ),
    ConnectorDescriptor(
        name="salesforce",
        title="Salesforce",
        icon="☁",
        blurb="Ler e atualizar casos, contas e oportunidades no CRM.",
        auth="none",
        two_way=False,
        fields=[],
        instructions=[],
        available=False,
        brand_color="#00a1e0",
        logo="salesforce",
    ),
    ConnectorDescriptor(
        name="docusign",
        title="Docusign",
        icon="✍",
        blurb="Acompanhar contratos, checar o status dos envelopes e enviar documentos para assinatura.",
        auth="oauth",
        two_way=False,
        brand_color="#4c00ff",
        logo="docusign",
        fields=[
            Field(
                "access_token",
                "OAuth access token",
                secret=True,
                help="Access token from a Docusign app (JWT or authorization-code grant).",
            ),
        ],
        instructions=[
            "Crie um app no console de desenvolvedor da Docusign e conclua uma concessão OAuth.",
            "Cole o token de acesso abaixo; a conta e a base da API são descobertas automaticamente.",
        ],
        validate=_validate_docusign,
        available=True,
    ),
    ConnectorDescriptor(
        name="clickup",
        title="ClickUp",
        icon="⌃",
        blurb="Buscar tarefas e documentos; criar e atualizar itens.",
        auth="api_token",
        two_way=False,
        brand_color="#7b68ee",
        logo="clickup",
        fields=[
            Field(
                "api_token",
                "Personal API token",
                secret=True,
                help="ClickUp → Settings → Apps → API Token.",
                placeholder="pk_…",
            ),
        ],
        instructions=[
            "No ClickUp, abra Settings → Apps e gere um token de API pessoal.",
            "Cole abaixo.",
        ],
        validate=_validate_clickup,
        available=True,
    ),
    ConnectorDescriptor(
        name="google_drive",
        title="Google Drive",
        icon="◬",
        blurb="Buscar, navegar e ler arquivos no Google Drive.",
        auth="oauth",
        two_way=False,
        brand_color="#4285f4",
        logo="google_drive",
        fields=[
            Field(
                "access_token",
                "OAuth access token",
                secret=True,
                help="Google OAuth token with Drive read scopes.",
            ),
        ],
        instructions=[
            "Use um token de acesso OAuth do Google com escopo somente leitura do Drive.",
            "Cole o token de acesso abaixo.",
        ],
        validate=_validate_google_drive,
        available=True,
        managed=True,
        managed_paused=True,  # same Google app as Gmail — paused until CASA clears
        # Key each connected account by its Google email (the broker's `account`
        # field) so multiple Drive accounts list the same way Gmail's do, rather
        # than by the opaque `sub` that account_field="account_id" would use.
        account_field="@identity",
    ),
    ConnectorDescriptor(
        name="canva",
        title="Canva",
        icon="◠",
        blurb="Navegar, criar e exportar designs.",
        auth="oauth",
        two_way=False,
        brand_color="#00c4cc",
        logo="canva",
        fields=[
            Field(
                "access_token",
                "OAuth access token",
                secret=True,
                help="Access token from a Canva Connect integration.",
            ),
        ],
        instructions=[
            "Crie uma integração Connect em canva.com/developers e conclua uma concessão OAuth.",
            "Cole o token de acesso abaixo.",
        ],
        validate=_validate_canva,
        available=True,
    ),
    ConnectorDescriptor(
        name="figma",
        title="Figma",
        icon="◐",
        blurb="Ler arquivos de design e comentários; exportar assets.",
        auth="api_token",
        two_way=False,
        brand_color="#f24e1e",
        logo="figma",
        fields=[
            Field(
                "access_token",
                "Personal access token",
                secret=True,
                help="Figma → Settings → Security → Personal access tokens.",
                placeholder="figd_…",
            ),
        ],
        instructions=[
            "No Figma, abra Settings → Security e gere um token de acesso pessoal.",
            "Cole abaixo.",
        ],
        validate=_validate_figma,
        available=True,
    ),
    ConnectorDescriptor(
        name="descript",
        title="Descript",
        icon="≣",
        blurb="Ler e editar projetos de áudio e vídeo pelas transcrições.",
        auth="none",
        two_way=False,
        fields=[],
        instructions=[],
        available=False,
        brand_color="#0062ff",
        logo="descript",
    ),
    ConnectorDescriptor(
        name="clay",
        title="Clay",
        icon="⌒",
        blurb="Enriquecer pessoas e empresas; rodar fluxos de pesquisa para prospecção.",
        auth="none",
        two_way=False,
        fields=[],
        instructions=[],
        available=False,
        brand_color="#1f2328",
        logo="clay",
    ),
    ConnectorDescriptor(
        name="close",
        title="Close",
        icon="❋",
        blurb="Ler e atualizar leads, contatos e oportunidades no CRM.",
        auth="api_token",
        two_way=False,
        brand_color="#276392",
        logo="close",
        fields=[
            Field(
                "api_key",
                "API key",
                secret=True,
                help="Close → Settings → Developer → API Keys.",
                placeholder="api_…",
            ),
        ],
        instructions=[
            "No Close, abra Settings → Developer → API Keys e crie uma chave.",
            "Cole abaixo.",
        ],
        validate=_validate_close,
        available=True,
    ),
    ConnectorDescriptor(
        name="notion",
        title="Notion",
        icon="◰",
        blurb="Buscar páginas, ler conteúdo, consultar bases e criar páginas.",
        auth="oauth",
        two_way=False,
        fields=[
            Field(
                "access_token",
                "Integration secret",
                secret=True,
                help="From an internal integration at notion.so/my-integrations; "
                "share the pages it should see with the integration.",
                placeholder="ntn_…",
            ),
        ],
        instructions=[
            "Com um clique, conecta via Mangaba Cloud (recomendado).",
            "Manual: crie uma integração interna em notion.so/my-integrations,",
            "copie o segredo dela e compartilhe as páginas relevantes com a integração.",
        ],
        validate=_validate_notion,
        brand_color="#1f2328",
        logo="notion",
        managed=True,
        # Managed profiles key by the workspace id the broker sends
        # (account_id); a manual integration token falls back to the
        # validator's workspace name.
        account_field="account_id",
    ),
    ConnectorDescriptor(
        name="attio",
        title="Attio",
        icon="◵",
        blurb="Ler seu CRM do Attio: objetos, registros e notas.",
        auth="oauth",
        two_way=False,
        fields=[
            Field(
                "access_token",
                "API key",
                secret=True,
                help="Workspace Settings → Developers → API keys.",
            ),
        ],
        instructions=[
            "Com um clique, conecta via Mangaba Cloud (recomendado).",
            "Manual: crie uma chave de API em Workspace Settings → Developers.",
        ],
        validate=_validate_attio,
        brand_color="#2d7ff9",
        logo="attio",
        managed=True,
        account_field="account_id",
    ),
    ConnectorDescriptor(
        name="posthog",
        title="PostHog",
        icon="◫",
        blurb="Consultar analytics de produto: eventos, funis e insights salvos.",
        auth="api_token",
        two_way=False,
        fields=[
            Field(
                "base_url",
                "PostHog URL",
                required=False,
                help="Leave empty for US cloud; set for EU cloud or self-hosted.",
                placeholder="https://us.posthog.com",
            ),
            Field(
                "api_key",
                "Personal API key",
                secret=True,
                help="Settings → Personal API keys (read access is enough).",
                placeholder="phx_…",
            ),
            Field(
                "project_id",
                "Project ID",
                help="Settings → Project → Project ID. Add more projects as extra accounts.",
            ),
        ],
        instructions=[
            "No PostHog, abra Settings → Personal API keys e crie uma chave.",
            "Copie o Project ID em Settings → Project.",
            "Um projeto por conta — conecte de novo para adicionar outro projeto.",
        ],
        validate=_validate_posthog,
        brand_color="#f54e00",
        logo="posthog",
        account_field="project_id",
    ),
    ConnectorDescriptor(
        name="mixpanel",
        title="Mixpanel",
        icon="◭",
        blurb="Consultar eventos e segmentações do Mixpanel.",
        auth="api_token",
        two_way=False,
        fields=[
            Field("username", "Service account username", secret=False),
            Field("secret", "Service account secret", secret=True),
            Field(
                "project_id",
                "Project ID",
                help="Add more projects as extra accounts.",
            ),
        ],
        instructions=[
            "No Mixpanel, abra Organization Settings → Service Accounts e crie uma.",
            "Copie o usuário, o segredo e o seu Project ID (Project Settings).",
        ],
        validate=_validate_mixpanel,
        brand_color="#7856ff",
        logo="mixpanel",
        account_field="project_id",
    ),
    ConnectorDescriptor(
        name="amplitude",
        title="Amplitude",
        icon="∿",
        blurb="Consultar dados de gráficos do Amplitude: usuários ativos e totais de eventos.",
        auth="api_token",
        two_way=False,
        fields=[
            Field(
                "api_key", "API key", secret=True, help="Project Settings → API Keys."
            ),
            Field("secret_key", "Secret key", secret=True),
        ],
        instructions=[
            "No Amplitude, abra Settings → Projects → seu projeto → API Keys.",
            "Copie a chave de API e a chave secreta. Um projeto por conta.",
        ],
        validate=_validate_amplitude,
        brand_color="#1e61f0",
        logo="amplitude",
        account_field="@identity",
    ),
    ConnectorDescriptor(
        name="apollo",
        title="Apollo.io",
        icon="☄",
        blurb="Enriquecer pessoas e empresas; buscar na base B2B.",
        auth="api_token",
        two_way=False,
        fields=[
            Field(
                "api_key", "API key", secret=True, help="Settings → Integrations → API."
            ),
            Field(
                "label",
                "Account label",
                required=False,
                help="Name this account (used if you connect more than one).",
                placeholder="work",
            ),
        ],
        instructions=[
            "No Apollo, abra Settings → Integrations → API e crie uma chave de API.",
            "Os endpoints de enriquecimento e busca exigem um plano pago do Apollo.",
        ],
        validate=_validate_apollo,
        brand_color="#fbbf24",
        logo="apollo",
        account_field="@identity",
    ),
    ConnectorDescriptor(
        name="hunter",
        title="Hunter",
        icon="✉",
        blurb="Encontrar e verificar e-mails profissionais por domínio.",
        auth="api_token",
        two_way=False,
        fields=[
            Field(
                "api_key", "API key", secret=True, help="hunter.io → API → API keys."
            ),
        ],
        instructions=[
            "No Hunter, abra API → API keys e copie sua chave.",
        ],
        validate=_validate_hunter,
        brand_color="#fa5320",
        logo="hunter",
        account_field="@identity",
    ),
    ConnectorDescriptor(
        name="pagerduty",
        title="PagerDuty",
        icon="◔",
        blurb="Ver quem está de plantão e revisar incidentes ativos antes de acionar.",
        auth="none",
        two_way=False,
        fields=[],
        instructions=[],
        available=False,
        brand_color="#06ac38",
        logo="pagerduty",
    ),
]

_BY_NAME = {d.name: d for d in DESCRIPTORS}


def register_descriptor(descriptor: ConnectorDescriptor) -> None:
    """Register an extra connector (used by the experimental package and tests)."""
    DESCRIPTORS.append(descriptor)
    _BY_NAME[descriptor.name] = descriptor


# Experimental connectors live in a separate package so release builds can exclude the code
# entirely (see packaging/mangaba-server.spec). When the package is absent this is a no-op.
try:
    from .experimental import EXPERIMENTAL_DESCRIPTORS as _EXPERIMENTAL
except ImportError:
    _EXPERIMENTAL = []
for _exp in _EXPERIMENTAL:
    _exp.experimental = True  # enforced here, not trusted from the author
    register_descriptor(_exp)


def list_descriptors() -> list[ConnectorDescriptor]:
    return list(DESCRIPTORS)


def get_descriptor(name: str) -> Optional[ConnectorDescriptor]:
    return _BY_NAME.get(name)
