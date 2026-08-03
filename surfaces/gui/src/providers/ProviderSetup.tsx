import { useEffect, useRef, useState, type ReactNode } from "react";
import {
  getLocalEngine,
  getProviders,
  installLocalEngine,
  pullLocalModel,
  removeProvider,
  setProvider,
  verifyProvider,
  type LocalEngineStatus,
  type ProviderInfo,
} from "../api";
import { openExternal } from "../tauri";
import { PROVIDER_LOGOS, providerRank } from "./logos";

// The provider gallery ⇄ key form, shared by Onboarding step 1 (§39) and
// Settings ▸ Models (UX-021) so the two can never drift apart visually. The hook
// owns the interaction state machine; ProviderCards/ProviderForm own the shared
// markup. Each surface keeps its own frame (fixed-height modal vs scrolling page)
// and passes a testid prefix so both stay independently addressable in e2e.

// Where a non-developer gets an API key — deep link + one line of instructions.
export const KEY_HELP: Record<string, { url: string; label: string }> = {
  anthropic: { url: "https://console.anthropic.com/settings/keys", label: "console.anthropic.com" },
  openai: { url: "https://platform.openai.com/api-keys", label: "platform.openai.com" },
  gemini: { url: "https://aistudio.google.com/apikey", label: "aistudio.google.com" },
  fireworks: { url: "https://fireworks.ai/account/api-keys", label: "fireworks.ai" },
  together: { url: "https://api.together.xyz/settings/api-keys", label: "together.xyz" },
  zai: { url: "https://z.ai/manage-apikey/apikey-list", label: "z.ai" },
  kimi: { url: "https://platform.moonshot.ai/console/api-keys", label: "platform.moonshot.ai" },
  deepseek: { url: "https://platform.deepseek.com/api_keys", label: "platform.deepseek.com" },
  mistral: { url: "https://console.mistral.ai/api-keys", label: "console.mistral.ai" },
  qwen: { url: "https://modelstudio.console.alibabacloud.com", label: "alibabacloud.com" },
  minimax: { url: "https://platform.minimax.io", label: "platform.minimax.io" },
  xai: { url: "https://console.x.ai", label: "console.x.ai" },
};

export type Verify = { state: "idle" | "testing" | "ok" | "error"; msg?: string };

/** Brand chip: always a light plate so multicolor marks read on any theme. */
export function ProviderMark({ name, title, size = 32 }: { name: string; title: string; size?: number }) {
  const url = PROVIDER_LOGOS[name];
  return (
    <span
      className="rounded-lg border border-line grid place-items-center shrink-0"
      style={{ width: size, height: size, background: "#f6f7f8" }}
    >
      {url ? (
        <img src={url} alt="" style={{ width: size * 0.6, height: size * 0.6 }} />
      ) : (
        <span className="text-[13px] font-semibold text-muted">{title[0]}</span>
      )}
    </span>
  );
}

/** "2h ago"-style label for a provider's last completion (null when never used). */
export function relTime(epoch?: number | null): string | null {
  if (!epoch) return null;
  const secs = Math.max(0, Math.floor(Date.now() / 1000 - epoch));
  if (secs < 90) return "agora há pouco";
  const mins = Math.floor(secs / 60);
  if (mins < 60) return `há ${mins}m`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 48) return `há ${hrs}h`;
  return `há ${Math.floor(hrs / 24)}d`;
}

export interface ProviderSetupState {
  providers: ProviderInfo[];
  ordered: ProviderInfo[];
  refreshProviders: () => Promise<void>;
  providersLoaded: boolean;
  providersTimedOut: boolean;
  sel: string | null;
  info: ProviderInfo | undefined;
  fields: Record<string, string>;
  setFieldValue: (key: string, value: string) => void;
  dirty: boolean;
  verify: Verify;
  showEndpoint: boolean;
  setShowEndpoint: (v: boolean) => void;
  keylessOk: Set<string>;
  credentialed: boolean;
  savedState: boolean;
  secretFilled: boolean;
  openProvider: (name: string) => void;
  backToGallery: () => void;
  runTestAndSave: () => Promise<boolean>;
  removeKey: () => Promise<void>;
  cancelBackTimer: () => void;
  statusFor: (p: ProviderInfo, opts?: { lastUsed?: boolean }) => ReactNode;
  setVerifyError: (msg: string) => void;
  // Motor local (Mangaba Local): null until probed. Drives install-vs-detect in the form.
  engine: LocalEngineStatus | null;
  installing: boolean;
  installEngine: () => Promise<void>;
  reloadEngine: () => void;
  // Blur-save for non-secret fields on an already-configured provider (the Test button is
  // the KEY's save path; extras like anthropic's thinking_budget must not need a re-test —
  // owner-hit 2026-07-23: the budget silently never saved).
  saveField: (key: string) => Promise<void>;
  fieldSaved: string | null; // field key flashing "✓ Saved"
}

