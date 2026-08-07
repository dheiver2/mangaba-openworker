import { Component, type ErrorInfo, type ReactNode } from "react";

// Sem isto, qualquer erro de render deixa a janela COMPLETAMENTE em branco — sem texto, sem
// botão, sem pista do que houve. Já aconteceu: um item do Inbox com quick-replies em formato
// inesperado tornou o app impossível de abrir, e o único caminho de volta era editar o JSON
// de estado à mão. Uma tela de falha legível transforma isso num aborrecimento recuperável.
export class ErrorBoundary extends Component<
  { children: ReactNode },
  { erro: Error | null }
> {
  state: { erro: Error | null } = { erro: null };

  static getDerivedStateFromError(erro: Error) {
    return { erro };
  }

  componentDidCatch(erro: Error, info: ErrorInfo) {
    console.error("Falha ao renderizar a interface:", erro, info.componentStack);
  }

  render() {
    const { erro } = this.state;
    if (!erro) return this.props.children;
    return (
      <div className="flex h-screen w-screen items-center justify-center p-8 select-text">
        <div className="max-w-lg space-y-3">
          <div className="text-lg font-semibold">A interface falhou ao carregar</div>
          <p className="text-sm opacity-80">
            O Mangaba continua rodando — só esta tela quebrou. Tentar de novo costuma
            resolver; se persistir, envie a mensagem abaixo junto ao relato do problema.
          </p>
          <pre className="max-h-56 overflow-auto rounded border border-current/20 p-3 text-xs whitespace-pre-wrap">
            {String(erro?.message || erro)}
          </pre>
          <div className="flex gap-2">
            <button
              className="rounded border border-current/30 px-3 py-1.5 text-sm"
              onClick={() => this.setState({ erro: null })}
            >
              Tentar novamente
            </button>
            <button
              className="rounded border border-current/30 px-3 py-1.5 text-sm"
              onClick={() => window.location.reload()}
            >
              Recarregar
            </button>
          </div>
        </div>
      </div>
    );
  }
}
