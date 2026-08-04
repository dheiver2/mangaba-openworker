import { useState } from "react";
import {
  disconnectGmailAccount,
  setGmailDefaultAccount,
  setGmailFilters,
  type GmailAccount,
} from "../../api";
import { ConnectorBadge } from "../../connectors/ConnectorIcon";
import { ConnectSetup } from "../ManageTabs";
import type { DetailProps } from "./ConnectorsSection";
import { ToolsDisclosure } from "./ToolsDisclosure";
import { FOOT, GRP, GRP_H, PILL_ACCENT, ROW, TAG_ACCENT, TAG_WARN, XBTN } from "./ui";

// The Gmail detail page (UX-DECISIONS §21): connected mailboxes (multi-account,
// Default badge, per-account disconnect) + "Never show agents" privacy filters.
// Adicionar uma conta = colar um OAuth access token do Google (caminho manual).
// (O login gerenciado do Mangaba Cloud foi removido deste fork.)

const LABEL = "text-[12.5px] text-muted w-24 shrink-0";

export function GmailDetail({ c, slack: _slack, onChanged }: DetailProps) {
  const [showManual, setShowManual] = useState(false);
  const accounts = (c.accounts ?? []) as GmailAccount[]; // email-keyed (pre-generic-layer shape)

  return (
    <div data-testid="gmail-detail">
      <div className="flex items-center gap-3.5 mb-5">
        <ConnectorBadge connector={c} size={44} title="Gmail" />
        <div className="min-w-0 flex-1">
          <h2 className="text-[20px] font-semibold tracking-tight leading-tight">Gmail</h2>
          <div className="text-[12.5px] text-muted flex items-center gap-1.5">
            {c.connected ? (
              <>
                <span className="w-2 h-2 rounded-full bg-ok" />
                <span data-testid="gmail-status">
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
          <div className={GRP} data-testid="gmail-manual-add">
            <div className={ROW + " text-[12.5px] text-muted"}>
              Cole um OAuth access token do Google — cada caixa fica separada e os agentes dizem
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
          <div className={GRP} data-testid="gmail-accounts">
            {accounts.map((a) => (
              <AccountRow key={a.email} a={a} onChanged={onChanged} />
            ))}
          </div>
        </>
      )}

      <FiltersGroup c={c} onChanged={onChanged} />

      <ToolsDisclosure c={c} onChanged={onChanged} />
      <div className={FOOT + " mt-2"}>
        Os filtros são aplicados neste computador, antes de um agente ver os resultados. As contagens do que
        foi ocultado aparecem no cartão da ferramenta e em Atividade — nunca o conteúdo.
      </div>
    </div>
  );
}

function AccountRow({ a, onChanged }: { a: GmailAccount; onChanged: () => void }) {
  const [busy, setBusy] = useState(false);
  return (
    <div className={ROW} data-testid={`gmail-account-${a.email}`}>
      <span className="min-w-0 flex-1 flex items-center gap-2">
        <span className="text-[13px] font-medium truncate">{a.email}</span>
        {a.default && <span className={TAG_ACCENT}>Padrão</span>}
        {a.needs_reauth && <span className={TAG_WARN}>⚠ Sign in again</span>}
      </span>
      {!a.default && (
        <button
          className="text-[12px] text-muted hover:text-ink shrink-0"
          data-testid={`gmail-make-default-${a.email}`}
          onClick={async () => {
            await setGmailDefaultAccount(a.email);
            onChanged();
          }}
        >
          Make default
        </button>
      )}
      <button
        className={XBTN}
        title="Desconectar esta caixa de correio"
        data-testid={`gmail-disconnect-${a.email}`}
        disabled={busy}
        onClick={async () => {
          setBusy(true);
          await disconnectGmailAccount(a.email);
          setBusy(false);
          onChanged();
        }}
      >
        ×
      </button>
    </div>
  );
}

function FiltersGroup({ c, onChanged }: Pick<DetailProps, "c" | "onChanged">) {
  const filters = c.filters ?? { senders: [], labels: [] };
  return (
    <>
      <div className={GRP_H}>Nunca mostrar aos agentes</div>
      <div className={GRP} data-testid="gmail-filters">
        <ChipListRow
          label="Remetentes"
          testid="gmail-filter-senders"
          placeholder="nome@exemplo.com ou @dominio.com"
          values={filters.senders}
          onSave={async (senders) => {
            await setGmailFilters({ senders });
            onChanged();
          }}
        />
        <ChipListRow
          label="Marcadores"
          testid="gmail-filter-labels"
          placeholder="Nome do marcador, ex.: Pessoal"
          values={filters.labels}
          onSave={async (labels) => {
            await setGmailFilters({ labels });
            onChanged();
          }}
        />
      </div>
      <div className={FOOT}>
        Matching email is silently left out of what agents read — no trace they could probe.
      </div>
    </>
  );
}

function ChipListRow({
  label,
  testid,
  placeholder,
  values,
  onSave,
}: {
  label: string;
  testid: string;
  placeholder: string;
  values: string[];
  onSave: (next: string[]) => Promise<void>;
}) {
  const [draft, setDraft] = useState("");
  const add = async () => {
    const v = draft.trim();
    if (!v) return;
    setDraft("");
    await onSave([...values, v]);
  };
  return (
    <div className={ROW} data-testid={testid}>
      <span className={LABEL}>{label}</span>
      <span className="min-w-0 flex-1 flex flex-wrap items-center gap-1.5">
        {values.map((v) => (
          <span
            key={v}
            className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full bg-paper border border-line text-[12.5px]"
          >
            {v}
            <button
              className={XBTN}
              title="remover"
              onClick={() => onSave(values.filter((x) => x !== v))}
            >
              ×
            </button>
          </span>
        ))}
        <input
          className="flex-1 min-w-[140px] bg-transparent text-[12.5px] outline-none placeholder:text-faint"
          placeholder={placeholder}
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") add();
          }}
          onBlur={() => draft.trim() && add()}
        />
      </span>
    </div>
  );
}
