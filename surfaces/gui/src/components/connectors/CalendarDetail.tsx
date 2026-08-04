import { useState } from "react";
import {
  disconnectGcalAccount,
  setGcalDefaultAccount,
  type GmailAccount,
} from "../../api";
import { ConnectorBadge } from "../../connectors/ConnectorIcon";
import { ConnectSetup } from "../ManageTabs";
import type { DetailProps } from "./ConnectorsSection";
import { ToolsDisclosure } from "./ToolsDisclosure";
import { FOOT, GRP, GRP_H, PILL_ACCENT, ROW, TAG_ACCENT, TAG_WARN, XBTN } from "./ui";

// The Google Calendar detail page: connected accounts (multi-account, Default
// badge, per-account disconnect) — Gmail's page minus the privacy filters.
// Adicionar uma conta = colar um OAuth access token do Google (caminho manual).
// (O login gerenciado do Mangaba Cloud foi removido deste fork.)

export function CalendarDetail({ c, slack: _slack, onChanged }: DetailProps) {
  const [showManual, setShowManual] = useState(false);
  const accounts = (c.accounts ?? []) as GmailAccount[]; // email-keyed (pre-generic-layer shape)

  return (
    <div data-testid="gcal-detail">
      <div className="flex items-center gap-3.5 mb-5">
        <ConnectorBadge connector={c} size={44} title="Google Calendar" />
        <div className="min-w-0 flex-1">
          <h2 className="text-[20px] font-semibold tracking-tight leading-tight">
            Google Calendar
          </h2>
          <div className="text-[12.5px] text-muted flex items-center gap-1.5">
            {c.connected ? (
              <>
                <span className="w-2 h-2 rounded-full bg-ok" />
                <span data-testid="gcal-status">
                  {accounts.length} account{accounts.length === 1 ? "" : "s"}
                </span>
              </>
            ) : (
              <span>Não conectado</span>
            )}
          </div>
        </div>
        <button
          className={PILL_ACCENT}
          data-testid="add-account-btn"
          onClick={() => setShowManual((v) => !v)}
        >
          ＋ Adicionar conta
        </button>
      </div>

      {(showManual || !c.connected) && (
        <>
          <div className={GRP_H + " !mt-0"}>Adicionar uma conta</div>
          <div className={GRP} data-testid="gcal-manual-add">
            <div className={ROW + " text-[12.5px] text-muted"}>
              Cole um OAuth access token do Google — cada conta fica separada e os agentes dizem
              qual estão usando.
            </div>
            <div className="px-1.5 py-1">
              <ConnectSetup
                c={c}
                onConnected={() => {
                  setShowManual(false);
                  onChanged();
                }}
              />
            </div>
          </div>
        </>
      )}

      {accounts.length > 0 && (
        <>
          <div className={GRP_H + " !mt-0"}>Contas</div>
          <div className={GRP} data-testid="gcal-accounts">
            {accounts.map((a) => (
              <AccountRow key={a.email} a={a} onChanged={onChanged} />
            ))}
          </div>
        </>
      )}

      <ToolsDisclosure c={c} onChanged={onChanged} />
      <div className={FOOT + " mt-2"}>
        Criar, alterar ou excluir eventos sempre pede sua aprovação antes, e a aprovação
        diz qual conta será usada.
      </div>
    </div>
  );
}

function AccountRow({ a, onChanged }: { a: GmailAccount; onChanged: () => void }) {
  const [busy, setBusy] = useState(false);
  return (
    <div className={ROW} data-testid={`gcal-account-${a.email}`}>
      <span className="min-w-0 flex-1 flex items-center gap-2">
        <span className="text-[13px] font-medium truncate">{a.email}</span>
        {a.default && <span className={TAG_ACCENT}>Padrão</span>}
        {a.needs_reauth && <span className={TAG_WARN}>⚠ Sign in again</span>}
      </span>
      {!a.default && (
        <button
          className="text-[12px] text-muted hover:text-ink shrink-0"
          data-testid={`gcal-make-default-${a.email}`}
          onClick={async () => {
            await setGcalDefaultAccount(a.email);
            onChanged();
          }}
        >
          Make default
        </button>
      )}
      <button
        className={XBTN}
        title="Desconectar esta conta"
        data-testid={`gcal-disconnect-${a.email}`}
        disabled={busy}
        onClick={async () => {
          setBusy(true);
          await disconnectGcalAccount(a.email);
          setBusy(false);
          onChanged();
        }}
      >
        ×
      </button>
    </div>
  );
}
