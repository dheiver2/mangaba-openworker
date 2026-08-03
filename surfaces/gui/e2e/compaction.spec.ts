// OPE-27 — GUI da auto-compactação: os dois overrides do card de Configurações + o
// pin do modelo resumidor fazem POST, e o divisor "contexto compactado" renderiza
// inline no meio da sessão (dirigido pelo evento `compacted` roteirizado nos
// fixtures) sem tocar na transcrição.
import { expect } from "@playwright/test";
import { test } from "./fixtures";

test("Configurações: card de Compactação de contexto edita limiar, teto e modelo resumidor", async ({
  page,
}) => {
  await page.goto("/");
  await page.getByTestId("account-row").click();
  await page.getByRole("button", { name: "Configurações", exact: true }).click();
  await page.getByRole("button", { name: "Modelos", exact: true }).click();

  const card = page.getByTestId("compaction-card");
  await expect(card).toBeVisible();
  await expect(card.getByText("Compactação de contexto")).toBeVisible();

  // Defaults render when the backend doesn't send the fields (older-backend robustness).
  await expect(card.getByTestId("compaction-threshold")).toHaveValue("80");
  await expect(card.getByTestId("compaction-cap")).toHaveValue("250000");
  await expect(card.getByTestId("compaction-model")).toHaveValue("");

  // Threshold edits POST as a fraction, clamped to 10–95%.
  const [req] = await Promise.all([
    page.waitForRequest(
      (r) => r.url().endsWith("/v1/settings/compaction") && r.method() === "POST",
    ),
    card.getByTestId("compaction-threshold").fill("70"),
  ]);
  expect(req.postDataJSON()).toEqual({ compaction_threshold_pct: 0.7 });

  const [req2] = await Promise.all([
    page.waitForRequest(
      (r) => r.url().endsWith("/v1/settings/compaction") && r.method() === "POST",
    ),
    card.getByTestId("compaction-cap").fill("100000"),
  ]);
  expect(req2.postDataJSON()).toEqual({ compaction_cap_tokens: 100000 });

  // Summarizer pin: the picker offers the session-default plus the configured models.
  const [req3] = await Promise.all([
    page.waitForRequest(
      (r) => r.url().endsWith("/v1/settings/compaction") && r.method() === "POST",
    ),
    card.getByTestId("compaction-model").selectOption("gpt-4o-mini"),
  ]);
  expect(req3.postDataJSON()).toEqual({ compaction_model: "gpt-4o-mini" });
});

test("o divisor de compactação renderiza no meio da sessão e a transcrição fica intacta", async ({
  page,
}) => {
  await page.goto("/");
  await page.getByText("Draft the launch note").first().click();
  const box = page.getByPlaceholder(/Peça ao Mangaba/);

  // An earlier exchange that must survive the compaction marker (transcript intact).
  await box.fill("remember the launch date");
  await box.press("Enter");
  await expect(page.getByText("Echo: remember the launch date").first()).toBeVisible({
    timeout: 10_000,
  });

  await box.fill("compact the context");
  await box.press("Enter");
  // The transient signal shows while the summarizer runs, then yields to the divider.
  await expect(page.getByText("Compactando contexto…").first()).toBeVisible({
    timeout: 10_000,
  });
  await expect(
    page.getByText("Contexto compactado — os turnos mais antigos foram resumidos").first(),
  ).toBeVisible({ timeout: 10_000 });
  await expect(page.getByText("Compactando contexto…")).toHaveCount(0);
  await expect(
    page.getByText("Continuando de onde parei.").first(),
  ).toBeVisible();
  // Outbound-only: everything before the divider is still on screen.
  await expect(page.getByText("Echo: remember the launch date").first()).toBeVisible();
});
