import { useEffect, useState } from "react";
import {
  connectConnector,
  connectManaged,
  connectMcpBacked,
  getConnectors,
  type CloudStatus,
  type Connector,
} from "../../api";
import { ConnectorBadge } from "../../connectors/ConnectorIcon";
import { ConnectSetup } from "../ManageTabs";
import { CloudSignInInline, CloudStatusPending } from "./CloudSignIn";
import { PILL_ACCENT, PILL_LINE, TAG_ACCENT } from "./ui";

// The ONE place a connection gets added (UX-DECISIONS §21): the detail page's header
// button (or the list's Connect pill) opens this sheet. Connectors with two connect
// modes get a One click | Manual pill switcher; single-mode connectors render their
// existing ConnectSetup directly (Gmail's managed flow skips the modal entirely).

const INPUT =
  "w-full px-3 py-2 rounded-lg border border-line bg-paper text-[13px] text-ink outline-none focus:border-accent";

export function AddConnectionModal({
  c,
  cloud,
  title,
  onClose,
  onChanged,
}: {
  c: Connector;
  cloud: CloudStatus | null;
  title?: string; // e.g. "Add a workspace" — defaults to "Connect {title}"
  onClose: () => void;
  onChanged: () => void;
}) {
  // MCP-backed one-click (§42): local OAuth against the vendor's hosted MCP server —
  // with manual fields alongside (jira, asana) it's a second mode; alone (monday)
  // it IS the connect flow.
  const mcpBacked = !!c.mcp;
  const twoModes =
    c.name === "slack" ||
    c.name === "hubspot" ||
    c.name === "github" ||
    c.name === "notion" ||
    c.name === "attio" ||
    (mcpBacked && c.fields.length > 0);
  const [pane, setPane] = useState<"one" | "manual">("one");

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  return (
    <div className="fixed inset-0 z-40" data-testid="add-connection-modal">
      <div className="absolute inset-0 bg-black/30" onClick={onClose} />
      <div
        className="absolute left-1/2 top-[14%] -translate-x-1/2 w-[480px] max-w-[calc(100vw-2rem)] bg-panel rounded-2xl border border-line shadow-2xl"
        role="dialog"
        aria-label={title || `Conectar ${c.title}`}
      >
        <div className="flex items-center gap-3 px-5 pt-5">
          <ConnectorBadge connector={c} size={34} title={c.title} />
          <div className="flex-1 font-semibold text-[16px] tracking-tight">
            {title || `Connect ${c.title}`}
          </div>
          <button className="text-faint hover:text-ink text-[18px] leading-none" onClick={onClose} title="Fechar">
            ×
          </button>
        </div>

        {twoModes ? (
          <>
            <div className="px-5 pt-4">
              <div className="inline-flex rounded-full p-0.5 bg-paper text-[12.5px] font-medium">
                {(["one", "manual"] as const).map((p) => (
                  <button
                    key={p}
                    data-testid={`modal-pane-${p}`}
                    className={
                      "px-3.5 py-1 rounded-full " +
                      (pane === p ? "bg-panel shadow-sm text-ink border border-line" : "text-muted")
                    }
                    onClick={() => setPane(p)}
                  >
                    {p === "one" ? "Um clique" : "Manual"}
                  </button>
                ))}
              </div>
            </div>
            {pane === "one" ? (
              mcpBacked ? (
                <McpOneClick c={c} onConnected={() => { onChanged(); onClose(); }} />
              ) : c.name === "hubspot" ? (
                <HubSpotOneClick c={c} cloud={cloud} />
              ) : c.name === "github" ? (
                <GithubOneClick c={c} cloud={cloud} />
              ) : c.name === "slack" ? (
                <SlackOneClick c={c} cloud={cloud} />
              ) : (
                <GenericOneClick c={c} cloud={cloud} />
              )
            ) : c.name === "slack" ? (
              <SlackManual onConnected={() => { onChanged(); onClose(); }} />
            ) : (
              <div className="px-1.5 pb-2">
                <ConnectSetup c={c} cloud={cloud} onConnected={() => { onChanged(); onClose(); }} manualOnly />
              </div>
            )}
          </>
        ) : mcpBacked ? (
          /* MCP-backed with no manual fields (monday): one-click IS the flow. */
          <McpOneClick c={c} onConnected={() => { onChanged(); onClose(); }} />
        ) : (
          <div className="px-1.5 pb-2">
            {/* Existing combined setup (managed button + manual fields) for everything else. */}
            <ConnectSetup c={c} cloud={cloud} onConnected={() => { onChanged(); onClose(); }} />
          </div>
        )}
      </div>
    </div>
  );
}

