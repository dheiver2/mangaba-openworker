import { useEffect, useMemo, useState } from "react";
import { getFluxos, type Fluxo, type Problema } from "../api";
import { Icon } from "./Icon";

// A porta de entrada por PROBLEMA, não por mecanismo. A pessoa escolhe a dor do dia a dia
// e, dentro dela, o fluxo que se encaixa na pilha que ela tem — o mesmo problema resolvido
// do CRM, da planilha ou por WhatsApp são caminhos diferentes, não um só. O estado de cada
// peça vem VERIFICADO do backend: "pronto" nunca é só "cadastrado".

const TIPO_ICONE: Record<string, string> = {
  skill: "sparkle",
  mcp: "plug",
  conector: "plug",
  automação: "clock",
  modelo: "wrench",
};

// Uma frase por ação pendente — o que a pessoa faz para destravar a peça. Nomeada pelo que
// ela reconhece ("entrar no HubSpot"), não pelo mecanismo ("autenticar OAuth").
function textoAcao(peca: { acao: string; rotulo: string }): string {
  switch (peca.acao) {
    case "instalar_skill":
      return "instalar a skill";
    case "ativar_skill":
      return "ativar a skill (está desligada)";
    case "conectar_mcp":
      return "entrar na conta";
    case "instalar_mcp":
      return "adicionar o servidor";
    case "conectar_conector":
      return "conectar";
    case "criar_automacao":
      return "agendar (opcional — roda sob demanda sem isto)";
    case "configurar_modelo":
      return "escolher um modelo";
    case "baixar_modelo_local":
      return "baixar o modelo local";
    default:
      return "";
  }
}

function SeloModelo({ modelo }: { modelo: Fluxo["modelo"] }) {
  if (modelo === "local")
    return (
      <span className="fluxo-tag fluxo-tag-local" title="Roda sem nuvem — os dados não saem da máquina">
        100% local
      </span>
    );
  if (modelo === "forte")
    return (
      <span className="fluxo-tag" title="Pede um modelo de ponta; o resultado degrada num modelo pequeno">
        modelo forte
      </span>
    );
  return null;
}

function CartaoFluxo({
  fluxo,
  onUsar,
}: {
  fluxo: Fluxo;
  onUsar: (f: Fluxo) => void;
}) {
  const faltando = fluxo.pecas.filter((p) => !p.pronta && p.acao);
  return (
    <div className="fluxo-card" data-testid={`fluxo-${fluxo.id}`}>
      <div className="fluxo-card-head">
        <div className="fluxo-card-titulo">
          {fluxo.titulo}
          <SeloModelo modelo={fluxo.modelo} />
        </div>
        {fluxo.pronto ? (
          <span className="fluxo-selo fluxo-selo-ok">pronto</span>
        ) : (
          <span className="fluxo-selo fluxo-selo-falta">
            falta {fluxo.faltam}
          </span>
        )}
      </div>

      <p className="fluxo-resumo">{fluxo.resumo}</p>

      <div className="fluxo-entrega">
        <Icon name="diamond" size={12} className="shrink-0 mt-[3px]" />
        <span>{fluxo.entrega}</span>
      </div>

      <div className="fluxo-pecas">
        {fluxo.pecas.map((p, i) => (
          <span
            key={i}
            className={"fluxo-peca " + (p.pronta ? "ok" : "falta")}
            title={p.pronta ? "pronto" : textoAcao(p)}
          >
            <Icon name={(TIPO_ICONE[p.tipo] as never) || "sparkle"} size={11} />
            {p.rotulo}
          </span>
        ))}
      </div>

      {fluxo.agendado && (
        <div className="fluxo-agenda">
          <Icon name="clock" size={12} /> {fluxo.agendado}
          {fluxo.aprovacao && <span className="fluxo-aprova">· pede aprovação antes de enviar</span>}
        </div>
      )}

      <div className="fluxo-acao">
        {fluxo.pronto ? (
          <button className="fluxo-btn fluxo-btn-forte" onClick={() => onUsar(fluxo)}>
            Usar agora
          </button>
        ) : (
          <button className="fluxo-btn" onClick={() => onUsar(fluxo)}>
            {faltando.length === 1
              ? `Falta ${textoAcao(faltando[0])}`
              : `Falta ${faltando.length} passos`}
          </button>
        )}
      </div>
    </div>
  );
}

