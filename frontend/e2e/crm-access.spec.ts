import { expect, test } from "@playwright/test";

test("ограниченная роль: настоящий dev-вход и отказ прямого CRM API", async ({ page, context }) => {
  await context.clearCookies();
  await page.goto("/login");
  await page.getByLabel("Сотрудник").selectOption("vedernikova");
  await page.getByRole("button", { name: "Войти", exact: true }).click();
  await expect(page).not.toHaveURL(/\/login/);
  await expect(page.getByRole("link", { name: "Клиенты", exact: true })).toHaveCount(0);
  for (const path of ["/api/sales/clients", "/api/sales/contacts", "/api/sales/deals"]) {
    const response = await page.request.get(path);
    expect(response.status()).toBe(403);
  }
});

test("клиенты: HTTP error не становится пустотой, повтор восстанавливает список", async ({ page }) => {
  let fail = true;
  await page.route("**/api/sales/clients?**", (route) => fail
    ? route.fulfill({ status: 500, contentType: "application/json", body: '{"detail":"synthetic failure"}' })
    : route.continue());
  await page.goto("/crm/clients");
  const loadError = page.getByRole("alert").filter({ hasText: "Не удалось загрузить список" });
  await expect(loadError).toBeVisible();
  await expect(page.getByText("Нет доступных записей на этой странице.", { exact: true })).toHaveCount(0);
  fail = false;
  await page.getByRole("button", { name: "Повторить", exact: true }).click();
  await expect(page.getByText("Контроль E2E — синтетический покупатель", { exact: true })).toBeVisible();
  await expect(loadError).toHaveCount(0);
});
