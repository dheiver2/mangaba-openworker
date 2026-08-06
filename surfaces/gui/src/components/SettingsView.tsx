import { useEffect, useState } from "react";
import {
  getDiagnostics,
  setDailyTurnLimit,
  setSecretGuard,
  type Diagnostics,
  getSettings,
  getTrustedWorkspaces,
  setCompactionSettings,
  setContextBar,
  setOnboarded,
  setPdfSettings,
  setScratchBase,
  setSessionsPeek,
  setWorkspaceTrusted,
  type CompactionSettings,
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
import { SkillsTab } from "./SkillsTab";
import { showPersonas } from "../flags";

// Settings, restructured (Option 2) into a full-page surface that mirrors IntegrationsView's shell:
// a left sub-nav (Appearance · Files · Models · Personas) + centered panel, replacing the old
// top-tab ManageModal. Local/app concerns live here; anything external (Connectors, Messaging, MCP,
// Activity) stays under Integrations. Appearance + Files are re-skinned to the mock's Tailwind idiom;
// Models + Personas host the existing tab components inside the page shell (field re-skin to follow).
// "appearance" is the General tab's stable key — callers deep-link with it, so the
// rename (UX-021) changed only the label. "files" folded into General as a card.
type SetTab = "appearance" | "models" | "skills" | "voice" | "personas";

const CARD = "rounded-xl2 border border-line bg-panel";
const FIELD_LABEL = "text-[12.5px] font-medium text-ink";
const FIELD_HELP = "text-[12px] text-muted mt-1.5 leading-relaxed";
const INPUT =
  "flex-1 min-w-0 px-3 py-2 rounded-lg border border-line bg-paper text-[13px] text-ink outline-none focus:border-accent";
const BTN_ACCENT = "text-[12.5px] px-3 py-2 rounded-lg bg-accent text-white shrink-0 disabled:opacity-40";
const BTN_BORDERED =
  "text-[12.5px] px-3 py-2 rounded-lg border border-line bg-paper hover:border-lineStrong shrink-0";

const SET_TABS: { key: SetTab; label: string; icon: "sliders" | "code" | "mic" | "sparkle" | "book" }[] = [
  { key: "appearance", label: "Geral", icon: "sliders" },
  { key: "models", label: "Modelos", icon: "code" },
  { key: "skills", label: "Skills", icon: "book" },
  { key: "voice", label: "Entrada de voz", icon: "mic" },
  { key: "personas", label: "Personas", icon: "sparkle" },
];

export function SettingsView({
  initialTab,
  onOpenPersona,
  onCreateSkill,
  onOpenIntegrations,
  onOpenScheduled,
}: {
  initialTab?: SetTab;
  onOpenPersona?: (id: string) => void;
  // Skills doorway (SKILLS-SPEC §5.2): start a new conversation with the description
  // prefilled — the worker builds the skill and proposes it via save_skill.
  onCreateSkill?: (description: string) => void;
  // Conectores/MCP e Automações são surfaces próprias; o subnav só ROTEIA para elas (não
  // as embute) para o usuário achá-las onde procura "configurações", sem duplicar telas.
  onOpenIntegrations?: () => void;
  onOpenScheduled?: () => void;
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

        {/* Conectores e Automações vivem em surfaces próprias. Quem procura "configurações"
            para ligar o Gmail espera achá-las aqui — estas linhas ROTEIAM para lá (o chevron
            sinaliza que saem do Settings), em vez de duplicar as telas dentro dele. */}
        {(onOpenIntegrations || onOpenScheduled) && (
          <div className="mt-3 pt-3 border-t border-line">
            {onOpenIntegrations && (
              <button
                className="w-full text-left px-2.5 py-2 rounded-lg text-[13px] flex items-center gap-2 text-muted hover:bg-paper hover:text-ink"
                onClick={onOpenIntegrations}
                data-testid="set-goto-integrations"
              >
                <Icon name="plug" size={15} /> Conectores e MCP
                <span className="ml-auto text-faint text-[14px]">›</span>
              </button>
            )}
            {onOpenScheduled && (
              <button
                className="w-full text-left px-2.5 py-2 rounded-lg text-[13px] flex items-center gap-2 text-muted hover:bg-paper hover:text-ink"
                onClick={onOpenScheduled}
                data-testid="set-goto-scheduled"
              >
                <Icon name="clock" size={15} /> Automações
                <span className="ml-auto text-faint text-[14px]">›</span>
              </button>
            )}
          </div>
        )}
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
                <CompactionCard />
              </div>
            </section>
          ) : tab === "skills" ? (
            <SkillsTab onCreateSkill={onCreateSkill} />
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

      <ContextBarCard />

      <FilesCard />


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

// Guarda-corpos locais (mangaba/guardrails.py): protetor de segredos e freio de gastos.
function GuardrailsCard() {
  const [guard, setGuard] = useState<boolean | null>(null);
  const [limit, setLimit] = useState(0);
  const [used, setUsed] = useState(0);

  useEffect(() => {
    getSettings()
      .then((s) => {
        setGuard(s.secret_guard !== false);
        setLimit(s.daily_turn_limit || 0);
        setUsed(s.turns_used_today || 0);
      })
      .catch(() => setGuard(true));
  }, []);

  if (guard === null) return null;
  return (
    <div className={CARD + " p-4 mb-4"} data-testid="guardrails-card">
      <div className={FIELD_LABEL}>Privacidade e limites</div>

      <label className="flex items-start gap-3 py-2 mt-1">
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
        {linha("Protetor de segredos", d.secret_guard ? "ligado" : "desligado")}
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
// This card is the attachment dial: attach thresholds + the fallback for models
// without native PDF support. (Long-history spend is handled by auto-compaction —
// the CompactionCard below, OPE-27.)
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

// -- Compactação de contexto (OPE-27) -------------------------------------------
// Sessões longas são resumidas automaticamente quando se aproximam do limite de
// contexto do modelo, para o trabalho continuar em vez de bater num erro cru do
// provedor. Dois overrides (gatilho % + teto de tokens) e o modelo resumidor — só.
function CompactionCard() {
  const [cfg, setCfg] = useState<CompactionSettings | null>(null);
  const [models, setModels] = useState<string[]>([]);
  const [labels, setLabels] = useState<Record<string, string>>({});

  useEffect(() => {
    getSettings()
      .then((s) => {
        setCfg({
          compaction_threshold_pct: s.compaction_threshold_pct ?? 0.8,
          compaction_cap_tokens: s.compaction_cap_tokens ?? 250_000,
          compaction_model: s.compaction_model ?? "",
        });
        setModels(s.models || []);
        setLabels(s.model_labels || {});
      })
      .catch(() =>
        setCfg({
          compaction_threshold_pct: 0.8,
          compaction_cap_tokens: 250_000,
          compaction_model: "",
        }),
      );
  }, []);

  const save = async (patch: Partial<CompactionSettings>) => {
    setCfg((p) => (p ? { ...p, ...patch } : p));
    await setCompactionSettings(patch);
  };

  if (!cfg) return null;
  const modelLabel = (id: string) => labels[id]?.split(" · ")[0] || id;
  return (
    <div className={CARD + " p-4 mb-4"} data-testid="compaction-card">
      <div className={FIELD_LABEL}>Compactação de contexto</div>
      <div className={FIELD_HELP}>
        Sessões longas são compactadas automaticamente: os turnos mais antigos são
        resumidos para o assistente continuar trabalhando em vez de ficar sem contexto.
        Sua transcrição visível nunca muda — um pequeno marcador mostra onde a
        compactação aconteceu.
      </div>

      <div className="mt-3 flex items-center gap-5 flex-wrap">
        <label className="flex items-center gap-2.5">
          <span className="text-[13px] text-ink">Compactar em</span>
          <input
            type="number"
            min={10}
            max={95}
            value={Math.round(cfg.compaction_threshold_pct * 100)}
            data-testid="compaction-threshold"
            className="w-16 px-2 py-1.5 rounded-lg border border-line bg-paper text-[13px] text-ink outline-none focus:border-accent"
            onChange={(e) =>
              save({
                compaction_threshold_pct:
                  Math.max(10, Math.min(Number(e.target.value) || 80, 95)) / 100,
              })
            }
          />
          <span className="text-[12.5px] text-muted">% da janela de contexto</span>
        </label>
        <label className="flex items-center gap-2.5">
          <span className="text-[13px] text-ink">ou em</span>
          <input
            type="number"
            min={10_000}
            max={2_000_000}
            step={10_000}
            value={cfg.compaction_cap_tokens}
            data-testid="compaction-cap"
            className="w-28 px-2 py-1.5 rounded-lg border border-line bg-paper text-[13px] text-ink outline-none focus:border-accent"
            onChange={(e) =>
              save({
                compaction_cap_tokens: Math.max(
                  10_000,
                  Math.min(Number(e.target.value) || 250_000, 2_000_000),
                ),
              })
            }
          />
          <span className="text-[12.5px] text-muted">tokens, o que for menor</span>
        </label>
      </div>
      <div className={FIELD_HELP}>
        O teto faz modelos de contexto muito grande compactarem cedo — qualidade e
        velocidade degradam bem antes do limite nominal.
      </div>

      <div className="mt-3 flex items-center gap-2.5">
        <span className="text-[13px] text-ink">Modelo resumidor</span>
        <select
          value={cfg.compaction_model}
          data-testid="compaction-model"
          className="px-2 py-1.5 rounded-lg border border-line bg-paper text-[13px] text-ink outline-none focus:border-accent"
          onChange={(e) => save({ compaction_model: e.target.value })}
        >
          <option value="">Modelo da própria sessão (padrão)</option>
          {models.map((m) => (
            <option key={m} value={m}>
              {modelLabel(m)}
            </option>
          ))}
        </select>
      </div>
      <div className={FIELD_HELP}>
        O resumo é escrito por este modelo. O padrão acompanha o modelo que a sessão
        estiver usando.
      </div>
    </div>
  );
}

// -- Composer: barra da janela de contexto (pedido do dono, 2026-07-30) ---------
// A barra do chip é a ocupação da janela de contexto; o total da sessão (sem teto)
// fica no popover. Tem gente que prefere não ver medidor nenhum, daí o toggle.
function ContextBarCard() {
  const [shown, setShown] = useState<boolean | null>(null);

  useEffect(() => {
    getSettings()
      .then((s) => setShown(s.context_bar === true))
      .catch(() => setShown(false));
  }, []);

  const save = async (next: boolean) => {
    setShown(next);
    await setContextBar(next);
  };

  if (shown === null) return null;
  return (
    <div className={CARD + " p-4 mb-4"} data-testid="context-bar-card">
      <div className={FIELD_LABEL}>Composer</div>
      <label className="flex items-start gap-3 py-2">
        <input
          type="checkbox"
          className="mt-0.5"
          data-testid="context-bar-toggle"
          checked={shown}
          onChange={(e) => save(e.target.checked)}
        />
        <span>
          <span className="block text-[13px] text-ink">Mostrar a barra da janela de contexto</span>
          <span className="block text-[12px] text-muted">
            Um medidor pequeno mostrando o quanto da janela de contexto do modelo já foi
            usado. Desligue para ver o total de tokens desta sessão no lugar; de qualquer
            forma, o detalhamento completo fica a um clique.
          </span>
        </span>
      </label>
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
