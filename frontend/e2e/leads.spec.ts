import { expect, test } from "@playwright/test";

// Критический путь воронки: лид пришёл → AI-квалификация → распределение на
// менеджера → конвертация в сделку. Сквозной сценарий через реальный UI + API.
test("лид: приём → AI-квалификация → распределение → конвертация в сделку", async ({ page }) => {
  await page.goto("/crm/leads");
  await expect(page.getByRole("heading", { name: "Приём лидов" })).toBeVisible();
  // Закрываем preview-drawer если он автоматически открылся для существующего лида
  // (e2e.db может содержать ЛИД-1 из seed, его preview перекрывает кнопку «Принять лид»)
  await page.keyboard.press("Escape");

  // 1) приём нового лида через форму
  await page.getByRole("button", { name: /Принять лид/ }).click();
  const form = page.locator("form.shadow-pop");
  await expect(form).toBeVisible();
  const company = `ООО E2E-Тест ${Date.now()}`;
  await form.getByPlaceholder("ООО ...").fill(company);
  await form.getByPlaceholder("Минск").fill("Минск");
  await form.getByPlaceholder("лист, арматура...").fill("лист");
  await form.getByPlaceholder("+375 ...").fill("+375290000000");
  const intake = page.waitForResponse((r) => /\/api\/leads\/?$/.test(r.url()) && r.request().method() === "POST");
  await form.getByRole("button", { name: "Принять", exact: true }).click();
  const intakeResponse = await intake;
  expect(intakeResponse.status()).toBe(201);
  const lead = await intakeResponse.json();

  // лид появился в инбоксе
  await expect(page.getByText(company).first()).toBeVisible();

  // 2) квалификация: появляется балл и вердикт «целевой» (+ AI-обоснование)
  const drawer = page.getByRole("dialog", { name: /Превью лида ЛИД-/ });
  await expect(drawer).toBeVisible();
  await drawer.getByRole("button", { name: "Квалифицировать", exact: true }).click();
  await expect(drawer.getByText(/целевой/).first()).toBeVisible();

  // 3) распределение: назначается менеджер
  await drawer.getByRole("button", { name: "Распределить", exact: true }).click();
  await expect(drawer.getByRole("button", { name: "✓ Распределён" })).toBeVisible();

  // 4) конвертация в сделку → появляется ссылка на созданную сделку
  await drawer.getByRole("button", { name: "В сделку", exact: true }).click();
  await expect(drawer.getByRole("link", { name: /Открыть сделку/ })).toBeVisible();
  const link = drawer.getByRole("link", { name: /Открыть сделку/ });
  const href = await link.getAttribute("href");
  const readback = await page.request.get(`/api/leads/${lead.id}`);
  expect(readback.ok()).toBe(true);
  const converted = await readback.json();
  expect(converted.status).toBe("converted");
  expect(converted.deal_id).toBeGreaterThan(0);
  expect(href).toBe(`/crm/deals/${converted.deal_id}`);
  const repeated = await page.request.post(`/api/leads/${lead.id}/convert`);
  expect(repeated.status()).toBe(409);
  expect((await repeated.json()).detail).toBe("Лид уже сконвертирован в сделку");
  expect((await (await page.request.get(`/api/leads/${lead.id}`)).json()).deal_id).toBe(converted.deal_id);
  await page.goto(href!);
  await page.reload();
  await expect(page.getByText(company).first()).toBeVisible();
});