export function FluxosView({
  onIniciarFluxo,
  onAbrirConfig,
}: {
  // Um fluxo pronto abre uma conversa com o prompt já preenchido (mesmo contrato do
  // startNewSession + prefill das skills). Um incompleto leva para o ajuste que falta.
  // `agente` é a família enxuta que o fluxo local inicia ("negocio") ou "cowork" para os
  // que usam conector/MCP — quem chama decide a persona da nova sessão a partir disso.
  onIniciarFluxo: (prompt: string, agente: string) => void;
  onAbrirConfig: (destino: "modelos" | "skills" | "mcp" | "conectores" | "automacoes") => void;
}) {
  const [problemas, setProblemas] = useState<Problema[] | null>(null);
  const [erro, setErro] = useState(false);
  const [area, setArea] = useState<string>("Todas");

  useEffect(() => {
    getFluxos()
      .then(setProblemas)
      .catch(() => setErro(true));
  }, []);

  const areas = useMemo(() => {
    if (!problemas) return [];
    return ["Todas", ...Array.from(new Set(problemas.map((p) => p.area)))];
  }, [problemas]);

  const visiveis = useMemo(() => {
    if (!problemas) return [];
    return area === "Todas" ? problemas : problemas.filter((p) => p.area === area);
  }, [problemas, area]);

  const usar = (f: Fluxo) => {
    if (f.pronto) {
      onIniciarFluxo(f.prompt, f.agente);
      return;
    }
    // Leva para o primeiro ajuste pendente — o destino depende do tipo da peça.
    const falta = f.pecas.find((p) => !p.pronta && p.acao);
    const destino =
      falta?.tipo === "skill"
        ? "skills"
        : falta?.tipo === "mcp"
          ? "mcp"
          : falta?.tipo === "conector"
            ? "conectores"
            : falta?.tipo === "modelo"
              ? "modelos"
              : "automacoes";
    onAbrirConfig(destino as never);
  };

  if (erro)
    return (
      <div className="fluxos-wrap">
        <div className="fluxos-vazio">
          Não consegui carregar os fluxos. O servidor local pode estar reiniciando —
          tente de novo em instantes.
        </div>
      </div>
    );

  if (!problemas)
    return <div className="fluxos-wrap"><div className="fluxos-vazio">Carregando…</div></div>;

  const prontos = problemas.filter((p) => p.tem_pronto).length;

  return (
    <div className="fluxos-wrap">
      <header className="fluxos-topo">
        <h1 className="fluxos-titulo">O que você quer resolver?</h1>
        <p className="fluxos-sub">
          Escolha o problema do dia a dia e o caminho que combina com o que você já tem.{" "}
          <strong>{prontos} de {problemas.length}</strong> já dá para usar agora, sem configurar nada.
        </p>
      </header>

      <div className="fluxos-filtros" role="tablist">
        {areas.map((a) => (
          <button
            key={a}
            role="tab"
            aria-selected={area === a}
            className={"fluxos-filtro " + (area === a ? "ativo" : "")}
            onClick={() => setArea(a)}
          >
            {a}
          </button>
        ))}
      </div>

      <div className="fluxos-lista">
        {visiveis.map((p) => (
          <section key={p.id} className="problema" data-testid={`problema-${p.id}`}>
            <div className="problema-cab">
              <div>
                <h2 className="problema-titulo">
                  {p.titulo}
                  {p.tem_pronto && <span className="problema-ok" title="Tem um caminho pronto">●</span>}
                </h2>
                <p className="problema-dor">{p.dor}</p>
              </div>
              <span className="problema-area">{p.area}</span>
            </div>
            <div className="problema-fluxos">
              {p.fluxos.map((f) => (
                <CartaoFluxo key={f.id} fluxo={f} onUsar={usar} />
              ))}
            </div>
          </section>
        ))}
      </div>
    </div>
  );
}