// One-click pane for MCP-BACKED connectors (monday, asana, jira — §42): the sidecar
// runs a fully LOCAL OAuth flow against the vendor's hosted MCP server (DCR — no
// client secret, no broker, no Mangaba sign-in required). Poll until the card
// flips to connected, then close.
function McpOneClick({ c, onConnected }: { c: Connector; onConnected: () => void }) {
  const [waiting, setWaiting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    if (!waiting) return;
    const t = setInterval(async () => {
      try {
        const list = await getConnectors();
        if (list.find((x) => x.name === c.name)?.connected) onConnected();
      } catch {
        /* keep polling */
      }
    }, 2000);
    return () => clearInterval(t);
  }, [waiting, c.name, onConnected]);
  const go = async () => {
    setError(null);
    const res = await connectMcpBacked(c.name);
    if (res.ok) setWaiting(true);
    else setError(res.error || "could not start the connect");
  };
  return (
    <div className="px-5 py-4 space-y-3">
      <p className="text-[13px] text-muted">
        Abre o {c.title} no seu navegador — entre e aprove o acesso por lá. Sem digitar tokens
        e sem precisar de conta Mangaba: o login roda inteiramente neste
        computador.
      </p>
      <button
        className={PILL_ACCENT + " w-full !py-2"}
        data-testid="modal-mcp-one-click"
        onClick={go}
        disabled={waiting}
      >
        {waiting ? "Confira seu navegador…" : `Conectar ${c.title}`}
      </button>
      {error && <div className="text-[12.5px] text-danger">{error}</div>}
      <p className="text-[12px] text-faint text-center flex items-center justify-center gap-1.5">
        <span className={TAG_ACCENT}>Recomendado</span> os agentes recebem um conjunto selecionado de{" "}
        {c.title} tools · tokens stay on this computer
      </p>
    </div>
  );
}

