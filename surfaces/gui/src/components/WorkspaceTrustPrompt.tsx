import { useState } from "react";
import { setWorkspaceTrusted, type WorkspaceCommandTrust } from "../api";

export function WorkspaceTrustPrompt({
  request,
  onClose,
}: {
  request: WorkspaceCommandTrust;
  onClose: () => void;
}) {
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  const trust = async () => {
    setSaving(true);
    setError("");
    const result = await setWorkspaceTrusted(request.workspace, true).catch(() => null);
    setSaving(false);
    if (!result?.ok) {
      setError(result?.error || "Não foi possível salvar a confiança da área de trabalho.");
      return;
    }
    onClose();
  };

  return (
    <div className="gate-overlay" role="dialog" aria-modal="true" aria-labelledby="workspace-trust-title">
      <div className="gate max-w-[560px]">
        <div className="gate-mark">✦</div>
        <h2 id="workspace-trust-title">Confiar nos comandos desta área de trabalho?</h2>
        <p className="gate-sub">
          Este projeto pede que o Mangaba rode os comandos abaixo sem aprovação individual.
          A confiança vale para futuras mudanças de configuração exatamente nesta pasta até você revogá-la
          in Settings.
        </p>
        <div className="rounded-lg border border-line bg-paper px-3 py-2.5 max-h-48 overflow-y-auto">
          {request.requested_commands.map((command) => (
            <code key={command} className="block text-[12.5px] py-1 text-ink">
              {command}
            </code>
          ))}
        </div>
        <div className="text-[11.5px] text-muted mt-2 break-all">{request.workspace}</div>
        {error && <div className="gate-error">{error}</div>}
        <div className="gate-foot justify-end gap-2">
          <button className="btn" onClick={onClose} disabled={saving}>
            Keep asking
          </button>
          <button className="btn primary" onClick={() => void trust()} disabled={saving}>
            {saving ? "Salvando…" : "Confiar na área de trabalho"}
          </button>
        </div>
      </div>
    </div>
  );
}