export function useProviderSetup(opts?: { onSaved?: () => void }): ProviderSetupState {
  const [providers, setProviders] = useState<ProviderInfo[]>([]);
  // Distinguishes "sidecar hasn't answered yet" from "answered with zero providers" —
  // `providers` alone can't tell those apart, so the empty gallery used to look identical
  // to a dead sidecar (same silent-catch bug fixed for model loading in Composer.tsx).
  const [providersLoaded, setProvidersLoaded] = useState(false);
  const [providersTimedOut, setProvidersTimedOut] = useState(false);
  // null = the gallery; a provider name = that provider's key form.
  const [sel, setSel] = useState<string | null>(null);
  const [fields, setFields] = useState<Record<string, string>>({});
  const [dirty, setDirty] = useState(false);
  const [showEndpoint, setShowEndpoint] = useState(false);
  const [verify, setVerify] = useState<Verify>({ state: "idle" });
  // Keyless providers (Mangaba) report configured without proving anything runs —
  // a passing Detect this session is what marks them live.
  const [keylessOk, setKeylessOk] = useState<Set<string>>(new Set());
  const [engine, setEngine] = useState<LocalEngineStatus | null>(null);
  const [installing, setInstalling] = useState(false);
  // Unsaved per-provider input survives switching cards (owner complaint 2026-07-16).
  const [drafts, setDrafts] = useState<Record<string, Record<string, string>>>({});
  const backTimer = useRef<number | null>(null);
  // Which non-secret field just blur-saved (flashes "✓ Saved" in the input).
  const [fieldSaved, setFieldSaved] = useState<string | null>(null);
  const fieldSavedTimer = useRef<number | null>(null);

  const refreshProviders = () => {
    setProvidersTimedOut(false);
    return getProviders()
      .then((p) => {
        setProviders(p);
        setProvidersLoaded(true);
      })
      .catch(() => {});
  };
  useEffect(() => {
    refreshProviders();
    return () => {
      if (backTimer.current) window.clearTimeout(backTimer.current);
    };
  }, []);

  // Same fix as Composer.tsx's model list: the sidecar fetch above swallows its error, so
  // without this the gallery just sits empty forever with no sign anything went wrong.
  // Re-arms on every refreshProviders() call (not just the initial one) by keying off
  // providersTimedOut too, so a retry that fails again still surfaces the failure.
  useEffect(() => {
    if (providersLoaded || providersTimedOut) return;
    const t = setTimeout(() => setProvidersTimedOut(true), 12000);
    return () => clearTimeout(t);
  }, [providersLoaded, providersTimedOut]);

  // Enquanto o motor instala ou um modelo baixa, o card acompanha de perto — senão a
  // barra de progresso fica parada em 0% até reabrir. A dependência lista TUDO que a
  // condição lê (bootstrap E pull), pelas razões documentadas na versão antiga do card.
  const bootPhase = engine?.bootstrap?.phase;
  const pullPhase = engine?.pull?.phase;
  useEffect(() => {
    const ativo =
      pullPhase === "pulling" ||
      bootPhase === "installing" ||
      bootPhase === "starting" ||
      bootPhase === "pulling";
    if (!ativo) return;
    const t = setInterval(() => {
      void getLocalEngine()
        .then((e) => {
          setEngine(e);
          if (e.bootstrap?.phase === "ready" || e.pull?.phase === "done") void refreshProviders();
        })
        .catch(() => {});
    }, 2000);
    return () => clearInterval(t);
  }, [bootPhase, pullPhase]);

  const reloadEngine = () => {
    void getLocalEngine().then(setEngine).catch(() => {});
  };

  const installEngine = async () => {
    setInstalling(true);
    const res = await installLocalEngine().catch(() => ({ ok: false, error: "unreachable" as string | undefined }));
    setInstalling(false);
    if (!res.ok) {
      setVerify({ state: "error", msg: res.error || "Não consegui instalar o motor local." });
      return;
    }
    // A instalação roda em segundo plano no servidor; o polling acima acompanha.
    setEngine(await getLocalEngine().catch(() => null));
  };

  const info = providers.find((p) => p.name === sel);
  const credentialed = !!info?.configured && !!info?.needs_key;

  const setVerifyError = (msg: string) => setVerify({ state: "error", msg });

  const openProvider = (name: string) => {
    const p = providers.find((x) => x.name === name);
    if (sel) setDrafts((d) => ({ ...d, [sel]: fields }));
    const draft = drafts[name];
    const next: Record<string, string> = {};
    for (const f of p?.fields || []) next[f.key] = draft?.[f.key] || p?.values?.[f.key] || f.default || "";
    setSel(name);
    setFields(next);
    setDirty(!!draft && Object.values(draft).some(Boolean));
    setVerify({ state: "idle" });
    setShowEndpoint(false);
    // Só sondamos o motor quando o usuário abre um provedor sem chave — a sonda pode
    // disparar spawn de processo, não cabe rodar no carregamento da galeria inteira.
    if (p && !p.needs_key) void getLocalEngine().then(setEngine).catch(() => {});
  };

  const backToGallery = () => {
    // Stash only UNSAVED input. The unconditional stash used to capture the just-saved
    // key on the post-Test auto-return, so revisiting a connected provider restored the
    // plaintext key into the field instead of the masked placeholder + saved pill
    // (state-restore bug, owner catch 2026-07-19). A clean form clears any stale draft.
    if (sel) setDrafts((d) => ({ ...d, [sel]: dirty ? fields : {} }));
    setSel(null);
    setVerify({ state: "idle" });
  };

  // Test = verify AND save AND return (§39: a passing Test auto-saves and takes
  // you back to the gallery, where the card now wears its ✓ — no extra clicks).
  const runTestAndSave = async (): Promise<boolean> => {
    if (!sel) return false;
    setVerify({ state: "testing" });
    const res = await verifyProvider(sel, fields).catch(() => ({ ok: false, error: "unreachable" }));
    if (!res.ok) {
      setVerify({ state: "error", msg: res.error || "couldn't verify" });
      return false;
    }
    // Keyless providers (Mangaba) report `configured: true` from the moment they're LISTED —
    // before any profile ever exists — so `!info?.configured` never fires here and a
    // successful Detect never persisted anything. Without a saved profile, the backend's
    // live-model lookup (which reads it) always came back empty, so "Detectar" showed
    // ✓ Rodando while the composer stayed with zero local models to choose. Persisting
    // unconditionally for keyless providers is safe — it's the same idempotent save.
    if (dirty || !info?.configured || !info?.needs_key) await setProvider(sel, fields).catch(() => {});
    if (!info?.needs_key) setKeylessOk((s) => new Set(s).add(sel));
    setVerify({ state: "ok" });
    setDirty(false);
    setDrafts((d) => ({ ...d, [sel]: {} }));
    await refreshProviders();
    opts?.onSaved?.();
    // Let the in-field "✓ Tested & saved" register, then slide home. NOT backToGallery:
    // the timeout would fire its stale closure (dirty/fields from before the save) and
    // re-stash the just-saved key as a draft — the state-restore bug (owner catch
    // 2026-07-19). This return path clears the draft unconditionally.
    backTimer.current = window.setTimeout(() => {
      setDrafts((d) => ({ ...d, [sel]: {} }));
      setSel(null);
      setVerify({ state: "idle" });
    }, 900);
    return true;
  };

  // Blur-save for non-secret fields when the provider is already configured: extras like
  // anthropic's thinking_budget must persist without a key re-test (owner-hit 2026-07-23 —
  // typed, left Settings, silently never saved). Secrets keep the explicit Test-to-save
  // contract; unconfigured providers save everything on their first Test.
  const saveField = async (key: string) => {
    if (!sel || !info?.configured) return;
    const spec = info.fields.find((f) => f.key === key);
    if (!spec || spec.secret) return;
    const current = (fields[key] || "").trim();
    const stored = (info.values?.[key] || "").trim();
    if (current === stored) return;
    const res = await setProvider(sel, { [key]: current }).catch(() => ({ ok: false }));
    if (!res.ok) return;
    await refreshProviders();
    opts?.onSaved?.();
    setFieldSaved(key);
    if (fieldSavedTimer.current) window.clearTimeout(fieldSavedTimer.current);
    fieldSavedTimer.current = window.setTimeout(() => setFieldSaved(null), 1400);
  };

  // Settings-only: forget the stored key; the card reverts to "Not set up".
  const removeKey = async () => {
    if (!sel) return;
    await removeProvider(sel).catch(() => {});
    setDrafts((d) => ({ ...d, [sel]: {} }));
    setKeylessOk((s) => {
      const next = new Set(s);
      next.delete(sel);
      return next;
    });
    await refreshProviders();
    opts?.onSaved?.();
    setSel(null);
    setVerify({ state: "idle" });
  };

  const statusFor = (p: ProviderInfo, o?: { lastUsed?: boolean }) => {
    if (p.configured && p.needs_key) {
      const used = o?.lastUsed ? relTime(p.last_used_at) : null;
      return (
        <span className="block text-[11.5px] text-ok font-medium truncate">
          ✓ Conectado{used ? <span className="text-muted font-normal"> · usado {used}</span> : ""}
        </span>
      );
    }
    if (!p.needs_key)
      return (
        <span className="block text-[11.5px] text-faint truncate">
          {keylessOk.has(p.name) ? (
            <span className="text-ok font-medium">✓ Rodando</span>
          ) : p.configured ? (
            // Modelo local no disco: conectado de fato, sem exigir um Detectar ritual.
            <span className="text-ok font-medium">✓ Conectado</span>
          ) : (
            "Não precisa de chave"
          )}
        </span>
      );
    return <span className="block text-[11.5px] text-faint truncate">Não configurado</span>;
  };

  return {
    providers,
    ordered: [...providers].sort((a, b) => providerRank(a.name) - providerRank(b.name)),
    refreshProviders,
    providersLoaded,
    providersTimedOut,
    sel,
    info,
    fields,
    setFieldValue: (key, value) => {
      setFields((cur) => ({ ...cur, [key]: value }));
      setDirty(true);
      setVerify({ state: "idle" });
    },
    dirty,
    verify,
    showEndpoint,
    setShowEndpoint,
    keylessOk,
    credentialed,
    // The in-field saved state (§39): green border + pill INSIDE the key box — shown
    // for stored credentials and fresh test-passes alike; typing clears it.
    savedState: (credentialed && !dirty) || verify.state === "ok",
    secretFilled: (info?.fields || []).every((f) => !f.secret || (fields[f.key] || "").trim()),
    openProvider,
    backToGallery,
    runTestAndSave,
    removeKey,
    saveField,
    fieldSaved,
    cancelBackTimer: () => {
      if (backTimer.current) window.clearTimeout(backTimer.current);
    },
    statusFor,
    setVerifyError,
    engine,
    installing,
    installEngine,
    reloadEngine,
  };
}

