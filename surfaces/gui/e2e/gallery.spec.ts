// Settings ▸ Personas ▸ Gallery: the catalog lives in a screen-sized modal opened
// from the Personas page (link → featured carousel + list → in-modal solo page →
// informed install → Done lands back on Personas). Plus the page-level delete
// affordance for non-builtin personas.
import { expect } from "@playwright/test";
import { test } from "./fixtures";

async function openPersonas(page) {
  // Personas is launch-flagged off by default — these suites cover the flagged-on flows.
  await page.addInitScript(() => localStorage.setItem("ocw.flag.personas", "1"));
  await page.goto("/");
  await page.getByTestId("account-row").click();
  await page.getByRole("button", { name: "Configurações", exact: true }).click();
  await page.getByRole("button", { name: "Personas", exact: true }).click();
  await expect(page.getByTestId("gallery-link")).toBeVisible();
}

async function openGallery(page) {
  await openPersonas(page);
  await page.getByTestId("gallery-link").click();
  await expect(page.getByTestId("gallery-modal")).toBeVisible();
}

test("slow cloud: skeleton shows while the gallery loads, never a blank body", async ({
  page,
}) => {
  // The real gallery is a cloud round-trip (Lambda + Dynamo) that can take seconds;
  // delay the mocked endpoints to assert the skeleton bridges the gap.
  await page.route("**/v1/cloud/status", async (route) => {
    await new Promise((r) => setTimeout(r, 1200));
    await route.fulfill({ json: { ok: true, signed_in: false } });
  });
  await openGallery(page);
  await expect(page.getByTestId("gallery-loading")).toBeVisible();
  await expect(page.getByTestId("gallery-loading")).toContainText("Carregando a galeria");
  // Resolves into the real body (signed-out prompt here) once the cloud answers.
  await expect(page.getByTestId("gallery-signin")).toBeVisible({ timeout: 10_000 });
  await expect(page.getByTestId("gallery-loading")).toHaveCount(0);
});

test("signed out: modal prompts for sign-in, manual install path unaffected", async ({ page }) => {
  await openGallery(page);
  const prompt = page.getByTestId("gallery-signin");
  await expect(prompt).toContainText("exige um\nlogin (gratuito) na nuvem");
  await expect(prompt).toContainText("sempre funciona sem conta");
  await expect(prompt.getByRole("button", { name: "Entrar" })).toBeVisible();
  // Esc closes; the Personas page (with its dir/Git importer) is still there.
  await page.keyboard.press("Escape");
  await expect(page.getByTestId("gallery-modal")).not.toBeVisible();
  await expect(page.getByRole("button", { name: "Instalar", exact: true })).toBeVisible();
});

test("signed in: featured carousel + list; solo page installs informed; Done returns", async ({
  page,
}) => {
  await openGallery(page);
  await page.getByTestId("gallery-signin").getByRole("button", { name: "Entrar" }).click();

  // Featured carousel holds the flagged persona; the list holds both.
  const featured = page.getByTestId("gallery-featured");
  await expect(featured).toBeVisible({ timeout: 10_000 });
  await expect(featured).toContainText("Sales Mangaba");
  await expect(featured).not.toContainText("Recruiter");
  await expect(page.getByTestId("gallery-recruiter")).toContainText("Ver e instalar");
  await expect(page.getByTestId("gallery-team-teaser")).toContainText("chega em breve");

  // Search narrows the list.
  await page.getByPlaceholder("Buscar personas").fill("recruit");
  await expect(page.getByTestId("gallery-sales")).not.toBeVisible();
  await page.getByPlaceholder("Buscar personas").fill("");

  // Solo page: pitch + manifest-derived capabilities BEFORE install.
  await page.getByTestId("gallery-sales").click();
  const detail = page.getByTestId("gallery-detail");
  await expect(detail).toContainText("Walk into every call already knowing the account");
  const caps = page.getByTestId("gallery-capabilities");
  await expect(caps).toContainText("verificado no manifesto");
  await expect(caps).toContainText("files, search, todo");
  await expect(caps).toContainText("hubspot · core");
  await expect(caps).toContainText("read deals and contacts");

  await detail.getByRole("button", { name: "Instalar" }).click();
  await expect(detail).toContainText("disabled until you approve and enable it");

  // Done closes the modal, landing back on the Personas page.
  await detail.getByRole("button", { name: "Done" }).click();
  await expect(page.getByTestId("gallery-modal")).not.toBeVisible();
  await expect(page.getByTestId("gallery-link")).toBeVisible();
});

test("back link returns from the solo page to the catalog", async ({ page }) => {
  await openGallery(page);
  await page.getByTestId("gallery-signin").getByRole("button", { name: "Entrar" }).click();
  await page.getByTestId("gallery-sales").click({ timeout: 10_000 });
  await expect(page.getByTestId("gallery-detail")).toBeVisible();
  await page.getByRole("button", { name: "← Gallery" }).click();
  await expect(page.getByTestId("gallery-cards")).toBeVisible();
});

test("delete: non-builtin personas removable after confirm; built-ins are not", async ({
  page,
}) => {
  await openPersonas(page);
  // Built-ins expose no delete affordance.
  await expect(page.getByTestId("persona-delete-cowork")).toHaveCount(0);
  // Non-builtin: trash → inline confirm → row gone (works signed out).
  await expect(page.getByText("Acme Notes")).toBeVisible();
  await page.getByTestId("persona-delete-acme-notes").click();
  await page.getByTestId("persona-delete-confirm-acme-notes").click();
  await expect(page.getByText("Acme Notes")).not.toBeVisible();
});
