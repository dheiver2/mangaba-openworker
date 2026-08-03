import { test, expect } from "./fixtures";

// SKILLS-SPEC §9 journey 1 — Settings ▸ Skills as the management home: create through the
// Add-skill menu, edit in place, disable with the amber clean-slate banner, and the
// rich-skill folder chip. Hermetic: every /v1 call lands in fixtures.ts.

const openSkills = async (page: import("@playwright/test").Page) => {
  await page.goto("/");
  await page.getByTestId("account-row").click();
  await page.getByRole("button", { name: "Configurações", exact: true }).click();
  await page.getByRole("button", { name: "Skills", exact: true }).click();
};

test("skills-settings: create via the menu → name-first banner; edit persists", async ({ page }) => {
  await openSkills(page);

  // The seeded rows render; the rich one wears its folder chip; the list is the page
  // (no standing add-surfaces).
  await expect(page.getByText("weekly-report")).toBeVisible();
  await expect(page.getByText("uploaded")).toBeVisible();
  await expect(page.getByTitle("Mostrar pasta")).toContainText("2 arquivos");
  await expect(page.getByText("Iniciar uma conversa")).toHaveCount(0);

  // Add skill ▾ → the three doors, then Write it myself.
  await page.getByRole("button", { name: /Adicionar skill/ }).click();
  await expect(page.getByText("Importar um arquivo")).toBeVisible();
  await expect(page.getByText("Criar com o Mangaba")).toBeVisible();
  await page.getByText("Escrever eu mesmo").click();

  await page.getByLabel("Nome").fill("greet-warmly");
  await page.getByLabel("Descrição").fill("Greets people warmly");
  await page.getByLabel("Instruções").fill("Always greet warmly.");
  await page.getByRole("button", { name: "Salvar skill" }).click();

  // Name-first teal confirmation (§7) + the new row.
  const status = page.getByRole("status");
  await expect(status).toContainText("greet-warmly");
  await expect(status).toContainText("já pode usá-la em todas as conversas");
  await expect(page.getByText("Greets people warmly")).toBeVisible();

  // Edit: pencil prefills, name locked, save PATCHes through to the re-fetched list.
  await page.getByTitle("Editar").first().click();
  const name = page.getByLabel("Nome");
  await expect(name).toBeDisabled();
  await page.getByLabel("Descrição").fill("Monday status report, sharper");
  await page.getByRole("button", { name: "Salvar skill" }).click();
  await expect(page.getByText("Monday status report, sharper")).toBeVisible();
});

test("skills-settings: disable → amber everywhere/clean-slate banner; delete is two-step", async ({ page }) => {
  await openSkills(page);

  await page.getByLabel("weekly-report ativada").click();
  const status = page.getByRole("status");
  await expect(status).toContainText("weekly-report");
  await expect(status).toContainText("desativada em todo lugar");
  await expect(status).toContainText("inicie uma nova para começar do zero");

  // Two-step delete: arm, confirm, row gone, banner names the skill.
  await page.getByLabel("Excluir html-to-markdown").click();
  await expect(page.getByText("html-to-markdown")).toBeVisible(); // armed ≠ deleted
  await page.getByText("Confirmar exclusão").click();
  await expect(page.getByText("html-to-markdown")).toHaveCount(1); // only the banner remains
  await expect(page.getByRole("status")).toContainText("removida");
});