/** The gallery: one card per provider, each wearing its own state. */
export function ProviderCards({
  ps,
  tp,
  gridClass = "grid grid-cols-2 gap-2.5",
  lastUsed = false,
}: {
  ps: ProviderSetupState;
  tp: string; // testid prefix ("ob" onboarding, "set" settings)
  gridClass?: string;
  lastUsed?: boolean;
}) {
  const card =
    "flex items-center gap-2.5 rounded-xl border border-line bg-panel px-3 py-2.5 text-left hover:border-lineStrong transition-colors";

  if (!ps.providersLoaded) {
    if (ps.providersTimedOut)
      return (
        <button
          className="text-[12.5px] text-warnInk hover:underline"
          data-testid={`${tp}-providers-failed`}
          title="O servidor local não respondeu. Clique para tentar de novo."
          onClick={() => ps.refreshProviders()}
        >
          Sem resposta do servidor · tentar de novo
        </button>
      );
    return (
      <div className={gridClass} data-testid={`${tp}-providers-loading`} aria-label="Carregando provedores…">
        {Array.from({ length: 6 }, (_, i) => (
          <div className="skel-card" key={i} aria-hidden="true">
            <span className="skel" style={{ width: 32, height: 32 }} />
            <span className="min-w-0 flex-1">
              <span className="skel block" style={{ width: "60%", height: 11, marginBottom: 6 }} />
              <span className="skel block" style={{ width: "40%", height: 9 }} />
            </span>
          </div>
        ))}
      </div>
    );
  }

  return (
    <div className={gridClass}>
      {ps.ordered.map((p) => (
        <button
          key={p.name}
          className={card}
          data-testid={`${tp}-provider-${p.name}`}
          onClick={() => ps.openProvider(p.name)}
        >
          <ProviderMark name={p.name} title={p.title} />
          <span className="min-w-0 flex-1">
            <span className="block text-[13px] font-semibold leading-tight truncate">{p.title}</span>
            {ps.statusFor(p, { lastUsed })}
          </span>
          <span className="text-faint text-[14px]">›</span>
        </button>
      ))}
    </div>
  );
}

