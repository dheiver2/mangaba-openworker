import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { Problema } from "../api";

// A tela é a porta de entrada por PROBLEMA. Um fluxo pronto abre a conversa direto; um
// incompleto leva a pessoa para o ajuste que falta — nunca a deixa num beco sem saída.
const PROBLEMAS: Problema[] = [
  {
    id: "cobrar-atrasados",
    titulo: "Cobrar quem está atrasado",
    dor: "Toda semana alguém puxa a lista de vencidos e escreve e-mail por e-mail.",
    area: "Financeiro",
    tem_pronto: true,
    fluxos: [
      {
        id: "cobranca-planilha",
        titulo: "Da planilha, quando eu pedir",
        resumo: "Você joga a planilha na conversa e ele faz o resto.",
        entrega: "Um arquivo com as mensagens prontas",
        agendado: null,
        modelo: "qualquer",
        aprovacao: true,
        prompt: "Leia a planilha de contas a receber e escreva as cobranças.",
        pronto: true,
        faltam: 0,
        problema_id: "cobrar-atrasados",
        problema: "Cobrar quem está atrasado",
        agente: "negocio",
        pecas: [
          { rotulo: "cobranca-inadimplencia", tipo: "skill", pronta: true, acao: "" },
          { rotulo: "Modelo", tipo: "modelo", pronta: true, acao: "" },
        ],
      },
      {
        id: "cobranca-crm",
        titulo: "Do CRM, toda segunda",
        resumo: "Lê os vencidos no CRM e escreve uma cobrança para cada.",
        entrega: "E-mails em rascunho, agrupados por faixa de atraso",
        agendado: "Segunda-feira, 9h",
        modelo: "qualquer",
        aprovacao: true,
        prompt: "Liste no CRM os títulos vencidos e escreva as cobranças.",
        pronto: false,
        faltam: 1,
        problema_id: "cobrar-atrasados",
        problema: "Cobrar quem está atrasado",
        agente: "cowork",
        pecas: [
          { rotulo: "cobranca-inadimplencia", tipo: "skill", pronta: true, acao: "" },
          { rotulo: "HubSpot", tipo: "mcp", pronta: false, acao: "conectar_mcp" },
          { rotulo: "Modelo", tipo: "modelo", pronta: true, acao: "" },
        ],
      },
    ],
  },
];

vi.mock("../api", async () => {
  const real = await vi.importActual<typeof import("../api")>("../api");
  return { ...real, getFluxos: vi.fn(async () => PROBLEMAS), deleteFluxo: vi.fn(async () => true) };
});

import { FluxosView } from "./FluxosView";

describe("tela de fluxos por problema", () => {
  afterEach(cleanup);
  beforeEach(() => vi.clearAllMocks());

  it("mostra o problema com sua dor em linguagem de negócio", async () => {
    render(<FluxosView onIniciarFluxo={() => {}} onAbrirConfig={() => {}} />);
    await waitFor(() => expect(screen.getByText("Cobrar quem está atrasado")).toBeTruthy());
    expect(screen.getByText(/puxa a lista de vencidos/)).toBeTruthy();
  });

  it("um fluxo pronto abre a conversa com o prompt preenchido", async () => {
    const iniciar = vi.fn();
    render(<FluxosView onIniciarFluxo={iniciar} onAbrirConfig={() => {}} />);
    await waitFor(() => expect(screen.getByText("Da planilha, quando eu pedir")).toBeTruthy());
    fireEvent.click(screen.getByText("Usar agora"));
    // Fluxo local abre na família enxuta "negocio" (menos ferramentas → prefill menor).
    expect(iniciar).toHaveBeenCalledWith(
      "Leia a planilha de contas a receber e escreva as cobranças.",
      "negocio",
    );
  });

  it("um fluxo incompleto leva para o ajuste que falta, não para a conversa", async () => {
    const iniciar = vi.fn();
    const config = vi.fn();
    render(<FluxosView onIniciarFluxo={iniciar} onAbrirConfig={config} />);
    await waitFor(() => expect(screen.getByText("Do CRM, toda segunda")).toBeTruthy());
    // o botão nomeia a ação pendente, não um genérico "configurar"
    fireEvent.click(screen.getByText(/Falta entrar na conta/));
    expect(iniciar).not.toHaveBeenCalled();
    expect(config).toHaveBeenCalledWith("mcp"); // HubSpot pendente → tela de MCP
  });

  it("o resumo diz quantos problemas já dão para usar", async () => {
    render(<FluxosView onIniciarFluxo={() => {}} onAbrirConfig={() => {}} />);
    await waitFor(() => expect(screen.getByText(/1 de 1/)).toBeTruthy());
  });
});

// -- remover: só em "Meus fluxos" ---------------------------------------------------
describe("remover fluxo", () => {
  afterEach(cleanup);
  const MEUS: Problema[] = [
    ...PROBLEMAS,
    {
      id: "meus-fluxos",
      titulo: "Meus fluxos",
      dor: "Procedimentos que você montou aqui, a partir do que pediu.",
      area: "Meus",
      tem_pronto: true,
      fluxos: [
        {
          id: "meu-proprio",
          titulo: "Do meu jeito",
          resumo: "r",
          entrega: "e",
          agendado: null,
          modelo: "qualquer",
          aprovacao: true,
          prompt: "p",
          pronto: true,
          faltam: 0,
          problema_id: "meus-fluxos",
          problema: "Meus fluxos",
          agente: "negocio",
          pecas: [{ rotulo: "Modelo", tipo: "modelo", pronta: true, acao: "" }],
        },
      ],
    },
  ];

  it("mostra o botão de remover só nos fluxos gravados, e apaga após confirmar", async () => {
    const api = await import("../api");
    (api.getFluxos as ReturnType<typeof vi.fn>).mockResolvedValue(MEUS);
    const confirmar = vi.spyOn(window, "confirm").mockReturnValue(true);
    const { FluxosView } = await import("./FluxosView");
    render(<FluxosView onIniciarFluxo={() => {}} onAbrirConfig={() => {}} />);
    await screen.findByTestId("fluxo-meu-proprio");

    // Fluxo de fábrica NÃO tem o botão — o servidor recusaria de qualquer jeito.
    expect(screen.queryByTestId("apagar-cobranca-planilha")).toBeNull();

    fireEvent.click(screen.getByTestId("apagar-meu-proprio"));
    expect(confirmar).toHaveBeenCalled();
    await waitFor(() => expect(api.deleteFluxo).toHaveBeenCalledWith("meu-proprio"));
    confirmar.mockRestore();
  });

  it("não apaga quando a pessoa cancela a confirmação", async () => {
    const api = await import("../api");
    (api.getFluxos as ReturnType<typeof vi.fn>).mockResolvedValue(MEUS);
    (api.deleteFluxo as ReturnType<typeof vi.fn>).mockClear();
    const confirmar = vi.spyOn(window, "confirm").mockReturnValue(false);
    const { FluxosView } = await import("./FluxosView");
    render(<FluxosView onIniciarFluxo={() => {}} onAbrirConfig={() => {}} />);
    await screen.findByTestId("fluxo-meu-proprio");
    fireEvent.click(screen.getByTestId("apagar-meu-proprio"));
    expect(api.deleteFluxo).not.toHaveBeenCalled();
    confirmar.mockRestore();
  });
});