// One-click pane for generic managed connectors (Notion, Attio, …): sign in
// with the service in the browser; each consent lands as its own account.
function GenericOneClick({ c, cloud }: { c: Connector; cloud: CloudStatus | null }) {
  const [waiting, setWaiting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const go = async () => {
    setError(null);
    const res = await connectManaged(c.name);
    if (res.ok) setWaiting(true);
    else setError(res.error || "could not start the connect");
  };
  return (
    <div className="px-5 py-4 space-y-3">
      <p className="text-[13px] text-muted">
        Opens {c.title} in your browser — approve access there. No tokens typed; connect
        again with another account to add it alongside.
      </p>
      {cloud?.signed_in ? (
        <button
          className={PILL_ACCENT + " w-full !py-2"}
          data-testid="modal-generic-one-click"
          onClick={go}
          disabled={waiting}
        >
          {waiting ? "Confira seu navegador…" : `Conectar ${c.title}`}
        </button>
      ) : cloud ? (
        <CloudSignInInline />
      ) : (
        <CloudStatusPending />
      )}
      {error && <div className="text-[12.5px] text-danger">{error}</div>}
      <p className="text-[12px] text-faint text-center flex items-center justify-center gap-1.5">
        <span className={TAG_ACCENT}>Recomendado</span> os tokens ficam neste computador
      </p>
    </div>
  );
}

function SlackOneClick({ c, cloud }: { c: Connector; cloud: CloudStatus | null }) {
  const [waiting, setWaiting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const go = async () => {
    setError(null);
    const res = await connectManaged(c.name);
    if (res.ok) setWaiting(true);
    else setError(res.error || "could not start the install");
  };
  return (
    <div className="px-5 py-4 space-y-3">
      <p className="text-[13px] text-muted">
        Opens Slack in your browser — approve @ocw for the workspace. No tokens; works for any
        number of workspaces.
      </p>
      {cloud?.signed_in ? (
        <button className={PILL_ACCENT + " w-full !py-2"} data-testid="modal-add-to-slack" onClick={go} disabled={waiting}>
          {waiting ? "Confira seu navegador…" : "Adicionar ao Slack"}
        </button>
      ) : cloud ? (
        <CloudSignInInline />
      ) : (
        <CloudStatusPending />
      )}
      {error && <div className="text-[12.5px] text-danger">{error}</div>}
      <p className="text-[12px] text-faint text-center flex items-center justify-center gap-1.5">
        <span className={TAG_ACCENT}>Recomendado</span> relay · os tokens ficam neste computador
      </p>
    </div>
  );
}

function GithubOneClick({ c, cloud }: { c: Connector; cloud: CloudStatus | null }) {
  const [waiting, setWaiting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const go = async () => {
    setError(null);
    const res = await connectManaged(c.name);
    if (res.ok) setWaiting(true);
    else setError(res.error || "could not start the install");
  };
  return (
    <div className="px-5 py-4 space-y-3">
      <p className="text-[13px] text-muted">
        Opens GitHub in your browser — approve Mangaba there. An existing @ocw-agent App
        installation links right up; otherwise you'll pick an account and repos. No tokens
        typed; the agent acts as ocw-agent[bot].
      </p>
      {cloud?.signed_in ? (
        /* One button: the broker is authorize-first — it links an existing installation or
           redirects the same tab on to the install page (the old "Already installed? Link
           it" question and the Configure dead-end are gone). */
        <button className={PILL_ACCENT + " w-full !py-2"} data-testid="modal-install-github-app" onClick={() => go()} disabled={waiting}>
          {waiting ? "Confira seu navegador…" : "Conectar o GitHub"}
        </button>
      ) : cloud ? (
        <CloudSignInInline />
      ) : (
        <CloudStatusPending />
      )}
      {error && <div className="text-[12.5px] text-danger">{error}</div>}
      <p className="text-[12px] text-faint text-center flex items-center justify-center gap-1.5">
        <span className={TAG_ACCENT}>Recomendado</span> relay · tokens de curta duração, nunca armazenados
      </p>
    </div>
  );
}

function HubSpotOneClick({ c, cloud }: { c: Connector; cloud: CloudStatus | null }) {
  const [access, setAccess] = useState<"read" | "write">("read");
  const [waiting, setWaiting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const go = async () => {
    setError(null);
    const res = await connectManaged(c.name, { access });
    if (res.ok) setWaiting(true);
    else setError(res.error || "could not start the connect");
  };
  return (
    <div className="px-5 py-4 space-y-3">
      <p className="text-[13px] text-muted">
        Abre o HubSpot no seu navegador — escolha o portal por lá. O que os agentes podem fazer é decidido
        AGORA, no consentimento:
      </p>
      <div className="space-y-1.5" data-testid="hubspot-access">
        {(
          [
            ["read", "Somente leitura", "buscar e ler contatos, empresas, negócios e tickets"],
            ["write", "Leitura e escrita", "inclui: registrar notas e tarefas, atualizar registros, criar contatos — nunca excluir"],
          ] as const
        ).map(([value, label, blurb]) => (
          <label key={value} className="flex items-start gap-2 text-[13px] cursor-pointer">
            <input
              type="radio"
              name="hubspot-access"
              className="mt-0.5"
              checked={access === value}
              data-testid={`hubspot-access-${value}`}
              onChange={() => setAccess(value)}
            />
            <span>
              <span className="font-medium">{label}</span>
              <span className="block text-[12px] text-muted">{blurb}</span>
            </span>
          </label>
        ))}
      </div>
      {cloud?.signed_in ? (
        <button className={PILL_ACCENT + " w-full !py-2"} data-testid="modal-connect-hubspot" onClick={go} disabled={waiting}>
          {waiting ? "Confira seu navegador…" : "Conectar o HubSpot"}
        </button>
      ) : cloud ? (
        <CloudSignInInline />
      ) : (
        <CloudStatusPending />
      )}
      {error && <div className="text-[12.5px] text-danger">{error}</div>}
      <p className="text-[12px] text-faint text-center">
        Funciona com qualquer número de portais · os tokens ficam neste computador
      </p>
    </div>
  );
}

function SlackManual({ onConnected }: { onConnected: () => void }) {
  const [bot, setBot] = useState("");
  const [app, setApp] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const submit = async () => {
    setBusy(true);
    setError(null);
    const res = await connectConnector("slack", { bot_token: bot.trim(), app_token: app.trim() });
    setBusy(false);
    if (res.ok) onConnected();
    else setError(res.error || "could not connect");
  };
  return (
    <div className="px-5 py-4 space-y-3">
      <ol className="list-decimal pl-4 text-[13px] text-muted space-y-1">
        <li>Crie um app em api.slack.com/apps</li>
        <li>Ative o Socket Mode, adicione os escopos do bot e instale no seu workspace</li>
        <li>Cole os dois tokens</li>
      </ol>
      <input className={INPUT} type="password" placeholder="Token do bot · xoxb-…" value={bot} spellCheck={false} onChange={(e) => setBot(e.target.value)} />
      <input className={INPUT} type="password" placeholder="Token do app · xapp-…" value={app} spellCheck={false} onChange={(e) => setApp(e.target.value)} />
      <button className={PILL_LINE + " w-full !py-2"} onClick={submit} disabled={busy || !bot.trim() || !app.trim()}>
        {busy ? "Validando…" : "Conectar"}
      </button>
      {error && <div className="text-[12.5px] text-danger">{error}</div>}
      <p className="text-[12px] text-warnInk text-center">
        Um modo por vez — isto pausa quaisquer workspaces via relay.
      </p>
    </div>
  );
}
