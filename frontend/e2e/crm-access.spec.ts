import { expect, test } from "@playwright/test";

test("директор: самостоятельный CRM-клиент без сделки, потерянный ответ и повтор", async ({ page }) => {
  await page.goto("/crm/clients");
  await expect(page.getByRole("status").filter({ hasText: "Найдено:" })).toBeVisible();
  await page.getByRole("button", { name: "Новый клиент", exact: true }).click();
  const form = page.getByRole("form", { name: "Новый клиент CRM" });
  const name = `E2E-CRM-CLIENT-${Date.now()}`;
  await form.getByLabel("Название клиента", { exact: true }).fill(name);
  await form.getByRole("combobox", { name: "Ответственный", exact: true }).selectOption("2901");
  await form.screenshot({ path: test.info().outputPath("client-form.png") });
  let lost = true;
  let clientId = 0;
  const keys: string[] = [];
  await page.route("**/api/sales/clients", async (route) => {
    if (route.request().method() !== "POST") return route.continue();
    keys.push(route.request().postDataJSON().request_key);
    if (!lost) return route.continue();
    lost = false;
    const response = await route.fetch();
    expect(response.status()).toBe(201);
    clientId = (await response.json()).id;
    await route.abort("failed");
  });
  await form.getByRole("button", { name: "Создать клиента", exact: true }).click();
  await expect(form.getByRole("alert")).toBeVisible();
  await form.getByRole("button", { name: "Создать клиента", exact: true }).click();
  await expect(form).toHaveCount(0);
  expect(keys).toHaveLength(2);
  expect(keys[0]).toBeTruthy();
  expect(keys[0]).toBe(keys[1]);
  await expect(page.getByRole("row").filter({ hasText: name })).toHaveCount(1);
  await page.reload();
  await page.getByRole("searchbox").fill(name);
  await page.getByRole("button", { name: "Найти", exact: true }).click();
  await expect(page.getByRole("row").filter({ hasText: name })).toContainText("Создан в CRM");
  await page.getByRole("table", { name: "Клиенты", exact: true }).screenshot({ path: test.info().outputPath("client-saved.png") });
  const read = await page.request.get(`/api/sales/clients/${clientId}`);
  expect(read.ok()).toBe(true);
  expect(await read.json()).toMatchObject({ id: clientId, name, owner_id: 2901, counterparty_id: null, source: "crm" });
  const listed = await page.request.get(`/api/sales/clients?q=${name}`);
  const data = await listed.json();
  expect(data.total).toBe(1);
  expect(data.rows[0].deal_id).toBeNull();
});

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
