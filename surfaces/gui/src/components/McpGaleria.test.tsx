import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import type { McpCatalogItem } from "../api";

// A aba MCP nascia VAZIA e só aceitava JSON digitado à mão — por isso "os servidores não
// apareciam para os usuários": não havia o que aparecer. A galeria é a porta de entrada,
// então ela precisa deixar claro, ANTES do clique, o que dá para usar já.
const ITENS: McpCatalogItem[] = [
  {
    name: "context7",
    titulo: "Context7",
    blurb: "Documentação atualizada de bibliotecas.",
    categoria: "Documentação",
    transport: "http",
    oauth: false,
    runtime: null,
    runtime_pronto: true,
    runtime_titulo: "",
    runtime_url: "",
    runtime_porque: "",
    campos: [],
  },
  {
    name: "notion",
    titulo: "Notion",
    blurb: "Busca e edita páginas do seu Notion.",
    categoria: "Trabalho",
    transport: "http",
    oauth: true,
    runtime: null,
    runtime_pronto: true,
    runtime_titulo: "",
    runtime_url: "",
    runtime_porque: "",
    campos: [],
  },
  {
    name: "filesystem",
    titulo: "Arquivos",
    blurb: "Ler e escrever arquivos numa pasta.",
    categoria: "Local",
    transport: "stdio",
    oauth: false,
    runtime: "node",
    runtime_pronto: false, // máquina sem Node — o caso do usuário Windows
    runtime_titulo: "Node.js",
    runtime_url: "https://nodejs.org",
    runtime_porque: "Servidores npm rodam com o npx.",
    campos: [{ key: "pasta", label: "Pasta liberada" }],
  },
];

vi.mock("../api", async () => {
  const real = await vi.importActual<typeof import("../api")>("../api");
  return {
    ...real,
    getMcpCatalog: vi.fn(async () => ITENS),
    installMcpFromCatalog: vi.fn(async () => ({ ok: true })),
  };
});

import { McpGaleria } from "./ManageTabs";

describe("galeria de servidores MCP", () => {
  // Este projeto não usa cleanup automático (ver ApprovalCard.test.tsx): sem isto
  // o DOM de um teste vaza para o próximo e os itens parecem duplicados.
  afterEach(cleanup);
  beforeEach(() => vi.clearAllMocks());

  it("lista os servidores agrupados por categoria", async () => {
    render(<McpGaleria onInstalado={() => {}} onManual={() => {}} />);
    await waitFor(() => expect(screen.getByText("Context7")).toBeTruthy());
    expect(screen.getByText("Documentação")).toBeTruthy();
    expect(screen.getByText("Trabalho")).toBeTruthy();
    expect(screen.getByText("Notion")).toBeTruthy();
  });

  it("marca o que dá para usar sem login e o que pede conta", async () => {
    render(<McpGaleria onInstalado={() => {}} onManual={() => {}} />);
    await waitFor(() => expect(screen.getByText("sem login")).toBeTruthy());
    expect(screen.getByText("entrar com sua conta")).toBeTruthy();
  });

  it("avisa do runtime ausente ANTES de instalar, com link", async () => {
    // Sem isto o usuário Windows só descobria pelo erro do sistema
    // ("[WinError 2] O sistema não pode encontrar o arquivo especificado").
    render(<McpGaleria onInstalado={() => {}} onManual={() => {}} />);
    await waitFor(() => expect(screen.getByText("Arquivos")).toBeTruthy());
    expect(screen.getByText(/Precisa do Node.js instalado/)).toBeTruthy();
    const link = screen.getByText("Baixar") as HTMLAnchorElement;
    expect(link.getAttribute("href")).toBe("https://nodejs.org");
  });

  it("servidor HTTP não exibe aviso de runtime", async () => {
    render(<McpGaleria onInstalado={() => {}} onManual={() => {}} />);
    await waitFor(() => expect(screen.getByText("Context7")).toBeTruthy());
    expect(screen.queryByText(/Precisa do .* instalado/)).toBeTruthy(); // só o do stdio
    expect(screen.getAllByText(/Precisa do/).length).toBe(1);
  });
});
