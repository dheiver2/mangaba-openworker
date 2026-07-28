import { useEffect, useRef, useState } from "react";
import {
  cloudLogin,
  connectManaged,
  getCloudStatus,
  getConnectors,
  getRecentChannels,
  waitForCloudSignIn,
  type CloudStatus,
  type Connector,
  type RecentChannel,
} from "../api";
import { ConnectorBadge } from "../connectors/ConnectorIcon";
import { deviceLabel } from "../tauri";
import { ChannelPicker } from "./SubscriptionsChip";
import { SelectMenu } from "./SelectMenu";

// The Automations quickstart (UX-DECISIONS §29): ONE template system. The former onboarding
// recipe step (§24's role recipes) merged into the page's "Start from a template" grid — every
// card carries §27's connector-dot vocabulary (brand = connected, grayscale = needs connecting);
// picking a card expands the configure card below the grid: connect rows (with the lazy cloud
// sign-in pane), channel-by-name, day × time, and the §25 consent line for write recipes.
// The `ob-*` testids moved here with the machinery.

// "When" = day choice × free time (owner call 2026-07-11); the cron assembles from the two.
const DAYS: Record<string, { label: string; dow: string }> = {
  mon: { label: "Segundas", dow: "1" },
  tue: { label: "Terças", dow: "2" },
  wed: { label: "Quartas", dow: "3" },
  thu: { label: "Quintas", dow: "4" },
  fri: { label: "Sextas", dow: "5" },
  sat: { label: "Sábados", dow: "6" },
  sun: { label: "Domingos", dow: "0" },
  weekdays: { label: "Dias úteis", dow: "1-5" },
  daily: { label: "Todo dia", dow: "*" },
};
// §30 connect-state spinner (the app has no other spinner — waits elsewhere are label swaps).
// Exported for Onboarding page 2's sign-in button (same states, same look).
export const Spinner = () => (
  <span className="inline-block w-3 h-3 rounded-full border-[1.5px] border-line2 border-t-accent animate-spin" />
);

const cronFor = (dayKey: string, hhmm: string) => {
  const [h, m] = hhmm.split(":");
  return `${Number(m) || 0} ${Number(h) || 9} * * ${DAYS[dayKey]?.dow ?? "*"}`;
};

interface QuickTemplate {
  key: string;
  title: string;
  blurb: string;
  cadence: string; // the card's footer label
  conns: { name: string; why: string }[]; // [] = no connections needed
  needsRepo?: boolean;
  needsChannel?: boolean;
  consent?: boolean; // write recipes carry the §25 consent line; reads carry disclosure
  deliver?: boolean; // Morning brief's deliver-to choice
  day: string;
  time: string;
  instructions: (ctx: { repo: string; channel: string; deliver: "app" | "slack" }) => string;
}

