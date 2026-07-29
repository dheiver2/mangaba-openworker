import { test, expect } from "./fixtures";

// As duas variantes de plataforma da MESMA build: o shell Rust injeta __OCW_PLATFORM__
// antes do SPA carregar, e todo texto por plataforma (deviceLabel, shortcutLabel) deriva
// disso. Simular cada valor aqui é exatamente o que o app real faz — é o único jeito de
// exercitar o lado Windows da UI sem uma máquina Windows (o .exe é cross-compilado e não
// roda no macOS). Cobre as regressões que já aconteceram de verdade: "⌘" fixo nas dicas
// (v0.1.12) e "fica neste Mac" para usuários Windows (v0.1.14).

test("windows: o card de aprovação fala 'computador', nunca 'Mac'", async ({ page }) => {
  await page.addInitScript(() => {
    (window as any).__OCW_PLATFORM__ = "windows";
  });
  await page.goto("/");
  // Provoca uma aprovação de comando (o agente fake do harness dispara o fluxo).
  await page.getByPlaceholder(/Peça ao Mangaba/).fill("please run a tool");
  await page.getByRole("button", { name: "Enviar" }).click();
  await expect(page.getByText(/fica neste computador/).last()).toBeVisible();
  await expect(page.getByText(/fica neste Mac/)).toHaveCount(0);
});

test("macos: o mesmo card fala 'Mac'", async ({ page }) => {
  // O fixture já fixa "macos" por padrão (paridade com a injeção do shell).
  await page.goto("/");
  await page.getByPlaceholder(/Peça ao Mangaba/).fill("please run a tool");
  await page.getByRole("button", { name: "Enviar" }).click();
  await expect(page.getByText(/fica neste Mac/).last()).toBeVisible();
  await expect(page.getByText(/fica neste computador/)).toHaveCount(0);
});

test("windows: dicas de atalho usam Ctrl, não ⌘", async ({ page }) => {
  await page.addInitScript(() => {
    (window as any).__OCW_PLATFORM__ = "windows";
  });
  await page.goto("/");
  // O title do toggle da sidebar carrega o atalho formatado por plataforma.
  const withShortcut = page.locator("[title*='Ctrl+B'], [aria-label*='Ctrl+B']").first();
  await expect(withShortcut).toBeAttached();
  await expect(page.locator("[title*='⌘B'], [aria-label*='⌘B']")).toHaveCount(0);
});

test("macos: dicas de atalho usam ⌘", async ({ page }) => {
  await page.goto("/");
  const withShortcut = page.locator("[title*='⌘B'], [aria-label*='⌘B']").first();
  await expect(withShortcut).toBeAttached();
});
