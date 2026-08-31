import { expect, test } from "@playwright/test";

// Критический путь карточки: создать сделку → открыть → сформировать счёт → запись в 1С.
// Самодостаточно (на пустой доске CI карточек нет — создаём свою).
test("карточка сделки: формирование счёта → запись в 1С", async ({ page }) => {
  await page.goto("/crm/deals");
  // Кнопка SSR-видима до подключения React onClick; ждём завершения гидрации.
  await expect(page.getByTestId("deals-client-ready")).toBeVisible();

  await page.getByRole("button", { name: /Создать сделку/ }).click();
  const form = page.locator("form.shadow-pop");
  await expect(form).toBeVisible();
  await form.getByPlaceholder("CRM-2024-0200").fill(`E2E-DOC-${Date.now()}`);
  await form.getByPlaceholder("ООО ...").fill("ООО E2E-Документ");
  await form.getByPlaceholder("Поставка ...").fill("Поставка для E2E");
  await form.getByRole("button", { name: "Создать" }).click();

  // открыть карточку созданной сделки (double-click: single-click открывает drawer-preview,
  // double-click — router.push на полную карточку /crm/deals/[id] с вкладкой Документы)
  await page.getByText("ООО E2E-Документ").first().dblclick();
  await expect(page.getByText("Документы")).toBeVisible();

  // счёт пишется в 1С сразу → статус «Записан в 1С»
  await page.getByRole("button", { name: /Сформировать/ }).click();
  await expect(page.getByText(/Записан в 1С/).first()).toBeVisible();
});
