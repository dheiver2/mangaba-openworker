// O que acontece quando a lista de PROVEDORES não chega.
//
// Mesmo bug do "Carregando modelos…" (ver Composer.models.test.tsx), só que na tela de
// Configurações ▸ Modelos: `getProviders()` engolia o erro em `.catch(() => {})`, então
// um sidecar que não sobe a tempo deixava a galeria de provedores vazia para sempre, sem
// nenhuma explicação — usuários recém-instalados relataram exatamente isso. Estes testes
// fixam o comportamento novo: passado o prazo, a tela admite a falha e oferece retry.
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { renderHook } from "@testing-library/react";
import { useProviderSetup, ProviderCards } from "./ProviderSetup";

vi.mock("../api", () => ({
  getProviders: vi.fn(() => new Promise(() => {})), // never resolves — simulates a dead sidecar
  removeProvider: vi.fn(),
  setProvider: vi.fn(),
  verifyProvider: vi.fn(),
  getLocalEngine: vi.fn(() => Promise.resolve({ state: "absent", installed: false, running: false, binary: null })),
  installLocalEngine: vi.fn(() => Promise.resolve({ ok: true })),
}));

beforeEach(() => {
  vi.useFakeTimers();
});

afterEach(() => {
  vi.useRealTimers();
  cleanup();
});

describe("ProviderSetup — lista de provedores indisponível", () => {
  it("começa carregando e não acusa falha de imediato", () => {
    const { result } = renderHook(() => useProviderSetup());
    render(<ProviderCards ps={result.current} tp="set" />);
    expect(screen.queryByTestId("set-providers-loading")).toBeTruthy();
    expect(screen.queryByTestId("set-providers-failed")).toBeNull();
  });

  it("passado o prazo, admite a falha em vez de mostrar galeria vazia sem explicação", () => {
    const { result, rerender } = renderHook(() => useProviderSetup());
    act(() => vi.advanceTimersByTime(12_000));
    rerender();
    render(<ProviderCards ps={result.current} tp="set" />);
    expect(screen.queryByTestId("set-providers-loading")).toBeNull();
    const falhou = screen.getByTestId("set-providers-failed");
    // Tem de apontar o servidor local, senão o usuário não sabe se o problema é a
    // chave do provedor, a internet, ou o app.
    expect(falhou.textContent || "").toMatch(/servidor/i);
  });

  it("clicar em tentar de novo rechama o sidecar e volta a carregar", async () => {
    const { result, rerender } = renderHook(() => useProviderSetup());
    act(() => vi.advanceTimersByTime(12_000));
    rerender();
    render(<ProviderCards ps={result.current} tp="set" />);

    fireEvent.click(screen.getByTestId("set-providers-failed"));
    rerender();
    render(<ProviderCards ps={result.current} tp="set" />);
    expect(screen.queryAllByTestId("set-providers-loading").length).toBeGreaterThan(0);
  });
});