/** One provider's key form: crumb, brand head, fields (endpoint behind a quiet
 * disclosure), in-field saved pill, Test/Detect, key help, fixed error line.
 * `footer` renders after the error line (Settings adds "Remove key…" there). */
export function ProviderForm({
  ps,
  tp,
  footer,
}: {
  ps: ProviderSetupState;
  tp: string;
  footer?: ReactNode;
}) {
  const { info, sel } = ps;
  const label = "block text-[12px] text-muted mt-3 mb-1";
  const input =
    "w-full px-3 py-2 rounded-lg border bg-panel text-[13.5px] outline-none focus:border-accent";
  if (!sel) return null;
  return (
    <div>
      <button className="text-[12.5px] text-muted hover:text-ink" onClick={ps.backToGallery} data-testid={`${tp}-back`}>
        ‹ Todos os provedores
      </button>
      <div className="flex items-center gap-3 mt-3 mb-1">
        <ProviderMark name={info?.name || ""} title={info?.title || ""} size={36} />
        <span className="min-w-0">
          <span className="block text-[15px] font-semibold leading-tight">{info?.title}</span>
          {info ? ps.statusFor(info) : null}
        </span>
      </div>
      {info?.blurb && <p className="text-[11.5px] text-faint mt-1">{info.blurb}</p>}

      {info && !info.needs_key && (
        <p className="text-[11.5px] text-faint mt-2">
          Não precisa de chave — os modelos rodam neste computador.{" "}
          {ps.engine?.bootstrap && ps.engine.bootstrap.phase === "installing" ? (
            <span data-testid={`${tp}-engine-bootstrapping`}>
              Instalando o motor local… {Math.round((ps.engine.bootstrap.progress || 0) * 100)}%
              <span className="engine-bar"><i style={{ width: `${Math.round((ps.engine.bootstrap.progress || 0) * 100)}%` }} /></span>
            </span>
          ) : ps.engine?.pull?.phase === "pulling" ? (
            <span data-testid={`${tp}-engine-pulling`}>
              Baixando {ps.engine.pull.tag}… {Math.round((ps.engine.pull.progress || 0) * 100)}%
              <span className="engine-bar"><i style={{ width: `${Math.round((ps.engine.pull.progress || 0) * 100)}%` }} /></span>
            </span>
          ) : ps.engine?.pull?.phase === "error" ? (
            <span className="text-warnInk" data-testid={`${tp}-engine-pull-error`}>
              Falha ao baixar {ps.engine.pull.tag}: {ps.engine.pull.error || "erro desconhecido"}
            </span>
          ) : ps.engine?.pull?.phase === "done" ? (
            <span className="text-ok" data-testid={`${tp}-engine-pull-done`}>
              ✓ {ps.engine.pull.tag} pronto — clique em Detectar para usá-lo.
            </span>
          ) : ps.engine?.installed === false ? (
            // Motor ausente: instalar é o próximo passo, não "Detectar" (que só falharia).
            <button
              className="text-muted underline decoration-line underline-offset-2 hover:text-ink disabled:opacity-50"
              onClick={() => void ps.installEngine()}
              disabled={ps.installing}
              data-testid={`${tp}-install-engine`}
            >
              {ps.installing ? "Instalando o motor local…" : "Instalar o motor local (llama.cpp, ~20 MB)"}
            </button>
          ) : ps.engine ? (
            <span data-testid={`${tp}-engine-ready`}>
              {(ps.engine.models || 0) === 0
                ? "Motor local pronto, mas sem nenhum modelo baixado — baixe um para poder conversar."
                : ps.engine.running
                  ? `Motor local ativo${ps.engine.active ? ` (${ps.engine.active})` : ""}.`
                  : "Motor local instalado — clique em Detectar."}
              {/* O maior modelo que ESTA máquina roda bem (por RAM detectada): um clique baixa. */}
              {ps.engine.recommended && !(ps.engine.tags || []).includes(ps.engine.recommended.tag) && (
                <>
                  {" "}
                  <button
                    className="text-muted underline decoration-line underline-offset-2 hover:text-ink"
                    onClick={() =>
                      void pullLocalModel(ps.engine!.recommended!.tag)
                        .then((r) => {
                          if (!r.ok) ps.setVerifyError(r.error || "Não consegui baixar o modelo.");
                          ps.reloadEngine();
                        })
                        .catch(() => ps.setVerifyError("Não consegui falar com o servidor local."))
                    }
                    data-testid={`${tp}-pull-recommended`}
                  >
                    Baixar o recomendado p/ esta máquina ({ps.engine.recommended.tag}, ~{ps.engine.recommended.download_gb} GB)
                  </button>{" "}
                  <span className="text-faint">RAM detectada: {Math.round(ps.engine.recommended.ram_gb)} GB.</span>
                </>
              )}
            </span>
          ) : null}
        </p>
      )}

      {(info?.fields || []).map((f) => {
        const keyed = (info?.fields || []).some((x) => x.secret);
        // A keyed provider's base_url is an expert option — it renders BELOW the key-help
        // line as its own advanced section (owner nit 2026-07-19), not inside the loop.
        if (f.key === "base_url" && keyed) return null;
        const testable =
          (f.secret && f.key === (info?.fields || []).find((x) => x.secret)?.key) ||
          (!keyed && f.key === (info?.fields || [])[0]?.key);
        return (
          <div key={f.key}>
            <label className={label}>{f.label}</label>
            <div className="flex gap-2">
              <div className="relative flex-1 min-w-0">
                <input
                  className={input + (ps.savedState && f.secret ? " border-ok pr-32" : " border-line")}
                  type={f.secret ? "password" : "text"}
                  placeholder={f.secret && ps.credentialed && !ps.dirty ? "••••••••" : f.placeholder}
                  value={ps.fields[f.key] || ""}
                  data-testid={`${tp}-field-${f.key}`}
                  onChange={(e) => ps.setFieldValue(f.key, e.target.value)}
                  onBlur={f.secret ? undefined : () => void ps.saveField(f.key)}
                />
                {ps.fieldSaved === f.key && (
                  <span
                    className="absolute right-2 top-1/2 -translate-y-1/2 text-[11px] font-medium text-ok bg-okSoft rounded-full px-2 py-0.5 pointer-events-none"
                    data-testid={`${tp}-field-saved-${f.key}`}
                  >
                    ✓ Saved
                  </span>
                )}
                {/* §39: state lives IN the field — no status lines below. */}
                {ps.savedState && f.secret && (
                  <span
                    className="absolute right-2 top-1/2 -translate-y-1/2 text-[11px] font-medium text-ok bg-okSoft rounded-full px-2 py-0.5 pointer-events-none"
                    data-testid={`${tp}-saved-pill`}
                  >
                    ✓ Tested &amp; saved
                  </span>
                )}
                {ps.savedState && !f.secret && testable && (
                  <span
                    className="absolute right-2 top-1/2 -translate-y-1/2 text-[11px] font-medium text-ok bg-okSoft rounded-full px-2 py-0.5 pointer-events-none"
                    data-testid={`${tp}-saved-pill`}
                  >
                    ✓ Detected
                  </span>
                )}
              </div>
              {testable && (
                <button
                  className="px-4 rounded-lg border border-line text-[13px] font-medium text-ink hover:border-lineStrong shrink-0 disabled:opacity-40"
                  onClick={() => ps.runTestAndSave()}
                  disabled={ps.verify.state === "testing" || (f.secret && !ps.secretFilled && !ps.credentialed)}
                  data-testid={`${tp}-test`}
                >
                  {ps.verify.state === "testing" ? "…" : info?.needs_key ? "Testar" : "Detectar"}
                </button>
              )}
            </div>
            {f.help && !f.secret && <p className="text-[11.5px] text-faint mt-1">{f.help}</p>}
          </div>
        );
      })}

      {info?.needs_key && KEY_HELP[sel] && (
        <p className="text-[11.5px] text-faint mt-2">
          Ainda não tem chave?{" "}
          <button
            className="text-muted underline decoration-line underline-offset-2 hover:text-ink"
            onClick={() => openExternal(KEY_HELP[sel].url)}
          >
            Crie uma em {KEY_HELP[sel].label} ↗
          </button>{" "}
          — leva cerca de um minuto.
        </p>
      )}
      {info && !info.needs_key && (
        <p className="text-[11.5px] text-faint mt-2" data-testid={`${tp}-sem-chave`}>
          Não precisa de chave nem cadastro — clique em Detectar para carregar os modelos.
          {/* Estes modelos conversam, mas não acionam ferramentas: sem este aviso o usuário
              pediria "leia este arquivo" e receberia uma resposta inventada com cara de
              trabalho feito (comportamento verificado no gateway em 31/07/2026). */}
          <br />
          Eles respondem e escrevem, mas não leem arquivos nem rodam comandos — para o agente
          trabalhar com as suas ferramentas, conecte um provedor com chave.
        </p>
      )}

      {/* Custom endpoint (keyed providers only): a quiet disclosure BELOW the key help,
          with enough separation to read as its own advanced row — no explainer copy
          (owner calls 2026-07-18 + 2026-07-19). */}
      {(() => {
        const keyed = (info?.fields || []).some((x) => x.secret);
        const ep = keyed ? (info?.fields || []).find((f) => f.key === "base_url") : undefined;
        if (!ep) return null;
        if (!ps.showEndpoint)
          return (
            <button
              className="block self-start text-[12.5px] text-muted hover:text-ink mt-4"
              onClick={() => ps.setShowEndpoint(true)}
              data-testid={`${tp}-endpoint-link`}
            >
              Custom endpoint ⌄
            </button>
          );
        return (
          <div className="mt-4">
            <label className={label}>{ep.label}</label>
            <div className="relative">
              <input
                className={input + " border-line"}
                type="text"
                placeholder={ep.placeholder}
                value={ps.fields[ep.key] || ""}
                data-testid={`${tp}-field-${ep.key}`}
                onChange={(e) => ps.setFieldValue(ep.key, e.target.value)}
                onBlur={() => void ps.saveField(ep.key)}
              />
              {ps.fieldSaved === ep.key && (
                <span
                  className="absolute right-2 top-1/2 -translate-y-1/2 text-[11px] font-medium text-ok bg-okSoft rounded-full px-2 py-0.5 pointer-events-none"
                  data-testid={`${tp}-field-saved-${ep.key}`}
                >
                  ✓ Saved
                </span>
              )}
            </div>
            {ep.help && <p className="text-[11.5px] text-faint mt-1">{ep.help}</p>}
          </div>
        );
      })()}

      {/* Error line: fixed height so failures never reflow the form. */}
      <div className="mt-3 min-h-[19px] text-[12.5px]">
        {ps.verify.state === "error" && <span className="text-warnInk">{ps.verify.msg}</span>}
      </div>
      {footer}
    </div>
  );
}
