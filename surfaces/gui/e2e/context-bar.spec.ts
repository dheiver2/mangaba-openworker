import { test, expect } from "./fixtures";

// Porte parcial do upstream usage-chip.spec.ts (25dc283): o chip de uso do composer
// (OPE-42) ainda não existe neste fork, então cobrimos só a parte portável — o toggle
// "barra da janela de contexto" em Configurações ▸ Geral, desligado por padrão, que
// persiste via POST /v1/settings/context-bar.
test("Configurações: o toggle da barra de contexto persiste no servidor", async ({ page }) => {
  await page.goto("/");
  await page.getByTestId("account-row").click();
  await page.getByRole("button", { name: "Configurações", exact: true }).click();

  const toggle = page.getByTestId("context-bar-toggle");
  await expect(toggle).toBeVisible();
  // Padrão (pedido do dono, 2026-07-30): a barra fica DESLIGADA.
  await expect(toggle).not.toBeChecked();

  const [req] = await Promise.all([
    page.waitForRequest(
      (r) => r.url().endsWith("/v1/settings/context-bar") && r.method() === "POST",
    ),
    toggle.check(),
  ]);
  expect(req.postDataJSON()).toEqual({ context_bar: true });

  // Recarrega para o app reler as configurações: o toggle continua marcado.
  await page.goto("/");
  await page.getByTestId("account-row").click();
  await page.getByRole("button", { name: "Configurações", exact: true }).click();
  await expect(page.getByTestId("context-bar-toggle")).toBeChecked();
});
