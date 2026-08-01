import { useEffect, useState } from "react";
import {
  changePasscode,
  getAuthStatus,
  getDiagnostics,
  setDailyTurnLimit,
  setSecretGuard,
  setVaultMode,
  type Diagnostics,
  getSettings,
  getTrustedWorkspaces,
  logoutPasscode,
  setOnboarded,
  setPdfSettings,
  setScratchBase,
  setSessionsPeek,
  setWorkspaceTrusted,
  type ModelSettings,
  type PdfSettings,
  type WorkspaceCommandTrust,
} from "../api";
import {
  cancelDictationModelDownload,
  deleteDictationModel,
  deviceLabel,
  downloadDictationModel,
  getAutostart,
  getDictationStatus,
  getKeepAwake,
  checkForUpdate,
  installUpdate,
  isTauri,
  listenDictationDownloadProgress,
  markDictationTestPassed,
  pickFolder,
  setAutostart,
  setKeepAwake,
  startDictation,
  stopDictation,
  verifyDictationModel,
  type DictationDownloadProgress,
  type DictationStatus,
} from "../tauri";
import { useThemePref } from "../theme";
import { Icon } from "./Icon";
import { PanelHead } from "./IntegrationsView";
import { ModelsTab } from "./ManageTabs";
import { GalleryModal } from "./GalleryModal";
import { PersonasTab } from "./PersonasTab";
import { showPersonas } from "../flags";

// Settings, restructured (Option 2) into a full-page surface that mirrors IntegrationsView's shell:
// a left sub-nav (Appearance · Files · Models · Personas) + centered panel, replacing the old
// top-tab ManageModal. Local/app concerns live here; anything external (Connectors, Messaging, MCP,
// Activity) stays under Integrations. Appearance + Files are re-skinned to the mock's Tailwind idiom;
// Models + Personas host the existing tab components inside the page shell (field re-skin to follow).
// "appearance" is the General tab's stable key — callers deep-link with it, so the
// rename (UX-021) changed only the label. "files" folded into General as a card.
type SetTab = "appearance" | "models" | "voice" | "personas";

const CARD = "rounded-xl2 border border-line bg-panel";
const FIELD_LABEL = "text-[12.5px] font-medium text-ink";
const FIELD_HELP = "text-[12px] text-muted mt-1.5 leading-relaxed";
const INPUT =
  "flex-1 min-w-0 px-3 py-2 rounded-lg border border-line bg-paper text-[13px] text-ink outline-none focus:border-accent";
const BTN_ACCENT = "text-[12.5px] px-3 py-2 rounded-lg bg-accent text-white shrink-0 disabled:opacity-40";
const BTN_BORDERED =
  "text-[12.5px] px-3 py-2 rounded-lg border border-line bg-paper hover:border-lineStrong shrink-0";

const SET_TABS: { key: SetTab; label: string; icon: "sliders" | "code" | "mic" | "sparkle" }[] = [
  { key: "appearance", label: "Geral", icon: "sliders" },
  { key: "models", label: "Modelos", icon: "code" },
  { key: "voice", label: "Entrada de voz", icon: "mic" },
  { key: "personas", label: "Personas", icon: "sparkle" },
];

export function SettingsView({
  initialTab,
  onOpenPersona,
}: {
  initialTab?: SetTab;
  onOpenPersona?: (id: string) => void;
}) {
  // Personas is flag-gated (hidden for launch) — filter the tab AND coerce a stale
  // deep-link to it (openSettings("personas") callers) so the page never opens on a
  // section with no nav entry.
  const personas = showPersonas();
  const tabs = personas ? SET_TABS : SET_TABS.filter((t) => t.key !== "personas");
  const wanted = initialTab && (personas || initialTab !== "personas") ? initialTab : "appearance";
  const [tab, setTab] = useState<SetTab>(wanted);

  return (
    <main className="flex-1 min-w-0 flex bg-paper">
      <nav className="page-subnav w-[208px] shrink-0 border-r border-line bg-panel/40 px-3 py-4">
        <div className="px-2 text-[13.5px] font-semibold mb-3 flex items-center gap-2">
          <Icon name="gear" size={16} /> Configurações
        </div>
        {tabs.map((t) => {
          const active = tab === t.key;
          return (
            <button
              key={t.key}
              className={
                "w-full text-left px-2.5 py-2 rounded-lg text-[13px] flex items-center gap-2 " +
                (active ? "bg-paper text-accent font-medium" : "text-muted hover:bg-paper hover:text-ink")
              }
              onClick={() => setTab(t.key)}
            >
              <Icon name={t.icon} size={15} /> {t.label}
            </button>
          );
        })}
      </nav>

      <div className="flex-1 min-w-0 overflow-y-auto hairline-scroll">
        <div className="max-w-3xl mx-auto px-7 py-6">
          {tab === "appearance" ? (
            <AppearanceSection />
          ) : tab === "models" ? (
            <section>
              <PanelHead
                title="Modelos"
                sub="Provedores e os modelos oferecidos no seletor do compositor. As chaves ficam guardadas apenas neste computador."
              />
              <ModelsTab />
              {/* Token savings is model-spend behavior, so it lives here (UX-021),
                  not under General. */}
              <div className="mt-6">
                <TokenSavingsCard />
              </div>
            </section>
          ) : tab === "voice" ? (
            <VoiceInputSection />
          ) : (
            <PersonasSection onOpenPersona={onOpenPersona} />
          )}
        </div>
      </div>
    </main>
  );
}