const TEMPLATES: QuickTemplate[] = [
  {
    key: "github",
    title: "Resumo do GitHub",
    blurb: "PRs mesclados e commits, publicados no Slack do seu time.",
    cadence: "Semanal",
    conns: [
      { name: "slack", why: "Onde o resumo é publicado" },
      { name: "github", why: "O que o resumo cobre" },
    ],
    needsRepo: true,
    needsChannel: true,
    consent: true,
    day: "mon",
    time: "09:00",
    instructions: ({ repo, channel }) =>
      `Resuma a atividade desde o último resumo no repositório do GitHub ${repo || "(o repositório conectado)"}: ` +
      `pull requests mesclados, commits relevantes e qualquer coisa que precise de atenção. ` +
      `Publique o resumo no canal do Slack ${channel} usando send_message.`,
  },
  {
    key: "pipeline",
    title: "Resumo do funil",
    blurb: "Negócios que avançaram — e os que esfriaram — publicados no Slack.",
    cadence: "Semanal",
    conns: [
      { name: "slack", why: "Onde o resumo é publicado" },
      { name: "hubspot", why: "Atividade do funil e dos negócios" },
    ],
    needsChannel: true,
    consent: true,
    day: "mon",
    time: "09:00",
    instructions: ({ channel }) =>
      `Revise a atividade do HubSpot desde o último resumo: negócios que mudaram de estágio, negócios ` +
      `parados e negócios com a data de fechamento vencida. Publique um resumo curto do funil no canal ` +
      `do Slack ${channel} usando send_message.`,
  },
  {
    key: "brief",
    title: "Briefing matinal",
    blurb: "Agenda e e-mails não lidos, resumidos antes de o dia começar.",
    cadence: "Diário",
    conns: [
      { name: "google_calendar", why: "As reuniões e brechas de hoje" },
      { name: "gmail", why: "O que chegou durante a noite" },
    ],
    deliver: true,
    day: "daily",
    time: "08:00",
    instructions: ({ deliver }) =>
      `Prepare um briefing matinal curto: os eventos e brechas da agenda de hoje, além dos e-mails que ` +
      `chegaram desde ontem à noite. ` +
      (deliver === "app" ? "Salve como entregável da sessão." : "Envie para mim por DM no Slack."),
  },
  {
    key: "news",
    title: "Briefing matinal de notícias",
    blurb: "Um resumo de 5 tópicos sobre tecnologia e mundo, salvo em markdown.",
    cadence: "Diário",
    conns: [],
    day: "daily",
    time: "08:00",
    instructions: () =>
      "Pesquise na web as notícias mais importantes de tecnologia e do mundo nas últimas 24 horas " +
      "e escreva um briefing conciso de 5 tópicos, salvo como arquivo markdown.",
  },
  {
    key: "inboxdigest",
    title: "Resumo da caixa de entrada",
    blurb: "Um resumo curto dos seus e-mails não lidos.",
    cadence: "Dias úteis",
    conns: [{ name: "gmail", why: "Seus e-mails não lidos" }],
    day: "weekdays",
    time: "09:00",
    instructions: () => "Resuma meus e-mails não lidos em uma nota curta.",
  },
  {
    key: "cotacao",
    title: "Cotação do dia",
    blurb: "Dólar, euro e Ibovespa, resumidos antes da abertura.",
    cadence: "Dias úteis",
    conns: [],
    day: "weekdays",
    time: "08:30",
    instructions: () =>
      "Pesquise na web a cotação atual do dólar e do euro em reais e o fechamento " +
      "anterior do Ibovespa. Escreva um resumo curto em português com os números e a " +
      "variação do dia, salvo como arquivo markdown.",
  },
  {
    key: "noticias-br",
    title: "Notícias do Brasil",
    blurb: "As 5 notícias mais importantes do país, sem ruído.",
    cadence: "Diário",
    conns: [],
    day: "daily",
    time: "07:30",
    instructions: () =>
      "Pesquise na web as notícias mais importantes do Brasil das últimas 24 horas " +
      "(economia, política e tecnologia). Escreva um briefing de 5 tópicos em " +
      "português, um parágrafo por tópico, salvo como arquivo markdown.",
  },
  {
    key: "semana",
    title: "Preparação da semana",
    blurb: "Segunda cedo: o que ficou aberto e o que vem pela frente.",
    cadence: "Semanal",
    conns: [],
    day: "mon",
    time: "07:00",
    instructions: () =>
      "Revise os arquivos da área de trabalho desta sessão em busca de pendências e " +
      "anotações da semana passada, e escreva um plano curto da semana em português: " +
      "o que ficou aberto, o que é prioridade e o que dá para delegar. Salve como markdown.",
  },
  {
    key: "cleanup",
    title: "Faxina de pastas",
    blurb: "Organiza os downloads recentes em pastas por tipo.",
    cadence: "Semanal",
    conns: [],
    day: "fri",
    time: "17:30",
    instructions: () => "Organize meus downloads recentes em pastas arrumadas por tipo de arquivo.",
  },
];

