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
  await form.getByPlaceholder("ООО ...").fill("ООО E2E-Тест");
  await form.getByPlaceholder("Минск").fill("Минск");
  await form.getByPlaceholder("лист, арматура...").fill("лист");
  await form.getByPlaceholder("+375 ...").fill("+375290000000");
  await form.getByRole("button", { name: "Принять", exact: true }).click();

  // лид появился в инбоксе
  await expect(page.getByText("ООО E2E-Тест").first()).toBeVisible();

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
});
