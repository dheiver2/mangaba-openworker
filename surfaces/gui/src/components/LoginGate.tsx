import { useEffect, useRef, useState } from "react";
import {
  getAuthStatus,
  loginPasscode,
  setupPasscode,
  PASSCODE_CHANGED,
  sessionToken,
  type AuthStatus,
} from "../api";
import { BrandLockup } from "./Brand";

// O gate humano da GUI (ver mangaba/passcode.py): o token do sidecar prova que a chamada
// saiu desta máquina, e esta tela prova que é a PESSOA certa nela. Três estados:
//   · carregando  — perguntando ao servidor se já existe senha
//   · criar       — primeira execução: define a senha (e já entra)
//   · entrar      — senha existe: pede e destrava
// Nada do app monta antes de destravar — o gate embrulha a árvore inteira, então nenhuma
// requisição autenticada sai antes da hora.

type Phase = "loading" | "setup" | "login" | "stale";

export function LoginGate({ children }: { children: React.ReactNode }) {
  const [status, setStatus] = useState<AuthStatus | null>(null);
  const [unlocked, setUnlocked] = useState(false);

  const refresh = () =>
    getAuthStatus()
      .then((s) => {
        setStatus(s);
        if (!s.ok) {
          setUnlocked(false);
          return;
        }
        // Sem senha ainda, o gate NÃO deixa passar: mostra a tela de criação. O
        // servidor aceitaria a chamada (o app precisa abrir na primeira execução para
        // a senha poder ser criada), mas quem entra pela GUI define a senha primeiro —
        // senão o gate seria opcional na prática e ninguém acharia a tela.
        setUnlocked(s.authenticated);
      })
      .catch(() => {
        // Servidor ainda subindo: não trave o usuário numa tela morta — o App tem
        // sua própria espera pelo health, e o gate reavalia quando a sessão mudar.
        setStatus(null);
        setUnlocked(true);
      });

  useEffect(() => {
    refresh();
    // Uma sessão derrubada (expirou, servidor reiniciou, logout) reabre o gate.
    const onChange = () => {
      if (!sessionToken()) refresh();
    };
    window.addEventListener(PASSCODE_CHANGED, onChange);
    return () => window.removeEventListener(PASSCODE_CHANGED, onChange);
  }, []);

  if (unlocked) return <>{children}</>;

  const phase: Phase = !status
    ? "loading"
    : !status.ok
      ? "stale"
      : status.configured
        ? "login"
        : "setup";
  return (
    <PasscodeScreen
      phase={phase}
      lockedFor={status?.locked_for || 0}
      onUnlocked={() => setUnlocked(true)}
    />
  );
}

function PasscodeScreen({
  phase,
  lockedFor,
  onUnlocked,
}: {
  phase: Phase;
  lockedFor: number;
  onUnlocked: () => void;
}) {
  const [passcode, setPasscode] = useState("");
  const [confirm, setConfirm] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [locked, setLocked] = useState(lockedFor);
  const inputRef = useRef<HTMLInputElement | null>(null);

  useEffect(() => setLocked(lockedFor), [lockedFor]);
  useEffect(() => {
    if (locked <= 0) return;
    const t = setInterval(() => setLocked((s) => Math.max(0, s - 1)), 1000);
    return () => clearInterval(t);
  }, [locked]);
  useEffect(() => {
    inputRef.current?.focus();
  }, [phase]);

  const creating = phase === "setup";
  const desatualizado = phase === "stale";
  const canSubmit =
    !busy &&
    locked <= 0 &&
    passcode.length > 0 &&
    (!creating || confirm.length > 0);

  const submit = async () => {
    if (!canSubmit) return;
    if (creating && passcode !== confirm) {
      setError("as duas senhas não são iguais");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const out = creating
        ? await setupPasscode(passcode)
        : await loginPasscode(passcode);
      if (out.ok) {
        onUnlocked();
        return;
      }
      setError(out.error || "não foi possível entrar");
      const wait = (out as { locked_for?: number }).locked_for;
      if (wait) setLocked(wait);
      setPasscode("");
      setConfirm("");
      inputRef.current?.focus();
    } catch {
      setError("o servidor do Mangaba não respondeu — ele está rodando?");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="login-gate" data-testid="login-gate">
      <div className="login-card">
        {/* A logomarca é o cabeçalho da tela: marca + wordmark centralizados, com o
            título logo abaixo — sem repetir a palavra "Mangaba" em texto. */}
        <div className="login-brand">
          <BrandLockup size={54} />
          <span className="beta-tag">BETA</span>
        </div>
        <h1 className="login-title">
          {phase === "loading"
            ? "Carregando…"
            : desatualizado
              ? "O servidor foi reiniciado"
              : creating
                ? "Proteja o seu Mangaba"
                : "Bem-vindo de volta"}
        </h1>
        <p className="login-lede">
          {phase === "loading"
            ? "Conectando ao servidor local…"
            : desatualizado
              ? "O Mangaba subiu de novo e gerou novas credenciais de acesso. Recarregue esta página para reconectar."
              : creating
                ? "Crie uma senha para esta máquina. Ela protege suas conversas, arquivos e conectores de quem tiver acesso físico a este computador."
                : "Digite sua senha para destravar as sessões, automações e conectores."}
        </p>

        {desatualizado && (
          <button
            className="login-submit"
            onClick={() => window.location.reload()}
            data-testid="login-reload"
          >
            Recarregar
          </button>
        )}

        {phase !== "loading" && !desatualizado && (
          <>
            <label className="login-field">
              <span>Senha</span>
              <input
                ref={inputRef}
                type="password"
                autoComplete={creating ? "new-password" : "current-password"}
                value={passcode}
                disabled={busy || locked > 0}
                placeholder={creating ? "pelo menos 6 caracteres" : "sua senha"}
                onChange={(e) => setPasscode(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && (creating ? undefined : submit())}
                data-testid="login-passcode"
              />
            </label>

            {creating && (
              <label className="login-field">
                <span>Confirme a senha</span>
                <input
                  type="password"
                  autoComplete="new-password"
                  value={confirm}
                  disabled={busy}
                  placeholder="digite de novo"
                  onChange={(e) => setConfirm(e.target.value)}
                  onKeyDown={(e) => e.key === "Enter" && submit()}
                  data-testid="login-confirm"
                />
              </label>
            )}

            {error && (
              <div className="login-error" role="alert" data-testid="login-error">
                {error}
              </div>
            )}
            {locked > 0 && (
              <div className="login-error" role="status">
                Tentativas demais — tente de novo em {locked}s.
              </div>
            )}

            <button
              className="login-submit"
              onClick={submit}
              disabled={!canSubmit}
              data-testid="login-submit"
            >
              {busy
                ? creating
                  ? "Criando…"
                  : "Entrando…"
                : creating
                  ? "Criar senha e entrar"
                  : "Entrar"}
            </button>

            <p className="login-foot">
              {creating
                ? "A senha é guardada só neste computador, como hash — nunca em texto puro, e nunca sai daqui."
                : "Esqueceu a senha? Apague ~/.config/mangaba/passcode.json e o Mangaba pede uma nova."}
            </p>
          </>
        )}
      </div>
    </div>
  );
}