export function AutomationQuickstart({
  busy,
  onCreate,
}: {
  busy: boolean;
  onCreate: (payload: {
    title: string;
    instructions: string;
    cron?: string;
    permissions?: { tool: string; target: string; access: "read" | "write" }[];
  }) => void;
}) {
  const [pickedKey, setPickedKey] = useState<string | null>(null);
  const picked = TEMPLATES.find((t) => t.key === pickedKey) || null;

  const [connectors, setConnectors] = useState<Connector[]>([]);
  const [cloud, setCloud] = useState<CloudStatus | null>(null);
  const [pendingConn, setPendingConn] = useState<string | null>(null);
  // §30 connect states: "opening" while the broker POST is in flight (the browser hasn't
  // appeared yet), "waiting" once it has — the handoff strip explains the out-of-band finish.
  const [connFlow, setConnFlow] = useState<{ name: string; phase: "opening" | "waiting" } | null>(
    null,
  );
  const [signinPhase, setSigninPhase] = useState<"opening" | "waiting" | null>(null);
  const [recent, setRecent] = useState<RecentChannel[]>([]);
  const [repo, setRepo] = useState("");
  const [channel, setChannel] = useState("");
  const [day, setDay] = useState("mon");
  const [time, setTime] = useState("09:00");
  const [deliver, setDeliver] = useState<"app" | "slack">("app");
  const [consent, setConsent] = useState(true);

  const refresh = () => {
    getConnectors().then(setConnectors).catch(() => {});
    getCloudStatus().then(setCloud).catch(() => {});
  };
  // Connector state drives the card dots, so load once up front; poll only while a template
  // is being configured (connects and the cloud sign-in land out-of-band).
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  useEffect(() => {
    refresh();
  }, []);
  useEffect(() => {
    if (!picked) return;
    refresh();
    getRecentChannels().then(setRecent).catch(() => {});
    pollRef.current = setInterval(refresh, 3000);
    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pickedKey]);

  const connState = (name: string) => connectors.find((c) => c.name === name);
  const allConnected = !picked || picked.conns.every((c) => connState(c.name)?.connected);
  // §25 consent line shows the HUMAN name (owner catch 2026-07-14: it echoed the raw
  // slack:T…/C… target). Names come from a picker pick (remembered per address) or the
  // recent list; a hand-typed raw address stays raw — we never guess.
  const [picked_names, setPickedNames] = useState<Record<string, { name: string; workspace?: string }>>({});
  const pickedInfo = picked_names[channel];
  const channelName = pickedInfo?.name || recent.find((c) => c.channel === channel)?.name;
  const channelLabel = channelName ? `#${channelName}` : channel;
  const channelWorkspace = pickedInfo?.workspace;

  // The poll flipping a row to ✓ is what ends its waiting state.
  useEffect(() => {
    if (connFlow && connState(connFlow.name)?.connected) setConnFlow(null);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [connectors]);

  // §30: the configure card scrolls into view on pick — it expands below the fold on
  // three-row grids and otherwise appears "nowhere".
  const cfgRef = useRef<HTMLDivElement | null>(null);
  useEffect(() => {
    if (pickedKey) cfgRef.current?.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }, [pickedKey]);

  const pick = (t: QuickTemplate) => {
    setPickedKey(t.key);
    setDay(t.day);
    setTime(t.time);
    setConsent(true);
    setConnFlow(null);
  };

  const startConnect = async (name: string) => {
    if (!cloud?.signed_in) {
      setPendingConn(name); // the pane appears; sign-in completes it
      return;
    }
    // §30: the broker round-trip takes seconds — narrate it on the row itself.
    setConnFlow({ name, phase: "opening" });
    // GitHub is authorize-first at the BROKER: one connect links an existing
    // installation or lands on the install page — no flow choice here anymore.
    await connectManaged(name).catch(() => {});
    // The POST resolves once the system browser is off; the poll ends the waiting state.
    setConnFlow((f) => (f?.name === name ? { name, phase: "waiting" } : f));
    refresh();
  };

  const signinPollRef = useRef<(() => void) | null>(null);
  const cancelSignin = () => {
    signinPollRef.current?.();
    signinPollRef.current = null;
    setSigninPhase(null);
  };
  useEffect(() => cancelSignin, []); // never leave the poll running after unmount

  const signInThenConnect = async () => {
    setSigninPhase("opening");
    await cloudLogin().catch(() => {});
    setSigninPhase("waiting");
    // Poll until the browser flow lands, then finish the pending connect (bounded).
    signinPollRef.current = waitForCloudSignIn(async (s) => {
      signinPollRef.current = null;
      setSigninPhase(null);
      if (!s?.signed_in) return;
      setCloud(s);
      if (pendingConn) {
        const name = pendingConn;
        setConnFlow({ name, phase: "opening" });
        await connectManaged(name).catch(() => {});
        setConnFlow((f) => (f?.name === name ? { name, phase: "waiting" } : f));
        setPendingConn(null);
        refresh();
      }
    });
  };

  const create = () => {
    if (!picked) return;
    onCreate({
      title: picked.title,
      instructions: picked.instructions({ repo, channel, deliver }),
      cron: cronFor(day, time),
      permissions:
        picked.consent && consent && channel
          ? [{ tool: "send_message", target: channel, access: "write" }]
          : [],
    });
  };

  const gateHint = !allConnected
    ? `Conecte ${picked?.conns
        .filter((c) => !connState(c.name)?.connected)
        .map((c) => connState(c.name)?.title || c.name)
        .join(" e ")} para continuar`
    : picked?.needsChannel && !channel
      ? "Escolha antes um canal para publicar"
      : "";

  const label = "block text-[12px] text-muted mt-3 mb-1";
  const input =
    "w-full px-3 py-2 rounded-lg border border-line bg-panel text-[13.5px] outline-none focus:border-accent";

  return (
    <div className="mb-4">
      <div className="text-[11px] uppercase tracking-[0.05em] text-faint mb-2.5">
        Começar a partir de um modelo
      </div>
      {/* Equal-height cards (owner ask 2026-07-12): 1fr rows + h-full — <button> grid items
          don't stretch like divs. */}
      <div className="grid grid-cols-3 auto-rows-fr gap-3">
        {TEMPLATES.map((t) => (
          <button
            key={t.key}
            data-testid={`qs-template-${t.key}`}
            className={
              "h-full text-left rounded-xl2 border bg-panel p-4 flex flex-col gap-1.5 " +
              (pickedKey === t.key
                ? "border-accent ring-2 ring-accentSoft"
                : "border-line hover:border-lineStrong")
            }
            onClick={() => pick(t)}
          >
            <span className="text-[13.5px] font-semibold">{t.title}</span>
            <span className="text-[12px] text-muted leading-relaxed flex-1">{t.blurb}</span>
            <span className="flex items-center gap-1.5 mt-1">
              {t.conns.map((c) => {
                const cs = connState(c.name);
                const on = !!cs?.connected;
                return (
                  <span
                    key={c.name}
                    title={`${cs?.title || c.name} — ${on ? "conectado" : "ainda não conectado"}`}
                    style={on ? undefined : { filter: "grayscale(1)", opacity: 0.55 }}
                  >
                    {cs ? (
                      <ConnectorBadge connector={cs} size={16} title={cs.title} />
                    ) : (
                      <span className="inline-block w-4 h-4 rounded-full border border-line2" />
                    )}
                  </span>
                );
              })}
              <span className="text-[11px] text-faint ml-0.5">
                {t.conns.length === 0 ? `Sem conexões necessárias · ${t.cadence}` : t.cadence}
              </span>
            </span>
          </button>
        ))}
      </div>

      {picked && (
        <div
          ref={cfgRef}
          className="mt-3 rounded-xl2 border border-line bg-panel p-4"
          data-testid="qs-configure"
        >
          {/* §30: the card names its template — without this it starts abruptly after the grid. */}
          <div className="flex items-baseline gap-2 pb-2.5 mb-1 border-b border-line">
            <span className="text-[11px] uppercase tracking-[0.05em] text-accent font-semibold">
              Configurar
            </span>
            <span className="text-[14px] font-semibold">{picked.title}</span>
            <span className="ml-auto text-[12px] text-faint max-sm:hidden">
              {picked.conns.length ? "Conexões, entrega e agendamento" : "Entrega e agendamento"} ·{" "}
              {picked.cadence}
            </span>
          </div>
          {picked.conns.map(({ name, why }) => {
            const c = connState(name);
            const flow = connFlow?.name === name ? connFlow : null;
            return (
              <div key={name} className="border-b border-line last:border-b-0">
                <div className="flex items-center gap-3 py-2.5">
                  {c && <ConnectorBadge connector={c} size={26} title={c.title} />}
                  <span className="min-w-0 flex-1">
                    <span className="block text-[13.5px] font-medium">{c?.title || name}</span>
                    <span className="block text-[11.5px] text-faint">{why}</span>
                  </span>
                  {c?.connected ? (
                    <span className="text-[12.5px] text-ok">✓ Conectado</span>
                  ) : flow ? (
                    <span className="inline-flex items-center gap-2 text-[12px] text-muted">
                      <Spinner />
                      {flow.phase === "opening"
                        ? "Abrindo o navegador…"
                        : `Aguardando o ${c?.title || name}…`}
                    </span>
                  ) : (
                    <button
                      className="px-3.5 py-1 rounded-full border border-line text-[12.5px] hover:bg-paper"
                      onClick={() => startConnect(name)}
                      data-testid={`ob-connect-${name}`}
                    >
                      Conectar
                    </button>
                  )}
                </div>
                {/* §30 handoff strip: the flow finishes out-of-band in the browser — say so,
                    and let Cancel clear the LOCAL state (the browser tab is the user's). */}
                {flow?.phase === "waiting" && (
                  <div
                    className="flex items-start gap-2 bg-accentSoft/50 rounded-lg px-3 py-2 mb-2.5 text-[12px] text-muted"
                    data-testid="ob-connect-wait"
                  >
                    <span>↗</span>
                    <span className="flex-1 min-w-0">
                      <b className="text-ink font-medium">
                        Conclua a conexão com o {c?.title || name} no seu navegador.
                      </b>{" "}
                      Aprove por lá e volte — esta página se atualiza sozinha.
                    </span>
                    <button
                      className="text-faint underline hover:text-muted shrink-0"
                      onClick={() => setConnFlow(null)}
                      data-testid="ob-connect-cancel"
                    >
                      Cancelar
                    </button>
                  </div>
                )}
              </div>
            );
          })}

          {pendingConn && !cloud?.signed_in && (
            <div
              className="bg-accentSoft/50 rounded-xl px-4 py-3 mt-3 text-[12.5px] text-muted"
              data-testid="ob-cloudpane"
            >
              <span className="block text-[13px] text-ink font-medium">
                Um único login libera todas as conexões com um clique
              </span>
              As conexões são intermediadas pelo Mangaba Cloud — seus tokens ficam neste {deviceLabel()}.
              <div className="flex items-center gap-3 mt-2">
                {signinPhase ? (
                  <>
                    <span className="inline-flex items-center gap-2 text-[12px]">
                      <Spinner />
                      {signinPhase === "opening" ? "Abrindo o navegador…" : "Aguardando o login…"}
                    </span>
                    {signinPhase === "waiting" && (
                      <span className="text-[11.5px] text-faint">
                        Conclua o login no navegador — esta página se atualiza sozinha.{" "}
                        <button
                          className="underline hover:text-muted"
                          onClick={cancelSignin}
                          data-testid="ob-signin-cancel"
                        >
                          Cancelar
                        </button>
                      </span>
                    )}
                  </>
                ) : (
                  <button
                    className="px-3.5 py-1 rounded-full border border-line text-[12.5px] text-accent hover:bg-panel"
                    onClick={signInThenConnect}
                    data-testid="ob-cloud-signin"
                  >
                    Entrar no Mangaba Cloud
                  </button>
                )}
              </div>
            </div>
          )}

          {allConnected && (
            <div className={picked.conns.length ? "bg-paper rounded-xl px-4 py-3.5 mt-3" : ""} data-testid="ob-recipe">
              {picked.needsRepo && (
                <>
                  <label className={label}>Repositório</label>
                  <input
                    className={input}
                    placeholder="dono/repositorio"
                    value={repo}
                    onChange={(e) => setRepo(e.target.value)}
                    data-testid="ob-repo"
                  />
                </>
              )}
              {picked.needsChannel && (
                <>
                  <label className={label}>Publicar no canal</label>
                  <div data-testid="ob-channel">
                    <ChannelPicker
                      value={channel}
                      onChange={setChannel}
                      recent={recent}
                      onPickName={(address, name, workspace) =>
                        setPickedNames((m) => ({ ...m, [address]: { name, workspace } }))
                      }
                    />
                  </div>
                  <p className="text-[11px] text-warnInk mt-1">
                    O bot precisa ser membro do canal — convide o @Mangaba no Slack se ainda não for.
                  </p>
                </>
              )}
              <label className={label}>Quando</label>
              <div className="flex gap-2">
                <div className="flex-1 min-w-0">
                  <SelectMenu
                    ariaLabel="Dia"
                    value={day}
                    options={Object.entries(DAYS).map(([k, v]) => ({ value: k, label: v.label }))}
                    onChange={setDay}
                  />
                </div>
                <input
                  className="w-28 px-3 py-2 rounded-lg border border-line bg-panel text-[13.5px] outline-none focus:border-accent"
                  type="time"
                  aria-label="Hora"
                  value={time}
                  onChange={(e) => setTime(e.target.value)}
                />
              </div>
              {picked.deliver && (
                <>
                  <label className={label}>Entregar em</label>
                  <SelectMenu
                    ariaLabel="Entregar em"
                    value={deliver}
                    options={[
                      { value: "app", label: "No aplicativo" },
                      { value: "slack", label: "DM no Slack (conectar o Slack depois)" },
                    ]}
                    onChange={(v) => setDeliver(v as "app" | "slack")}
                  />
                </>
              )}
              {picked.consent ? (
                <label className="flex items-start gap-2.5 mt-3.5 text-[12.5px] text-muted select-none">
                  <input
                    type="checkbox"
                    className="mt-0.5"
                    checked={consent}
                    onChange={(e) => setConsent(e.target.checked)}
                    data-testid="ob-consent"
                  />
                  <span>
                    Permitir que esta automação publique o resumo em{" "}
                    <b className="text-ink" title={channel || undefined}>
                      {channelLabel || "o canal"}
                      {channelWorkspace ? ` (${channelWorkspace})` : ""}
                    </b>{" "}
                    sem perguntar toda vez. Todo o resto continua perguntando antes.
                  </span>
                </label>
              ) : picked.conns.length > 0 ? (
                <p className="text-[12.5px] text-muted mt-3">
                  Esta automação apenas <b className="text-ink">lê</b> no horário marcado — leitura
                  nunca precisa de aprovação.
                </p>
              ) : null}
            </div>
          )}

          <div className="flex items-center gap-3 mt-4">
            <button
              className="text-[12.5px] text-faint hover:text-muted"
              onClick={() => setPickedKey(null)}
            >
              Cancelar
            </button>
            {/* A silently-disabled primary reads as a bug — always name the missing piece. */}
            {gateHint && (
              <span className="ml-auto text-[11.5px] text-faint" data-testid="ob-create-hint">
                {gateHint}
              </span>
            )}
            <button
              className={
                (gateHint ? "" : "ml-auto ") +
                "px-5 py-2 rounded-full bg-ink text-panel text-[13px] disabled:opacity-40"
              }
              disabled={busy || !allConnected || (picked.needsChannel && !channel)}
              onClick={create}
              data-testid="ob-create"
            >
              {busy ? "Criando…" : "Criar automação"}
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
