// @vitest-environment jsdom
// A jornada de entrada: criar senha → entrar → usar a plataforma → sair.
// O gate embrulha o app inteiro, então cada estado errado aqui é um usuário preso
// do lado de fora (ou, pior, uma tela destravada que não deveria estar).
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { LoginGate } from "./LoginGate";
import { PASSCODE_CHANGED, setSessionToken } from "../api";

const PLATAFORMA = <div data-testid="plataforma">a plataforma</div>;

let status: { configured: boolean; authenticated: boolean; locked_for: number };
let respostaLogin: Record<string, unknown>;
let chamadas: { url: string; body: unknown }[];

beforeEach(() => {
  localStorage.clear();
  status = { configured: false, authenticated: false, locked_for: 0 };
  respostaLogin = { ok: true, session: "sessao-1" };
  chamadas = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) => {
      const body = init?.body ? JSON.parse(String(init.body)) : null;
      chamadas.push({ url: String(url), body });
      const responde = (data: unknown) =>
        ({ status: 200, ok: true, json: async () => data, clone: () => ({ json: async () => data }) }) as unknown as Response;
      if (String(url).includes("/v1/auth/status")) return responde(status);
      return responde(respostaLogin);
    }),
  );
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  localStorage.clear();
});

describe("LoginGate — jornada de entrada", () => {
  it("sem senha definida, pede para criar uma antes de abrir a plataforma", async () => {
    render(<LoginGate>{PLATAFORMA}</LoginGate>);

    expect(await screen.findByText("Proteja o seu Mangaba")).toBeTruthy();
    // A plataforma NÃO monta atrás do gate — nada de requisição autenticada antes da hora.
    expect(screen.queryByTestId("plataforma")).toBeNull();
    expect(screen.getByTestId("login-confirm")).toBeTruthy();
  });

  it("criar a senha guarda a sessão e revela a plataforma", async () => {
    render(<LoginGate>{PLATAFORMA}</LoginGate>);
    await screen.findByText("Proteja o seu Mangaba");

    fireEvent.change(screen.getByTestId("login-passcode"), { target: { value: "mangaba123" } });
    fireEvent.change(screen.getByTestId("login-confirm"), { target: { value: "mangaba123" } });
    fireEvent.click(screen.getByTestId("login-submit"));

    expect(await screen.findByTestId("plataforma")).toBeTruthy();
    expect(localStorage.getItem("mangaba:session:v1")).toBe("sessao-1");
    expect(chamadas.some((c) => c.url.includes("/v1/auth/setup"))).toBe(true);
  });

  it("confirmação divergente nem chega ao servidor", async () => {
    render(<LoginGate>{PLATAFORMA}</LoginGate>);
    await screen.findByText("Proteja o seu Mangaba");

    fireEvent.change(screen.getByTestId("login-passcode"), { target: { value: "mangaba123" } });
    fireEvent.change(screen.getByTestId("login-confirm"), { target: { value: "outra-coisa" } });
    fireEvent.click(screen.getByTestId("login-submit"));

    expect(await screen.findByTestId("login-error")).toHaveProperty(
      "textContent",
      "as duas senhas não são iguais",
    );
    expect(chamadas.some((c) => c.url.includes("/v1/auth/setup"))).toBe(false);
    expect(screen.queryByTestId("plataforma")).toBeNull();
  });

  it("com senha já definida, pede para entrar (uma senha só, sem confirmação)", async () => {
    status = { configured: true, authenticated: false, locked_for: 0 };
    render(<LoginGate>{PLATAFORMA}</LoginGate>);

    expect(await screen.findByText("Bem-vindo de volta")).toBeTruthy();
    expect(screen.queryByTestId("login-confirm")).toBeNull();
    expect(screen.queryByTestId("plataforma")).toBeNull();
  });

  it("senha errada mostra o motivo, limpa o campo e mantém o gate fechado", async () => {
    status = { configured: true, authenticated: false, locked_for: 0 };
    respostaLogin = { ok: false, error: "senha incorreta" };
    render(<LoginGate>{PLATAFORMA}</LoginGate>);
    await screen.findByText("Bem-vindo de volta");

    const campo = screen.getByTestId("login-passcode") as HTMLInputElement;
    fireEvent.change(campo, { target: { value: "chute" } });
    fireEvent.click(screen.getByTestId("login-submit"));

    expect(await screen.findByTestId("login-error")).toHaveProperty("textContent", "senha incorreta");
    expect(campo.value).toBe("");
    expect(screen.queryByTestId("plataforma")).toBeNull();
  });

  it("bloqueio por tentativas desabilita o envio e conta o tempo", async () => {
    status = { configured: true, authenticated: false, locked_for: 0 };
    respostaLogin = { ok: false, error: "tentativas demais — aguarde 60s", locked_for: 60 };
    render(<LoginGate>{PLATAFORMA}</LoginGate>);
    await screen.findByText("Bem-vindo de volta");

    fireEvent.change(screen.getByTestId("login-passcode"), { target: { value: "chute" } });
    fireEvent.click(screen.getByTestId("login-submit"));

    await screen.findByText(/Tentativas demais/);
    expect((screen.getByTestId("login-submit") as HTMLButtonElement).disabled).toBe(true);
  });

  it("já autenticado abre direto na plataforma, sem passar pelo login", async () => {
    status = { configured: true, authenticated: true, locked_for: 0 };
    render(<LoginGate>{PLATAFORMA}</LoginGate>);

    expect(await screen.findByTestId("plataforma")).toBeTruthy();
    expect(screen.queryByTestId("login-gate")).toBeNull();
  });

  it("sessão derrubada (logout ou servidor reiniciado) reabre o login", async () => {
    status = { configured: true, authenticated: true, locked_for: 0 };
    setSessionToken("sessao-antiga");
    render(<LoginGate>{PLATAFORMA}</LoginGate>);
    await screen.findByTestId("plataforma");

    // É isto que api.ts faz ao ver 401 com code=passcode_required, e o que o botão
    // Sair dispara: some a sessão, e o gate precisa voltar sozinho.
    status = { configured: true, authenticated: false, locked_for: 0 };
    setSessionToken(null);

    expect(await screen.findByText("Bem-vindo de volta")).toBeTruthy();
    expect(screen.queryByTestId("plataforma")).toBeNull();
  });

  it("token do sidecar trocado (servidor reiniciado) pede recarga em vez de sumir com o app", async () => {
    // 401 aqui não é "sem senha": é o token de lançamento vencido. Mostrar a tela de
    // CRIAR senha nessa hora seria mentir para quem já tem uma.
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => ({
        status: 401,
        ok: false,
        json: async () => ({ error: "token do sidecar do Mangaba ausente ou inválido" }),
        clone: () => ({ json: async () => ({}) }),
      })) as unknown as typeof fetch,
    );
    render(<LoginGate>{PLATAFORMA}</LoginGate>);

    expect(await screen.findByText("O servidor foi reiniciado")).toBeTruthy();
    expect(screen.getByTestId("login-reload")).toBeTruthy();
    expect(screen.queryByTestId("login-passcode")).toBeNull();
    expect(screen.queryByTestId("plataforma")).toBeNull();
  });

  it("servidor fora do ar não prende o usuário numa tela morta", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => { throw new Error("connection refused"); }));
    render(<LoginGate>{PLATAFORMA}</LoginGate>);

    // O App tem a própria espera pelo servidor (boot splash + retry do health), então
    // o gate cede a vez em vez de mostrar um formulário que não teria como funcionar.
    expect(await screen.findByTestId("plataforma")).toBeTruthy();
  });

  it("uma sessão viva não some ao trocar de tela (evento sem perda de sessão)", async () => {
    status = { configured: true, authenticated: true, locked_for: 0 };
    setSessionToken("sessao-viva");
    render(<LoginGate>{PLATAFORMA}</LoginGate>);
    await screen.findByTestId("plataforma");

    window.dispatchEvent(new CustomEvent(PASSCODE_CHANGED));

    await waitFor(() => expect(screen.getByTestId("plataforma")).toBeTruthy());
  });
});
