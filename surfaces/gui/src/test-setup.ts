// Setup dos testes de unidade.
//
// O jsdom cria `window.localStorage` normalmente, mas o Vitest não o promove ao
// escopo global — então todo componente que lê preferências (barra lateral, tema,
// sessão do login) quebrava com "Cannot read properties of undefined (reading
// 'getItem')" sem que houvesse nada de errado no código. Ligamos os dois aqui.
if (typeof globalThis.localStorage === "undefined") {
  const doWindow = (globalThis as { window?: { localStorage?: Storage } }).window?.localStorage;
  const store: Storage =
    doWindow ??
    (() => {
      // Rede de segurança para o caso de o ambiente não ser jsdom: uma Storage
      // em memória com a mesma superfície, para o teste falhar pelo motivo certo.
      const dados = new Map<string, string>();
      return {
        get length() {
          return dados.size;
        },
        key: (i: number) => [...dados.keys()][i] ?? null,
        getItem: (k: string) => dados.get(k) ?? null,
        setItem: (k: string, v: string) => void dados.set(k, String(v)),
        removeItem: (k: string) => void dados.delete(k),
        clear: () => dados.clear(),
      } as Storage;
    })();

  Object.defineProperty(globalThis, "localStorage", { value: store, configurable: true });
}
