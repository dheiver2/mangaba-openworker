import { useEffect, useState } from "react";
import { getAudit, type AuditEvent } from "../api";
import { PanelHead } from "./IntegrationsView";

// Activity — connector/browser tool history, restructured onto the IntegrationsView page shell
// (centered panel + PanelHead + cards), replacing the legacy `page-view` layout. Read-only:
// filterable, with sanitized arguments.
const CARD = "rounded-xl2 border border-line bg-panel";
const INPUT = "px-3 py-1.5 rounded-lg border border-line bg-paper text-[13px] text-ink outline-none focus:border-accent";
const BTN_ACCENT = "text-[12.5px] px-3 py-1.5 rounded-lg bg-accent text-white shrink-0";

export function AuditView() {
  const [events, setEvents] = useState<AuditEvent[]>([]);
  const [sessionFilter, setSessionFilter] = useState("");
  const [connectorFilter, setConnectorFilter] = useState("");
  const [toolFilter, setToolFilter] = useState("");

  const refresh = () =>
    getAudit({
      limit: 150,
      session_id: sessionFilter.trim() || undefined,
      connector: connectorFilter.trim() || undefined,
      tool: toolFilter.trim() || undefined,
    })
      .then(setEvents)
      .catch(() => setEvents([]));

  useEffect(() => {
    refresh();
  }, []);

  return (
    <main className="flex-1 min-w-0 flex bg-paper">
      <div className="flex-1 min-w-0 overflow-y-auto hairline-scroll">
        <div className="max-w-4xl mx-auto px-7 py-6">
          <PanelHead
            title="Atividade"
            sub="Atividade recente dos conectores e das ferramentas de navegador. Os argumentos são sanitizados antes de serem gravados."
          />

          <div className="flex items-center gap-2 flex-wrap mb-4">
            <input className={INPUT} placeholder="id da sessão" value={sessionFilter} onChange={(e) => setSessionFilter(e.target.value)} />
            <input className={INPUT} placeholder="conector" value={connectorFilter} onChange={(e) => setConnectorFilter(e.target.value)} />
            <input className={INPUT} placeholder="ferramenta" value={toolFilter} onChange={(e) => setToolFilter(e.target.value)} />
            <button className={BTN_ACCENT} onClick={refresh}>
              Filtrar
            </button>
            <button
              className="text-[12.5px] px-3 py-1.5 rounded-lg border border-line bg-paper hover:border-lineStrong shrink-0 disabled:opacity-40"
              disabled={events.length === 0}
              data-testid="audit-csv"
              onClick={() => {
                // CSV gerado do que está NA TELA (mesmos filtros): auditoria que
                // você consegue arquivar, anexar num ticket ou abrir no Excel.
                const esc = (v: unknown) => `"${String(v ?? "").replace(/"/g, '""')}"`;
                const linhas = [
                  ["quando", "sessao", "conector", "ferramenta", "status", "argumentos"].join(";"),
                  ...events.map((ev) =>
                    [
                      ev.timestamp,
                      ev.session_id,
                      ev.connector,
                      ev.tool,
                      ev.status,
                      JSON.stringify(ev.args ?? {}),
                    ].map(esc).join(";"),
                  ),
                ];
                // BOM para o Excel pt-BR abrir com acentos certos; ";" idem (vírgula decimal).
                const blob = new Blob(["\ufeff" + linhas.join("\n")], { type: "text/csv;charset=utf-8" });
                const a = document.createElement("a");
                a.href = URL.createObjectURL(blob);
                a.download = `atividade-mangaba-${new Date().toISOString().slice(0, 10)}.csv`;
                a.click();
                URL.revokeObjectURL(a.href);
              }}
            >
              Baixar CSV
            </button>
          </div>

          {events.length === 0 ? (
            <div className={CARD + " p-4 text-[13px] text-muted"}>Nenhum evento de auditoria ainda.</div>
          ) : (
            <div className="space-y-2">
              {events.map((ev) => (
                <AuditRow ev={ev} key={ev.id} />
              ))}
            </div>
          )}
        </div>
      </div>
    </main>
  );
}

function AuditRow({ ev }: { ev: AuditEvent }) {
  return (
    <div className={CARD + " p-3.5"}>
      <div className="flex items-center gap-2 flex-wrap">
        <span className="font-mono text-[12.5px] font-medium text-ink">{ev.tool}</span>
        <span className="text-[11.5px] text-faint">
          {ev.connector || "tool"} · {ev.stage || ev.status || "event"} · {ev.timestamp}
        </span>
      </div>
      <div className="text-[11.5px] text-muted mt-0.5">
        session {ev.session_id || "-"} {ev.approval ? `· ${ev.approval}` : ""} {ev.status ? `· ${ev.status}` : ""}
      </div>
      {ev.resource && <div className="text-[11.5px] text-faint mt-0.5">resource: {ev.resource}</div>}
      {ev.args && Object.keys(ev.args).length > 0 && (
        <div className="font-mono text-[11.5px] text-muted mt-1.5 break-words">{formatAuditArgs(ev.args)}</div>
      )}
      {(ev.reason || ev.result_preview) && (
        <div className="text-[11.5px] text-faint mt-1">{ev.reason || ev.result_preview}</div>
      )}
    </div>
  );
}

function formatAuditArgs(args: Record<string, any>) {
  return Object.entries(args)
    .map(([k, v]) => `${k}=${typeof v === "string" ? v : JSON.stringify(v)}`)
    .join("  ");
}
