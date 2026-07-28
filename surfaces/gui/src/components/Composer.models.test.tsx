// O que acontece quando a lista de modelos NÃO chega.
//
// A busca de modelos engole o erro (`.catch(() => {})` no App), então a interface
// não tem como saber que falhou: o chip ficava em "Carregando modelos…" para
// sempre. Um usuário no Windows passou exatamente por isso — janela aberta,
// nenhuma informação, nenhuma saída. Estes testes fixam o comportamento novo:
// passado o prazo, o chip admite a falha e oferece tentar de novo.
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { Composer } from "./Composer";

const props = (extra: Partial<Parameters<typeof Composer>[0]> = {}) => ({
  mode: "interactive",
  model: "gpt-5.6-sol",
  running: false,
  connected: true,
  onSend: vi.fn(),
  onInterrupt: vi.fn(),
  onModeChange: vi.fn(),
  onModelChange: vi.fn(),
  ...extra,
});

beforeEach(() => {
  vi.useFakeTimers();
});

afterEach(() => {
  vi.useRealTimers();
  cleanup();
});

describe("Composer — lista de modelos indisponível", () => {
  it("começa carregando e não acusa falha de imediato", () => {
    render(<Composer {...props({ models: [] })} />);
    expect(screen.queryByTestId("models-loading")).toBeTruthy();
    expect(screen.queryByTestId("models-failed")).toBeNull();
  });

  it("passado o prazo, admite a falha em vez de girar para sempre", () => {
    render(<Composer {...props({ models: [] })} />);
    act(() => vi.advanceTimersByTime(12_000));
    expect(screen.queryByTestId("models-loading")).toBeNull();
    const falhou = screen.getByTestId("models-failed");
    // A mensagem tem de dizer que o problema é o servidor local, senão o usuário
    // não sabe se a culpa é da internet, da chave do provedor ou do app.
    expect(falhou.textContent || "").toMatch(/servidor/i);
  });

  it("clicar em tentar de novo dispara a rebusca e volta a carregar", () => {
    const onRetryModels = vi.fn();
    render(<Composer {...props({ models: [], onRetryModels })} />);
    act(() => vi.advanceTimersByTime(12_000));

    fireEvent.click(screen.getByTestId("models-failed"));
    expect(onRetryModels).toHaveBeenCalledTimes(1);
    // Volta ao estado de carregando: o usuário precisa ver que algo aconteceu.
    expect(screen.queryByTestId("models-loading")).toBeTruthy();
  });

  it("modelos chegando durante a espera cancelam o aviso de falha", () => {
    const { rerender } = render(<Composer {...props({ models: [] })} />);
    act(() => vi.advanceTimersByTime(8_000));
    rerender(<Composer {...props({ models: ["gpt-5.6-sol"] })} />);
    act(() => vi.advanceTimersByTime(20_000));
    expect(screen.queryByTestId("models-failed")).toBeNull();
  });
});
