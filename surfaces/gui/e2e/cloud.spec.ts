// Cloud sign-in (§26: the sidebar account row is the sign-in home) + managed one-click
// connectors. Product invariant under test: manual token setup is always present; managed
// one-click is an ADDITION that appears only when signed in.
import { expect } from "@playwright/test";
import { test } from "./fixtures";

async function openConnectors(page) {
  await page.goto("/");
  await page.getByTestId("account-row").click();
  await page.getByTestId("account-menu").getByRole("button", { name: "Conectores", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Conectores" })).toBeVisible();
}

async function signIn(page) {
  await page.getByTestId("account-row").click();
  await page.getByTestId("account-sign-in").click();
  await expect(page.getByTestId("account-row")).toContainText("Rohit", { timeout: 10_000 });
}

test("signed out: the account row is the sign-in home; managed connector still connects manually", async ({
  page,
}) => {
  await page.goto("/");
  const row = page.getByTestId("account-row");
  await expect(row).toContainText("Não conectado");

  // The menu leads with the sign-in CTA and always lists Inbox + Connectors.
  await row.click();
  const menu = page.getByTestId("account-menu");
  await expect(menu).toContainText("conexões com um clique exigem o Mangaba Cloud");
  await expect(menu.getByTestId("account-sign-in")).toBeVisible();
  await expect(menu.getByRole("button", { name: "Caixa de entrada" })).toBeVisible();
  await menu.getByRole("button", { name: "Conectores", exact: true }).click();

  // The managed-capable connector's add-modal shows the hint + manual fields, no
  // one-click button while signed out.
  await page.getByTestId("connector-gmail").getByRole("button", { name: "Conectar" }).click();
  const modal = page.getByTestId("add-connection-modal");
  await expect(modal.getByTestId("managed-connect")).toContainText("Entrar no Mangaba Cloud");
  await expect(modal.locator("input[type=password]")).toBeVisible(); // manual field rendered
  await expect(modal.getByRole("button", { name: /one click/i })).toHaveCount(0);
});

test("signed in: account row shows the name; one-click appears; sign out from the menu", async ({
  page,
}) => {
  await openConnectors(page);
  await signIn(page);

  await page.getByTestId("connector-gmail").getByRole("button", { name: "Conectar", exact: true }).click();
  const modal = page.getByTestId("add-connection-modal");
  await expect(modal.getByRole("button", { name: /Conectar Gmail com um clique/i })).toBeVisible();
  // the manual path must still be offered alongside
  await expect(modal.getByTestId("managed-connect")).toContainText("ou conecte manualmente");
  await page.keyboard.press("Escape");

  // The menu header carries the email; Sign out flips the row back.
  await page.getByTestId("account-row").click();
  const menu = page.getByTestId("account-menu");
  await expect(menu).toContainText("rohit@mangaba.ai");
  await menu.getByRole("button", { name: "Sair" }).click();
  await page.getByTestId("account-row").click(); // reopen → status refetch
  await expect(page.getByTestId("account-row")).toContainText("Não conectado");
});

test("telemetry/Privacy card is gone from Settings (owner ask 2026-07-22), signed in or out", async ({
  page,
}) => {
  await page.goto("/");
  await page.getByTestId("account-row").click();
  await page.getByTestId("account-menu").getByRole("button", { name: "Configurações" }).click();
  await expect(page.getByRole("heading", { name: "Geral" })).toBeVisible();
  await expect(page.getByTestId("telemetry-toggle")).toHaveCount(0);
  await expect(page.getByText("Privacy", { exact: true })).toHaveCount(0);

  await signIn(page);
  await page.getByTestId("account-row").click();
  await page.getByTestId("account-menu").getByRole("button", { name: "Configurações" }).click();
  await expect(page.getByTestId("telemetry-toggle")).toHaveCount(0);
  await expect(page.getByText("Privacy", { exact: true })).toHaveCount(0);
});
