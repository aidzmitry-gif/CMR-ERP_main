import { expect, test } from "@playwright/test";
import { configureInstallationCompany } from "./installation-company";

// Сквозная навигация: панель владельца и переход в ERP-модуль через сайдбар.
test("навигация: панель владельца → ERP-модули и вложенные страницы", async ({ page }) => {
  test.setTimeout(90_000);
  const created = await page.request.post("/api/accounting/organizations", { data: {
    name: "Synthetic navigation seller", unp: `986${Date.now().toString().slice(-6)}`,
  } });
  expect(created.ok(), await created.text()).toBeTruthy();
  await configureInstallationCompany(page, (await created.json()).id);
  await page.goto("/crm/owner");
  await expect(page.getByRole("heading", { name: "Панель владельца", exact: true })).toBeVisible();

  const sidebar = page.getByRole("complementary").first();
  await sidebar.getByRole("button", { name: "Раскрыть меню", exact: true }).click();
  await sidebar.getByRole("link", { name: "Закупки", exact: true }).click();
  await expect(page).toHaveURL(/\/erp\/procurement/);
  await expect(page.getByRole("heading", { name: "Воронка закупок", exact: true })).toBeVisible();
  await expect(sidebar.getByRole("group", { name: "Разделы закупок" })).toBeVisible();
  await expect(sidebar.getByRole("link", { name: "Обзор и воронка", exact: true })).toHaveAttribute("aria-current", "page");
  await expect(page.getByRole("navigation", { name: "Разделы закупок" })).toHaveCount(0);

  for (const [path, group, activeLink] of [
    ["/erp/wms/inventory", "Склад: разделы", "Инвентаризация"],
    ["/erp/production/norms", "Производство: разделы", "Нормы и нормативы"],
    ["/erp/hr/worktime", "HR: разделы", "Учёт времени"],
  ]) {
    await test.step(path, async () => {
      await page.goto(path);
      await expect(sidebar.getByRole("group", { name: group, exact: true })).toBeVisible();
      await expect(sidebar.getByRole("group")).toHaveCount(1);
      await expect(sidebar.getByRole("link", { name: activeLink, exact: true })).toHaveAttribute("aria-current", "page");
      await expect(sidebar.getByRole("group", { name: "Разделы закупок" })).toHaveCount(0);
    });
  }
});
