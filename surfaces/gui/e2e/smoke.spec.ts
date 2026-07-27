import { test, expect } from "./fixtures";

test("app loads with the persona nav and composer", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByText("Mangaba").first()).toBeVisible();
  // New session + Search are the fixed top nav.
  await expect(page.getByRole("button", { name: /Nova sessão/i })).toBeVisible();
  // The persona groups render from /v1/personas.
  await expect(page.getByText("Ops", { exact: true })).toBeVisible();
});
