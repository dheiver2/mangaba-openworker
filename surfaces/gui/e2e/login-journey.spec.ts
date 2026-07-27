// A jornada de entrada, ponta a ponta, contra a UI real: gate → login → plataforma.
// Os demais specs entram já destravados (a fixture responde authenticated: true);
// aqui sobrescrevemos /v1/auth/* para percorrer cada estado do portão.
import { expect } from "@playwright/test";
import { test } from "./fixtures";

type Estado = { configured: boolean; authenticated: boolean; locked_for?: number };

/** Assume o controle das rotas de auth (as fixtures já responderam antes desta). */
async function comAuth(page: any, estado: Estado, resposta: Record<string, unknown> = { ok: true, session: "s-1" }) {
  const enviados: any[] = [];
  await page.route("**/v1/auth/**", async (route: any) => {
    const url = route.request().url();
    const json = (body: unknown) =>
      route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(body) });
    if (url.includes("/status")) return json({ locked_for: 0, ...estado });
    enviados.push({ url, body: route.request().postDataJSON?.() ?? null });
    if (resposta.ok) {
      estado.authenticated = true; // o próximo /status já reflete a sessão criada
    }
    return json(resposta);
  });
  return enviados;
}

test("primeira execução: o gate pede para criar a senha antes de abrir a plataforma", async ({ page }) => {
  await comAuth(page, { configured: false, authenticated: false });
  await page.goto("/");

  await expect(page.getByTestId("login-gate")).toBeVisible();
  await expect(page.getByText("Proteja o seu Mangaba")).toBeVisible();
  await expect(page.getByTestId("login-confirm")).toBeVisible();
  // A plataforma não pode estar montada atrás do gate.
  await expect(page.getByRole("button", { name: /Nova sessão/i })).toHaveCount(0);
});

test("criar a senha entra direto na plataforma", async ({ page }) => {
  const enviados = await comAuth(page, { configured: false, authenticated: false });
  await page.goto("/");

  await page.getByTestId("login-passcode").fill("mangaba-teste");
  await page.getByTestId("login-confirm").fill("mangaba-teste");
  await page.getByTestId("login-submit").click();

  await expect(page.getByTestId("login-gate")).toHaveCount(0);
  await expect(page.getByRole("button", { name: /Nova sessão/i })).toBeVisible();
  expect(enviados.some((e) => e.url.includes("/setup"))).toBe(true);
});

test("a confirmação divergente para no navegador, sem chamar o servidor", async ({ page }) => {
  const enviados = await comAuth(page, { configured: false, authenticated: false });
  await page.goto("/");

  await page.getByTestId("login-passcode").fill("mangaba-teste");
  await page.getByTestId("login-confirm").fill("outra-coisa");
  await page.getByTestId("login-submit").click();

  await expect(page.getByTestId("login-error")).toHaveText("as duas senhas não são iguais");
  expect(enviados.some((e) => e.url.includes("/setup"))).toBe(false);
});

test("com senha definida: entrar destrava a plataforma", async ({ page }) => {
  await comAuth(page, { configured: true, authenticated: false });
  await page.goto("/");

  await expect(page.getByText("Bem-vindo de volta")).toBeVisible();
  await expect(page.getByTestId("login-confirm")).toHaveCount(0); // só uma senha, sem confirmar

  await page.getByTestId("login-passcode").fill("mangaba-teste");
  await page.getByTestId("login-submit").click();

  await expect(page.getByRole("button", { name: /Nova sessão/i })).toBeVisible();
  await expect(page.getByPlaceholder(/Peça ao Mangaba/)).toBeVisible();
});

test("senha errada explica o motivo e mantém o gate fechado", async ({ page }) => {
  await comAuth(page, { configured: true, authenticated: false }, { ok: false, error: "senha incorreta" });
  await page.goto("/");

  await page.getByTestId("login-passcode").fill("chute");
  await page.getByTestId("login-submit").click();

  await expect(page.getByTestId("login-error")).toHaveText("senha incorreta");
  await expect(page.getByTestId("login-gate")).toBeVisible();
  await expect(page.getByTestId("login-passcode")).toHaveValue("");
});

test("tentativas demais bloqueiam o envio pelo tempo informado", async ({ page }) => {
  await comAuth(
    page,
    { configured: true, authenticated: false },
    { ok: false, error: "tentativas demais — aguarde 60s", locked_for: 60 },
  );
  await page.goto("/");

  await page.getByTestId("login-passcode").fill("chute");
  await page.getByTestId("login-submit").click();

  await expect(page.getByText(/Tentativas demais/)).toBeVisible();
  await expect(page.getByTestId("login-submit")).toBeDisabled();
});

test("quem já entrou volta direto para a plataforma, sem ver o login", async ({ page }) => {
  await comAuth(page, { configured: true, authenticated: true });
  await page.goto("/");

  await expect(page.getByRole("button", { name: /Nova sessão/i })).toBeVisible();
  await expect(page.getByTestId("login-gate")).toHaveCount(0);
});

test("a logomarca oficial abre a tela de entrada", async ({ page }) => {
  await comAuth(page, { configured: true, authenticated: false });
  await page.goto("/");

  const marca = page.getByTestId("login-gate").locator("img");
  await expect(marca.first()).toBeVisible();
  // Manga + wordmark: a arte é a mesma da splash e da landing.
  expect(await marca.count()).toBeGreaterThanOrEqual(2);
});
