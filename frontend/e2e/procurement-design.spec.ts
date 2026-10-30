import { expect, test } from "@playwright/test";

test("procurement keeps navigation on the left and renders the approved board design", async ({ page }, testInfo) => {
  test.setTimeout(120_000);
  const created = await page.request.post("/api/accounting/organizations", { data: { name: "Учебная организация · дизайн закупок", unp: `987${Date.now().toString().slice(-6)}` } });
  expect(created.ok(), await created.text()).toBeTruthy();
  const organization = await created.json();
  await page.goto("/erp/settings");
  await page.getByLabel("Юрлицо для всей платформы").selectOption(String(organization.id));
  await page.getByRole("button", { name: "Сохранить для всей платформы", exact: true }).click();
  await expect(page.getByRole("status").filter({ hasText: "Сохранено для всей платформы" })).toBeVisible();

  const context = await page.request.get(`/api/procurement/organizations/${organization.id}/request-plan-context`);
  expect(context.ok(), await context.text()).toBeTruthy();
  const identity = await context.json();
  expect(identity.can_manage).toBe(true);
  const request = await page.request.post(`/api/procurement/organizations/${organization.id}/requests`, {
    headers: { "X-Expected-Principal": identity.principal },
    data: { request_key: crypto.randomUUID(), document: { supplier: "Учебный поставщик", item: "Учебная партия аккумуляторов · SKU-219", qty: 24, amount: "1850.00", due_date: null }, ownership_evidence: "Синтетический сценарий оформления закупок" },
  });
  expect(request.ok(), await request.text()).toBeTruthy();
  const receipt = await request.json();

  await page.setViewportSize({ width: 1600, height: 1000 });
  await page.goto("/erp/procurement");
  await expect(page.getByRole("link", { name: receipt.number, exact: true })).toBeVisible();
  const left = page.getByRole("complementary").first();
  await left.getByRole("button", { name: "Раскрыть меню", exact: true }).click();
  await expect(left.getByRole("group", { name: "Разделы закупок" })).toBeVisible();
  await expect(page.getByRole("navigation", { name: "Разделы закупок" })).toHaveCount(0);
  await expect(page.getByRole("combobox")).toHaveCount(0);
  await expect(page.getByLabel("Канбан закупок").getByRole("region")).toHaveCount(9);
  await page.screenshot({ path: testInfo.outputPath("procurement-desktop.png"), fullPage: true });
  await testInfo.attach("procurement-desktop", { path: testInfo.outputPath("procurement-desktop.png"), contentType: "image/png" });

  await page.getByRole("textbox", { name: "Поиск по закупкам, поставщикам, SKU" }).fill("SKU-219");
  await page.getByRole("button", { name: "Список", exact: true }).click();
  await expect(page.getByLabel("Список закупок")).toContainText("Учебная партия аккумуляторов");
  await left.getByRole("link", { name: "План закупок", exact: true }).click();
  await expect(page).toHaveURL(/\/erp\/procurement\/planning$/);
  await expect(left.getByRole("link", { name: "План закупок", exact: true })).toHaveAttribute("aria-current", "page");
  await expect(left.getByRole("link", { name: "Обзор и воронка", exact: true })).toBeVisible();

  await page.goto("/erp/procurement");
  await page.setViewportSize({ width: 390, height: 844 });
  await left.getByRole("button", { name: "Свернуть меню", exact: true }).click();
  await expect(page.getByRole("link", { name: receipt.number, exact: true })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await page.screenshot({ path: testInfo.outputPath("procurement-mobile.png"), fullPage: true });
  await testInfo.attach("procurement-mobile", { path: testInfo.outputPath("procurement-mobile.png"), contentType: "image/png" });
  await page.getByLabel("Канбан закупок", { exact: true }).scrollIntoViewIfNeeded();
  await page.screenshot({ path: testInfo.outputPath("procurement-mobile-board.png"), fullPage: true });
  await testInfo.attach("procurement-mobile-board", { path: testInfo.outputPath("procurement-mobile-board.png"), contentType: "image/png" });
});
