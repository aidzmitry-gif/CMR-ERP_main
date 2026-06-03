import { expect, test } from "@playwright/test";

// Сквозная навигация: панель владельца и переход в ERP-модуль через сайдбар.
test("навигация: панель владельца → ERP-модуль", async ({ page }) => {
  await page.goto("/crm/owner");
  await expect(page.getByRole("heading", { name: "Панель владельца", exact: true })).toBeVisible();

  await page.getByRole("link", { name: "Закупки" }).click();
  await expect(page).toHaveURL(/\/erp\/procurement/);
  await expect(page.getByRole("heading", { name: "Закупки", exact: true })).toBeVisible();
});