// -- Voice input: deliberate model provisioning + compatibility + microphone test (§37) --------
const voiceError = (error: unknown) =>
  error instanceof Error ? error.message : typeof error === "string" ? error : "A entrada de voz não conseguiu concluir essa ação.";

const formatBytes = (bytes: number) => {
  if (!bytes) return "0 MiB";
  return `${Math.round(bytes / 1024 / 1024)} MiB`;
};

function VoiceInputSection() {
  const [status, setStatus] = useState<DictationStatus | null>(null);
  const [progress, setProgress] = useState<DictationDownloadProgress | null>(null);
  const [phase, setPhase] = useState<"idle" | "downloading" | "verifying" | "testing" | "transcribing">("idle");
  const [error, setError] = useState<string | null>(null);
  const [testTranscript, setTestTranscript] = useState("");
  const desktop = isTauri();

  const publish = (next: DictationStatus) => {
    setStatus(next);
    window.dispatchEvent(new CustomEvent("mangaba:voice-input-changed", { detail: next }));
  };

  useEffect(() => {
    if (!desktop) return;
    let active = true;
    let unlisten = () => {};
    void listenDictationDownloadProgress((next) => {
      if (active) setProgress(next);
    }).then((stop) => {
      unlisten = stop;
    });
    void getDictationStatus().then(async (initial) => {
      if (!active || !initial) return;
      publish(initial);
      // One-time migration for models installed by the first STT cut, before verification markers.
      if (initial.model_installed && !initial.model_verified) {
        setPhase("verifying");
        try {
          const verified = await verifyDictationModel();
          if (active) publish(verified);
        } catch (verifyError) {
          if (active) setError(voiceError(verifyError));
        } finally {
          if (active) setPhase("idle");
        }
      }
    });
    return () => {
      active = false;
      unlisten();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [desktop]);

  const download = async () => {
    setError(null);
    setProgress({ downloaded_bytes: 0, total_bytes: status?.model_bytes || 0 });
    setPhase("downloading");
    try {
      publish(await downloadDictationModel());
    } catch (downloadError) {
      setError(voiceError(downloadError));
      const latest = await getDictationStatus();
      if (latest) publish(latest);
    } finally {
      setPhase("idle");
    }
  };

  const cancelDownload = async () => {
    await cancelDictationModelDownload().catch(() => undefined);
  };

  const repair = async () => {
    setError(null);
    try {
      publish(await deleteDictationModel());
      await download();
    } catch (repairError) {
      setError(voiceError(repairError));
    }
  };

  const remove = async () => {
    if (!window.confirm("Excluir o modelo Whisper local e desativar a entrada de voz?")) return;
    setError(null);
    try {
      publish(await deleteDictationModel());
      setTestTranscript("");
      setProgress(null);
    } catch (deleteError) {
      setError(voiceError(deleteError));
    }
  };

  const toggleTest = async () => {
    if (!status?.supported || !status.model_verified) return;
    setError(null);
    try {
      if (status.recording) {
        setPhase("transcribing");
        const transcript = (await stopDictation()).trim();
        setTestTranscript(transcript);
        if (!transcript) throw new Error("Nenhuma fala detectada. Tente de novo e fale um pouco mais.");
        publish(await markDictationTestPassed());
      } else {
        setTestTranscript("");
        setPhase("testing");
        publish(await startDictation());
      }
    } catch (testError) {
      setError(voiceError(testError));
      const latest = await getDictationStatus();
      if (latest) publish(latest);
    } finally {
      setPhase("idle");
    }
  };

  const downloading = phase === "downloading" || !!status?.download_in_progress;
  const progressTotal = progress?.total_bytes || status?.model_bytes || 1;
  const progressPercent = Math.min(100, Math.round(((progress?.downloaded_bytes || 0) / progressTotal) * 100));
  const ready = !!status?.supported && !!status?.model_verified && !!status?.test_passed;

  return (
    <section>
      <PanelHead
        title="Entrada de voz"
        sub="Fale naturalmente no compositor. Gravações e transcrições ficam neste dispositivo."
      />

      {!desktop ? (
        <div className={CARD + " p-4 text-[13px] text-muted"}>A configuração da entrada de voz está disponível no app desktop do Mangaba.</div>
      ) : (
        <div className="space-y-4">
          <div className="rounded-xl border border-green-200 bg-green-50/70 px-4 py-3 text-[12.5px] text-green-800">
            <span className="font-medium">Privado por padrão.</span> O áudio fica só na memória enquanto você grava e é transcrito localmente.
          </div>

          <div className={CARD}>
            <div className="p-4 flex items-start gap-3">
              <Icon name="code" size={18} className="text-accent mt-0.5" />
              <div className="min-w-0 flex-1">
                <div className="text-[13.5px] font-medium">Este dispositivo</div>
                <div className="text-[12px] text-muted mt-1">{status?.device_summary || "Verificando compatibilidade…"}</div>
                {status?.compatibility_reason && <div className="text-[12px] text-red-600 mt-1.5">{status.compatibility_reason}</div>}
              </div>
              {status && (
                <span className={"text-[11.5px] px-2 py-1 rounded-full " + (status.supported ? "bg-green-50 text-green-700" : "bg-red-50 text-red-600")}>
                  {status.supported ? "● Compatível" : "Não suportado"}
                </span>
              )}
            </div>
            <div className="border-t border-line bg-paper/50 px-4 py-3 grid grid-cols-2 gap-3 text-[12px] text-muted">
              <div><span className="block text-ink font-medium">Mac</span>macOS 12+ · Apple Silicon M1+</div>
              <div><span className="block text-ink font-medium">Windows</span>Windows 10 22H2/11 · x64</div>
              <div><span className="block text-ink font-medium">Memória</span>8 GB recomendados</div>
              <div><span className="block text-ink font-medium">Processador</span>4 núcleos de CPU recomendados</div>
            </div>
          </div>

          <div className={CARD}>
            <div className="p-4 flex items-center gap-3">
              <div className="w-9 h-9 rounded-lg bg-accentSoft text-accent grid place-items-center font-semibold">W</div>
              <div className="min-w-0 flex-1">
                <div className="text-[13.5px] font-medium">Whisper Base · Inglês</div>
                <div className="text-[12px] text-muted mt-0.5">
                  {status?.model_verified ? `Installed and verified · ${formatBytes(status.model_bytes)}` : `Local voice model · ${formatBytes(status?.model_bytes || 147_964_211)}`}
                </div>
              </div>
              {status?.model_verified ? (
                <>
                  <span className="text-[11.5px] px-2 py-1 rounded-full bg-green-50 text-green-700">Verificado</span>
                  <button className={BTN_BORDERED} onClick={() => void repair()}>Reparar</button>
                  <button className="text-[12px] text-red-600 px-2 py-2" onClick={() => void remove()}>Excluir</button>
                </>
              ) : downloading ? (
                <button className={BTN_BORDERED} onClick={() => void cancelDownload()}>Cancelar</button>
              ) : phase === "verifying" ? (
                <span className="text-[12px] text-muted">Verificando…</span>
              ) : (
                <button className={BTN_ACCENT} disabled={!status?.supported} onClick={() => void download()}>Baixar modelo</button>
              )}
            </div>
            {downloading && (
              <div className="border-t border-line px-4 py-3">
                <div className="h-1.5 rounded-full bg-line overflow-hidden"><div className="h-full bg-accent transition-all" style={{ width: `${progressPercent}%` }} /></div>
                <div className="mt-1.5 text-[11.5px] text-muted flex"><span>{formatBytes(progress?.downloaded_bytes || 0)} of {formatBytes(progressTotal)}</span><span className="ml-auto">{progressPercent}%</span></div>
              </div>
            )}
          </div>

          <div className={CARD}>
            <div className="p-4 flex items-center gap-3">
              <Icon name="mic" size={18} className={ready ? "text-green-600" : "text-muted"} />
              <div className="min-w-0 flex-1">
                <div className="text-[13.5px] font-medium">Teste do microfone</div>
                <div className="text-[12px] text-muted mt-0.5">
                  {ready ? "Seu microfone e o motor de transcrição local estão funcionando." : "Grave uma frase curta para habilitar o microfone do compositor."}
                </div>
              </div>
              {ready && <span className="text-[11.5px] px-2 py-1 rounded-full bg-green-50 text-green-700">● Ready</span>}
              <button className={BTN_BORDERED} disabled={!status?.supported || !status?.model_verified || phase === "transcribing"} onClick={() => void toggleTest()}>
                {status?.recording ? "Parar e conferir" : phase === "transcribing" ? "Transcrevendo…" : ready ? "Testar de novo" : "Testar microfone"}
              </button>
            </div>
            {status?.recording && <div className="border-t border-line px-4 py-3 text-[12px] text-accent" role="status">● Listening… speak a short phrase, then stop.</div>}
            {testTranscript && <div className="border-t border-line bg-paper/50 px-4 py-3 text-[13px]">“{testTranscript}”</div>}
          </div>

          {error && <div role="alert" className="rounded-lg border border-red-200 bg-red-50 px-3 py-2.5 text-[12px] text-red-700">{error}</div>}
        </div>
      )}
    </section>
  );
}

// -- Personas: installed/enabled/delete management, the dir/Git importer, and the
// entry point to the Persona Gallery (a screen-sized modal — installs finish back
// here, disabled pending consent; a gallery install re-mounts the list in place).
function PersonasSection({ onOpenPersona }: { onOpenPersona?: (id: string) => void }) {
  const [galleryBump, setGalleryBump] = useState(0);
  const [galleryOpen, setGalleryOpen] = useState(false);

  return (
    <section>
      <PanelHead
        title="Personas"
        sub="Quais personas estão habilitadas e visíveis no seletor, além da instalação de novos pacotes de persona."
      />
      <PersonasTab key={galleryBump} onOpenPersona={onOpenPersona} />
      <button
        className="mt-6 w-full rounded-xl2 border border-line bg-panel px-4 py-3.5 flex items-center gap-3 text-left hover:border-lineStrong"
        data-testid="gallery-link"
        onClick={() => setGalleryOpen(true)}
      >
        <Icon name="sparkle" size={16} className="text-accent shrink-0" />
        <span className="min-w-0 flex-1">
          <span className="block text-[13.5px] font-medium">Explorar a Galeria de Personas</span>
          <span className="block text-[12px] text-muted">
            Personas selecionadas pelo time Mangaba — veja o que cada uma faz antes de instalar.
          </span>
        </span>
        <span className="text-[12.5px] text-accent shrink-0">Abrir →</span>
      </button>
      {galleryOpen && (
        <GalleryModal
          onClose={() => setGalleryOpen(false)}
          onInstalled={() => setGalleryBump((b) => b + 1)}
        />
      )}
    </section>
  );
}

// -- Appearance + app behaviour ------------------------------------------------
function AppearanceSection() {
  const [theme, setTheme] = useThemePref();
  const [autostart, setAuto] = useState(false);
  const [keepAwake, setKeep] = useState(false);
  const desktop = isTauri();

  useEffect(() => {
    if (isTauri()) {
      getAutostart().then((v) => setAuto(!!v));
      getKeepAwake().then((v) => setKeep(!!v));
    }
  }, []);

  const toggleAuto = async (v: boolean) => setAuto(!!(await setAutostart(v)));
  const toggleKeep = async (v: boolean) => setKeep(!!(await setKeepAwake(v)));
  const runSetupAgain = async () => {
    await setOnboarded(false);
    window.dispatchEvent(new CustomEvent("mangaba:open-onboarding"));
  };

  return (
    <section>
      <PanelHead title="Geral" sub="Como o Mangaba se comporta e aparece nesta máquina." />

      <div className={CARD + " p-4 mb-4"}>
        <div className={FIELD_LABEL}>Tema</div>
        <div className="seg mt-2.5" role="radiogroup" aria-label="Aparência">
          {(["light", "dark", "auto"] as const).map((p) => (
            <button key={p} className={p === theme ? "active" : ""} onClick={() => setTheme(p)}>
              {p === "light" ? "Claro" : p === "dark" ? "Escuro" : "Automático"}
            </button>
          ))}
        </div>
        <div className={FIELD_HELP}>O modo automático segue a aparência do seu {deviceLabel()}.</div>
      </div>

      <SidebarCard />

      <FilesCard />

      <PasscodeCard />

      <GuardrailsCard />

      <DiagnosticsCard />

      <TrustedWorkspacesCard />

      {desktop && (
        <div className={CARD + " p-4"}>
          <div className={FIELD_LABEL + " mb-2.5"}>Sempre ativo</div>
          <label className="flex items-start gap-3 py-2">
            <input type="checkbox" className="mt-0.5" checked={autostart} onChange={(e) => toggleAuto(e.target.checked)} />
            <span>
              <span className="block text-[13px] text-ink">Abrir ao iniciar sessão</span>
              <span className="block text-[12px] text-muted">Abrir o Mangaba automaticamente quando você entrar no sistema.</span>
            </span>
          </label>
          <label className="flex items-start gap-3 py-2">
            <input type="checkbox" className="mt-0.5" checked={keepAwake} onChange={(e) => toggleKeep(e.target.checked)} />
            <span>
              <span className="block text-[13px] text-ink">Manter este sistema acordado</span>
              <span className="block text-[12px] text-muted">Impede a suspensão por inatividade para que as tarefas agendadas rodem na hora.</span>
            </span>
          </label>
        </div>
      )}

      {/* One card for the app-lifecycle actions (UX-021): the onboarding replay (§24 —
          every build, the browser dev shell runs the same first-run flow) and, on
          desktop, the manual update check (launch also checks automatically). */}
      <div className={CARD + " p-4 mt-4"}>
        <div className={FIELD_LABEL + " mb-2"}>Configuração e atualizações</div>
        <div className="flex items-center gap-2">
          <button className={BTN_BORDERED} onClick={runSetupAgain}>
            Rodar a configuração de novo
          </button>
          {desktop && <UpdateInline />}
        </div>
        <div className={FIELD_HELP}>Repete a configuração inicial: modelo, primeira automação, dicas.</div>
      </div>
    </section>
  );
}

// Senha local (mangaba/passcode.py): trocar exige a atual, e "Sair" fecha a sessão
// desta máquina — o LoginGate reaparece na hora.
function PasscodeCard() {
  const [configured, setConfigured] = useState<boolean | null>(null);
  const [open, setOpen] = useState(false);
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [confirm, setConfirm] = useState("");
  const [msg, setMsg] = useState<{ tone: "ok" | "err"; text: string } | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    getAuthStatus()
      .then((s) => setConfigured(s.configured))
      .catch(() => setConfigured(null));
  }, []);

  const reset = () => {
    setOpen(false);
    setCurrent("");
    setNext("");
    setConfirm("");
  };

  const save = async () => {
    if (next !== confirm) {
      setMsg({ tone: "err", text: "as duas senhas novas não são iguais" });
      return;
    }
    setBusy(true);
    setMsg(null);
    try {
      const out = await changePasscode(current, next);
      if (out.ok) {
        reset();
        setMsg({ tone: "ok", text: "Senha trocada. As outras sessões foram encerradas." });
      } else {
        setMsg({ tone: "err", text: out.error || "não foi possível trocar a senha" });
      }
    } finally {
      setBusy(false);
    }
  };

  if (configured === null) return null;
  return (
    <div className={CARD + " p-4 mb-4"} data-testid="passcode-card">
      <div className={FIELD_LABEL}>Senha de acesso</div>
      <div className={FIELD_HELP}>
        {configured
          ? "Pedida ao abrir o Mangaba nesta máquina. Guardada como hash, apenas aqui."
          : "Nenhuma senha definida — o Mangaba abre direto. Reinicie o app para criá-la."}
      </div>

      {configured && !open && (
        <div className="flex items-center gap-2 mt-3">
          <button className={BTN_BORDERED} onClick={() => setOpen(true)}>
            Trocar senha
          </button>
          <button
            className={BTN_BORDERED}
            onClick={() => void logoutPasscode()}
            data-testid="passcode-logout"
          >
            Sair
          </button>
        </div>
      )}

      {configured && open && (
        <div className="mt-3 space-y-2 max-w-[320px]">
          <input
            className={INPUT}
            type="password"
            placeholder="senha atual"
            value={current}
            onChange={(e) => setCurrent(e.target.value)}
          />
          <input
            className={INPUT}
            type="password"
            placeholder="nova senha (mín. 6 caracteres)"
            value={next}
            onChange={(e) => setNext(e.target.value)}
          />
          <input
            className={INPUT}
            type="password"
            placeholder="confirme a nova senha"
            value={confirm}
            onChange={(e) => setConfirm(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && void save()}
          />
          <div className="flex items-center gap-2">
            <button
              className={BTN_ACCENT}
              disabled={busy || !current || !next || !confirm}
              onClick={() => void save()}
            >
              {busy ? "Salvando…" : "Salvar"}
            </button>
            <button className="text-[12.5px] text-faint hover:text-muted" onClick={reset}>
              cancelar
            </button>
          </div>
        </div>
      )}

      {msg && (
        <div
          className={
            "text-[12.5px] mt-2.5 " + (msg.tone === "ok" ? "text-muted" : "text-danger")
          }
        >
          {msg.text}
        </div>
      )}
    </div>
  );
}

// Guarda-corpos locais (mangaba/guardrails.py): "Somente Mangaba", protetor de segredos,
// freio de gastos e o auto-bloqueio (este último vive na GUI — LoginGate).
export const AUTOLOCK_KEY = "mangaba:autolock-min";

function GuardrailsCard() {
  const [vault, setVault] = useState<boolean | null>(null);
  const [guard, setGuard] = useState(true);
  const [limit, setLimit] = useState(0);
  const [used, setUsed] = useState(0);
  const [lockMin, setLockMin] = useState<number>(() => {
    try { return parseInt(localStorage.getItem(AUTOLOCK_KEY) || "0", 10) || 0; } catch { return 0; }
  });

  useEffect(() => {
    getSettings()
      .then((s) => {
        setVault(!!s.vault_mode);
        setGuard(s.secret_guard !== false);
        setLimit(s.daily_turn_limit || 0);
        setUsed(s.turns_used_today || 0);
      })
      .catch(() => setVault(false));
  }, []);

  const saveLock = (n: number) => {
    const v = Math.max(0, Math.min(n || 0, 480));
    setLockMin(v);
    try { localStorage.setItem(AUTOLOCK_KEY, String(v)); } catch { /* melhor esforço */ }
  };

  if (vault === null) return null;
  return (
    <div className={CARD + " p-4 mb-4"} data-testid="guardrails-card">
      <div className={FIELD_LABEL}>Privacidade e limites</div>

      <label className="flex items-start gap-3 py-2 mt-1">
        <input
          type="checkbox"
          className="mt-0.5"
          checked={vault}
          data-testid="vault-toggle"
          onChange={(e) => { setVault(e.target.checked); void setVaultMode(e.target.checked); }}
        />
        <span>
          <span className="block text-[13px] text-ink">Somente Mangaba</span>
          <span className="block text-[12px] text-muted">
            Bloqueia todo provedor de terceiro: só os modelos da Mangaba rodam. A checagem
            é no servidor, então nenhum outro provedor entra na conversa nem por engano.
          </span>
        </span>
      </label>

      <label className="flex items-start gap-3 py-2">
        <input
          type="checkbox"
          className="mt-0.5"
          checked={guard}
          data-testid="secret-guard-toggle"
          onChange={(e) => { setGuard(e.target.checked); void setSecretGuard(e.target.checked); }}
        />
        <span>
          <span className="block text-[13px] text-ink">Protetor de segredos</span>
          <span className="block text-[12px] text-muted">
            Chaves de API, tokens e senhas coladas na conversa são removidos antes de a
            mensagem chegar ao modelo.
          </span>
        </span>
      </label>

      <div className="flex items-center gap-3 py-2">
        <span className="min-w-0 flex-1">
          <span className="block text-[13px] text-ink">Freio de gastos</span>
          <span className="block text-[12px] text-muted">
            Teto de turnos por dia (0 = sem teto). Hoje: {used} usados.
          </span>
        </span>
        <input
          type="number"
          min={0}
          max={10000}
          value={limit}
          data-testid="turn-limit"
          className="w-20 px-2 py-1.5 rounded-lg border border-line bg-paper text-[13px] text-ink outline-none focus:border-accent"
          onChange={(e) => {
            const n = Math.max(0, parseInt(e.target.value, 10) || 0);
            setLimit(n);
            void setDailyTurnLimit(n);
          }}
        />
      </div>

      <div className="flex items-center gap-3 py-2">
        <span className="min-w-0 flex-1">
          <span className="block text-[13px] text-ink">Bloqueio automático</span>
          <span className="block text-[12px] text-muted">
            Minutos parado até pedir a senha de novo (0 = nunca).
          </span>
        </span>
        <input
          type="number"
          min={0}
          max={480}
          value={lockMin}
          data-testid="autolock-min"
          className="w-20 px-2 py-1.5 rounded-lg border border-line bg-paper text-[13px] text-ink outline-none focus:border-accent"
          onChange={(e) => saveLock(parseInt(e.target.value, 10))}
        />
      </div>
    </div>
  );
}

// Raio-x local do servidor (/v1/diagnostics) + latência medida daqui.
function DiagnosticsCard() {
  const [d, setD] = useState<Diagnostics | null>(null);
  const [latency, setLatency] = useState<number | null>(null);

  const load = () => {
    const t0 = performance.now();
    getDiagnostics()
      .then((x) => { setD(x); setLatency(Math.round(performance.now() - t0)); })
      .catch(() => setD(null));
  };
  useEffect(load, []);

  if (!d) return null;
  const up = d.uptime_seconds;
  const uptime = up >= 3600 ? `${Math.floor(up / 3600)}h${Math.floor((up % 3600) / 60)}m` : `${Math.floor(up / 60)}m`;
  const linha = (k: string, v: string) => (
    <div className="flex items-baseline gap-2 py-0.5 text-[12.5px]">
      <span className="text-faint w-32 shrink-0">{k}</span>
      <span className="text-ink truncate">{v}</span>
    </div>
  );
  return (
    <div className={CARD + " p-4 mb-4"} data-testid="diagnostics-card">
      <div className="flex items-center">
        <div className={FIELD_LABEL}>Diagnóstico</div>
        <button className="ml-auto text-[12px] text-accent hover:underline" onClick={load}>
          atualizar
        </button>
      </div>
      <div className="mt-2">
        {linha("Servidor", `v${d.version} · Python ${d.python} · no ar há ${uptime}`)}
        {linha("Latência local", latency !== null ? `${latency} ms` : "—")}
        {linha("Modelo padrão", `${d.model}${d.model_ready ? "" : " (provedor não configurado)"}`)}
        {linha("Sessões", String(d.sessions))}
        {linha("Só Mangaba / Protetor", `${d.vault_mode ? "ligado" : "desligado"} / ${d.secret_guard ? "ligado" : "desligado"}`)}
        {linha("Dados", d.state_dir)}
      </div>
    </div>
  );
}

function TrustedWorkspacesCard() {
  const [workspaces, setWorkspaces] = useState<WorkspaceCommandTrust[] | null>(null);

  const refresh = () =>
    getTrustedWorkspaces()
      .then(setWorkspaces)
      .catch(() => setWorkspaces([]));

  useEffect(() => {
    refresh();
  }, []);

  const revoke = async (path: string) => {
    if (!window.confirm(`Revogar a confiança de comandos para ${path}?`)) return;
    await setWorkspaceTrusted(path, false);
    refresh();
  };

  return (
    <div className={CARD + " p-4 mb-4"} data-testid="trusted-workspaces-card">
      <div className={FIELD_LABEL}>Áreas de trabalho confiáveis</div>
      <div className={FIELD_HELP}>
        Projetos confiáveis podem gerenciar as permissões de comandos em .mangaba/config.toml.
      </div>
      {workspaces === null ? (
        <div className="text-[12px] text-muted mt-3">Carregando…</div>
      ) : workspaces.length === 0 ? (
        <div className="text-[12px] text-muted mt-3">Nenhuma área de trabalho é confiável.</div>
      ) : (
        <div className="mt-3 divide-y divide-line">
          {workspaces.map((workspace) => (
            <div key={workspace.workspace} className="py-2.5 flex items-start gap-3">
              <div className="min-w-0 flex-1">
                <div className="text-[12.5px] text-ink break-all">{workspace.workspace}</div>
                <div className="text-[11.5px] text-muted mt-0.5">
                  {workspace.requested_commands.length
                    ? `${workspace.requested_commands.length} permissão${workspace.requested_commands.length === 1 ? "" : "ões"} de comando do projeto`
                    : "Nenhuma permissão de comando declarada no momento"}
                  {!workspace.exists ? " · Pasta indisponível" : ""}
                </div>
              </div>
              <button
                className="text-[12px] text-red-600 px-2 py-1"
                onClick={() => void revoke(workspace.workspace)}
              >
                Revogar
              </button>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function UpdateInline() {
  const [state, setState] = useState<"idle" | "checking" | "none" | "found" | "installing" | "error">("idle");
  const [version, setVersion] = useState("");

  const check = async () => {
    setState("checking");
    try {
      const u = await checkForUpdate();
      if (u) {
        setVersion(u.version);
        setState("found");
      } else {
        setState("none");
      }
    } catch {
      setState("error");
    }
  };

  const install = async () => {
    setState("installing");
    try {
      await installUpdate(); // success restarts the app
    } catch {
      setState("error");
    }
  };

  return (
    <span className="inline-flex items-center gap-2.5">
      {state === "found" ? (
        <button className={BTN_BORDERED} onClick={install} data-testid="settings-update-install">
          Atualizar para a v{version} e reiniciar
        </button>
      ) : (
        <button
          className={BTN_BORDERED}
          onClick={check}
          disabled={state === "checking" || state === "installing"}
          data-testid="settings-update-check"
        >
          {state === "checking" ? "Verificando…" : "Verificar atualizações"}
        </button>
      )}
      {(state === "none" || state === "error" || state === "installing") && (
        <span className="text-[12px] text-muted">
          {state === "none"
            ? "Você está na versão mais recente."
            : state === "error"
              ? "Não deu para verificar agora — tente mais tarde."
              : "Baixando — o Mangaba reinicia sozinho quando estiver pronto."}
        </span>
      )}
    </span>
  );
}

// Telemetry/Privacy card removed for this release (owner ask 2026-07-22); the
// setCloudTelemetry API stays for a future opt-out surface.

// -- Sidebar density -------------------------------------------------------------
// -- Token savings (PDF attachments; owner ask, 2026-07-17) ---------------------
// Attachments replay with EVERY turn, so a big PDF quietly multiplies token spend.
// Auto-compaction of long histories is a planned follow-up (punchlist §7) — until
// then this card is the user's dial: attach thresholds + the fallback for models
// without native PDF support.
function TokenSavingsCard() {
  const [pdf, setPdf] = useState<PdfSettings | null>(null);

  useEffect(() => {
    getSettings()
      .then((s) =>
        setPdf({
          pdf_fallback: s.pdf_fallback || "text",
          pdf_max_pages: s.pdf_max_pages || 20,
          pdf_max_mb: s.pdf_max_mb || 10,
        }),
      )
      .catch(() => setPdf({ pdf_fallback: "text", pdf_max_pages: 20, pdf_max_mb: 10 }));
  }, []);

  const save = async (patch: Partial<PdfSettings>) => {
    setPdf((p) => (p ? { ...p, ...patch } : p));
    await setPdfSettings(patch);
  };

  if (!pdf) return null;
  return (
    <div className={CARD + " p-4 mb-4"} data-testid="token-savings-card">
      <div className={FIELD_LABEL}>Economia de tokens</div>
      <div className={FIELD_HELP}>
        Anexos em PDF viajam a cada turno da conversa, então documentos grandes multiplicam
        o que você gasta em tokens.
      </div>

      <div className="mt-3 text-[13px] text-ink">PDFs em modelos sem suporte nativo a PDF</div>
      <div className="seg mt-2" role="radiogroup" aria-label="Alternativa para PDF" data-testid="pdf-fallback">
        <button
          className={pdf.pdf_fallback === "text" ? "active" : ""}
          onClick={() => save({ pdf_fallback: "text" })}
        >
          Extrair texto
        </button>
        <button
          className={pdf.pdf_fallback === "images" ? "active" : ""}
          onClick={() => save({ pdf_fallback: "images" })}
        >
          Enviar imagens das páginas
        </button>
      </div>
      <div className={FIELD_HELP}>
        Claude, GPT e Gemini leem PDFs nativamente — isto vale só para os modelos que não
        leem (GLM, Kimi, DeepSeek, modelos locais…). Extrair texto é o mais barato; imagens
        das páginas custam mais tokens e exigem um modelo com visão.
      </div>

      <div className="mt-3 flex items-center gap-5">
        <label className="flex items-center gap-2.5">
          <span className="text-[13px] text-ink">Máx. de páginas</span>
          <input
            type="number"
            min={1}
            max={100}
            value={pdf.pdf_max_pages}
            data-testid="pdf-max-pages"
            className="w-16 px-2 py-1.5 rounded-lg border border-line bg-paper text-[13px] text-ink outline-none focus:border-accent"
            onChange={(e) => save({ pdf_max_pages: Math.max(1, Math.min(Number(e.target.value) || 20, 100)) })}
          />
        </label>
        <label className="flex items-center gap-2.5">
          <span className="text-[13px] text-ink">Tamanho máx.</span>
          <input
            type="number"
            min={1}
            max={10}
            value={pdf.pdf_max_mb}
            data-testid="pdf-max-mb"
            className="w-16 px-2 py-1.5 rounded-lg border border-line bg-paper text-[13px] text-ink outline-none focus:border-accent"
            onChange={(e) => save({ pdf_max_mb: Math.max(1, Math.min(Number(e.target.value) || 10, 10)) })}
          />
          <span className="text-[12.5px] text-muted">MB</span>
        </label>
      </div>
      <div className={FIELD_HELP}>
        PDFs acima destes limites não são anexados — em vez disso, você verá um aviso no
        compositor.
      </div>
    </div>
  );
}

function SidebarCard() {
  const [peek, setPeek] = useState<number | null>(null);

  useEffect(() => {
    getSettings()
      .then((s) => setPeek(s.sessions_peek || 5))
      .catch(() => setPeek(5));
  }, []);

  const save = async (n: number) => {
    const clamped = Math.max(1, Math.min(n || 5, 50));
    setPeek(clamped);
    await setSessionsPeek(clamped);
  };

  if (peek === null) return null;
  return (
    <div className={CARD + " p-4 mb-4"}>
      <div className={FIELD_LABEL}>Barra lateral</div>
      <label className="flex items-center gap-3 mt-2.5">
        <span className="text-[13px] text-ink">Conversas exibidas por persona</span>
        <input
          type="number"
          min={1}
          max={50}
          value={peek}
          className="w-16 px-2 py-1.5 rounded-lg border border-line bg-paper text-[13px] text-ink outline-none focus:border-accent"
          onChange={(e) => save(Number(e.target.value))}
        />
      </label>
      <div className={FIELD_HELP}>
        Listas maiores ficam atrás de &ldquo;Ver mais&rdquo;. Vale por persona e por projeto.
      </div>
    </div>
  );
}

// -- Files (scratch location) — one card inside General (UX-021: a single option
// doesn't earn its own tab) -----------------------------------------------------
function FilesCard() {
  const [settings, setSettings] = useState<ModelSettings | null>(null);
  const [scratchDraft, setScratchDraft] = useState("");
  const [scratchMsg, setScratchMsg] = useState<string | null>(null);
  const desktop = isTauri();

  const refresh = () =>
    getSettings()
      .then((s) => {
        setSettings(s);
        setScratchDraft((d) => d || s.scratch_base || "");
      })
      .catch(() => setSettings(null));
  useEffect(() => {
    refresh();
  }, []);

  const saveScratch = async () => {
    setScratchMsg(null);
    const res = await setScratchBase(scratchDraft.trim());
    if (res.ok) {
      setScratchMsg("Salvo. Novas conversas vão usar este local.");
      refresh();
    } else {
      setScratchMsg(res.error || "Não foi possível usar esse local.");
    }
  };
  const browseScratch = async () => {
    const picked = await pickFolder();
    if (picked) setScratchDraft(picked);
  };

  if (!settings) return null;

  return (
    <div className={CARD + " p-4 mb-4"}>
      <div className={FIELD_LABEL}>Arquivos</div>
        <div className="flex items-center gap-2 mt-2.5">
          <input
            className={INPUT}
            type="text"
            placeholder="~/Mangaba"
            value={scratchDraft}
            spellCheck={false}
            autoComplete="off"
            onChange={(e) => setScratchDraft(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && saveScratch()}
          />
          {desktop && (
            <button className={BTN_BORDERED} onClick={browseScratch} title="Escolher uma pasta">
              Procurar
            </button>
          )}
          <button className={BTN_ACCENT} onClick={saveScratch} disabled={!scratchDraft.trim()}>
            Salvar
          </button>
        </div>
      <div className={FIELD_HELP}>
        Cada conversa ganha sua própria pasta dentro deste local. Conversas existentes mantêm a pasta
        atual; você pode conceder acesso a mais pastas dentro de qualquer conversa.
      </div>
      {scratchMsg && <div className="text-[12.5px] text-muted mt-2.5">{scratchMsg}</div>}
    </div>
  );
}
