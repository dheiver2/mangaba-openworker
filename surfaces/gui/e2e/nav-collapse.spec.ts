// Left-nav polish (§20): collapse (⌘B / brand button → reveal button docks it back) and the
// RECENT-header group/filter popover (Group by Persona↔Chronological, Filter by mangaba).
import { expect } from "@playwright/test";
import { test } from "./fixtures";

test("collapse hides the sidebar and reclaims the width; reveal button docks it back", async ({
  page,
}) => {
  await page.goto("/");
  const app = page.locator(".app");
  await expect(page.locator(".sidebar")).toBeVisible();

  // Collapse via the brand button.
  await page.getByRole("button", { name: "Recolher barra lateral" }).click();
  await expect(app).toHaveClass(/nav-collapsed/);
  // The floating reveal affordance appears; clicking it docks the nav back.
  const reveal = page.getByRole("button", { name: "Mostrar barra lateral" });
  await expect(reveal).toBeVisible();
  await reveal.click();
  await expect(app).not.toHaveClass(/nav-collapsed/);
});

test("⌘B toggles the sidebar collapse", async ({ page }) => {
  await page.goto("/");
  const app = page.locator(".app");
  await page.keyboard.press("Meta+b");
  await expect(app).toHaveClass(/nav-collapsed/);
  await page.keyboard.press("Meta+b");
  await expect(app).not.toHaveClass(/nav-collapsed/);
});

test("RECENT header group/filter popover: switch grouping + see mangaba filters", async ({
  page,
}) => {
  await page.goto("/");
  const header = page.getByTestId("recent-header");
  await expect(header).toContainText("Recentes");

  await header.getByRole("button", { name: "Agrupar e filtrar conversas" }).click();
  const menu = page.getByTestId("group-filter-menu");
  await expect(menu).toContainText("Agrupar por");
  await expect(menu).toContainText("Filtrar por persona");

  // Switch to Chronological → the persona accordion collapses into a flat list (the "Mangaba"
  // persona group header is no longer a row; sessions list directly).
  await menu.getByText("Cronológica").click();
  await expect(menu.getByText("Cronológica").locator("xpath=..")).toContainText("✓");

  // Filter-by-mangaba checkboxes are present (none checked by default → all shown).
  await expect(menu).toContainText("Nenhuma marcada mostra todas.");
});
