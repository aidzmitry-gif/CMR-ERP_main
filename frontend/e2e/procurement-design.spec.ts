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

  // A read failure never exposes backend details; recovery is an explicit user action.
  const planSources = `**/api/procurement/organizations/${organization.id}/owned-sources?*`;
  let planRecovery = false;
  let planReads = 0;
  await page.route(planSources, async route => {
    expect(route.request().method()).toBe("GET");
    planReads += 1;
    if (planRecovery) await route.fulfill({ json: { organization_id: organization.id, items: [], next_after_id: null } });
    else await route.fulfill({ status: 500, contentType: "text/plain", body: "PRIVATE_PLAN_BACKEND_DETAILS" });
  });
  await page.reload();
  const planAlert = page.getByRole("alert").filter({ hasText: "Не удалось выполнить запрос" });
  await expect(planAlert).toContainText("HTTP 500");
  await expect(planAlert).not.toContainText("PRIVATE_PLAN_BACKEND_DETAILS");
  await expect(page.getByText("На загруженной странице заявок нет.", { exact: true })).toHaveCount(0);
  await page.screenshot({ path: testInfo.outputPath("plan-safe-error.png"), fullPage: true });
  await testInfo.attach("plan-safe-error", { path: testInfo.outputPath("plan-safe-error.png"), contentType: "image/png" });
  planRecovery = true;
  await page.getByRole("button", { name: "Обновить документы", exact: true }).click();
  await expect(planAlert).toHaveCount(0);
  await expect(page.getByText("На загруженной странице заявок нет.", { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "Создать заявку", exact: true })).toBeEnabled();
  console.log("PLAN_SAFE_READS", JSON.stringify({ reads: planReads, manualRefreshClicks: 1, commandWrites: 0 }));
  await page.unroute(planSources);

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

  // RFQ presentation uses explicit synthetic GET fixtures; no create/bid/award commands.
  const rfqUrl = `**/api/procurement/organizations/${organization.id}/rfq?*`;
  const supplierUrl = `**/api/procurement/organizations/${organization.id}/supplier-options`;
  const historyUrl = `**/api/procurement/organizations/${organization.id}/rfq/265/history`;
  await page.route(rfqUrl, route => route.fulfill({ json: { organization_id: organization.id, next_after_id: null, items: [{
    id: 265, number: "RFQ-ДИЗАЙН-265", organization_id: organization.id, request_key: "00000000-0000-4000-8000-000000000265",
    item: "Аккумуляторы для учебной партии", sku_code: "SKU-219", qty: 24, request_id: null, status: "open", due_date: null, best_bid_id: 1,
    bids: [
      { id: 1, rfq_id: 265, supplier_id: 1, price_byn: 1850.25, lead_time_days: 7, incoterms: "DAP Минск", note: "", is_winner: false },
      { id: 2, rfq_id: 265, supplier_id: 2, price_byn: 1920, lead_time_days: null, incoterms: "", note: "", is_winner: false },
    ],
  }] } }));
  await page.route(supplierUrl, route => route.fulfill({ json: { organization_id: organization.id, items: [
    { id: 1, name: "Учебный поставщик Север", unp: "000000001" }, { id: 2, name: "Учебный поставщик Восток", unp: "000000002" },
  ] } }));
  await page.route(historyUrl, route => route.fulfill({ json: { organization_id: organization.id, rfq_id: 265, items: [] } }));
  await page.goto("/erp/procurement/rfq");
  await expect(page.getByRole("cell", { name: "Учебный поставщик Север", exact: true })).toBeVisible();
  await page.getByPlaceholder("Цена, BYN", { exact: true }).fill("1800.25");
  for (const view of [
    { name: "rfq-desktop", width: 1440, height: 1000, dark: false },
    { name: "rfq-mobile", width: 390, height: 844, dark: false },
    { name: "rfq-dark", width: 1440, height: 1000, dark: true },
  ]) {
    await page.setViewportSize({ width: view.width, height: view.height });
    if (view.dark) await page.getByRole("button", { name: "Включить тёмную тему", exact: true }).click();
    await page.getByRole("region", { name: "Сравнение предложений", exact: true }).scrollIntoViewIfNeeded();
    await page.screenshot({ path: testInfo.outputPath(`${view.name}.png`), fullPage: true });
    await testInfo.attach(view.name, { path: testInfo.outputPath(`${view.name}.png`), contentType: "image/png" });
    await testInfo.attach(`${view.name}-geometry`, { body: JSON.stringify(await page.evaluate(() => ({ viewport: innerWidth, documentWidth: document.documentElement.scrollWidth, tableWidth: document.querySelector("table")?.getBoundingClientRect().width }))), contentType: "application/json" });
    console.log("RFQ_GEOMETRY", view.name, JSON.stringify(await page.evaluate(() => ({ viewport: innerWidth, documentWidth: document.documentElement.scrollWidth, scrollX, overflowing: [...document.querySelectorAll("body *")].filter(el => el.getBoundingClientRect().right > innerWidth + 1).slice(0, 16).map(el => ({ tag: el.tagName, role: el.getAttribute("role"), width: el.getBoundingClientRect().width, right: el.getBoundingClientRect().right, overflow: getComputedStyle(el).overflowX })) }))));
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    await expect(page.getByRole("columnheader")).toHaveCount(5);
    await expect(page.getByRole("textbox", { name: "Цена, BYN", exact: true })).toHaveValue("1800.25");
    await expect(page.locator("label").filter({ has: page.getByRole("textbox", { name: "Цена, BYN", exact: true }) }).locator("span")).toBeVisible();
    if (view.width === 390) {
      const comparison = page.getByRole("region", { name: "Сравнение предложений", exact: true });
      await expect(comparison).toHaveCount(1);
      {
        await comparison.focus();
        await expect(comparison).toBeFocused();
        await page.keyboard.press("ArrowRight");
        await expect.poll(() => comparison.evaluate(element => element.scrollLeft)).toBeGreaterThan(0);
      }
      await page.screenshot({ path: testInfo.outputPath("rfq-mobile-table.png"), fullPage: true });
      await testInfo.attach("rfq-mobile-table", { path: testInfo.outputPath("rfq-mobile-table.png"), contentType: "image/png" });
    }
  }
  await page.unroute(rfqUrl);
  await page.unroute(supplierUrl);
  await page.unroute(historyUrl);
  await page.getByRole("button", { name: "Включить светлую тему", exact: true }).click();

  // A failed supplier refresh is explicit; cached rows survive and recovery is manual.
  let supplierRecovery = false;
  let supplierFailedReads = 0;
  let supplierSuccessfulReads = 0;
  const suppliersUrl = "**/api/procurement/suppliers";
  const supplierFixture = [
    { id: 2681, counterparty_id: 2681, name: "Учебный поставщик Север", unp: "000002681", country: "Беларусь", flag: "", contact_person: "", phone: "", email: "", payment_terms: "По факту", lead_time_days: 7, incoterms: "DAP", status: "active", notes: "" },
    { id: 2682, counterparty_id: 2682, name: "Учебный поставщик Восток", unp: "000002682", country: "Беларусь", flag: "", contact_person: "", phone: "", email: "", payment_terms: "", lead_time_days: null, incoterms: "", status: "blocked", notes: "" },
  ];
  await page.route(suppliersUrl, async route => {
    expect(route.request().method()).toBe("GET");
    if (supplierRecovery) {
      supplierSuccessfulReads += 1;
      await route.fulfill({ json: supplierFixture });
    } else {
      supplierFailedReads += 1;
      await route.fulfill({ status: 503, json: { detail: "PRIVATE_SUPPLIER_INTERNAL_DETAILS" } });
    }
  });
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.goto("/erp/procurement/suppliers");
  const supplierAlert = page.getByRole("alert").filter({ hasText: "Не удалось загрузить поставщиков" });
  await expect(supplierAlert).toBeVisible();
  await expect(supplierAlert).not.toContainText("PRIVATE_SUPPLIER_INTERNAL_DETAILS");
  await page.screenshot({ path: testInfo.outputPath("suppliers-load-error.png"), fullPage: true });
  await testInfo.attach("suppliers-load-error", { path: testInfo.outputPath("suppliers-load-error.png"), contentType: "image/png" });
  supplierRecovery = true;
  await page.getByRole("button", { name: "Обновить", exact: true }).click();
  await expect(page.getByText("Учебный поставщик Север", { exact: true })).toBeVisible();
  await expect(page.getByText("Учебный поставщик Восток", { exact: true })).toBeVisible();
  await expect(supplierAlert).toHaveCount(0);
  await page.screenshot({ path: testInfo.outputPath("suppliers-recovered.png"), fullPage: true });
  await testInfo.attach("suppliers-recovered", { path: testInfo.outputPath("suppliers-recovered.png"), contentType: "image/png" });
  supplierRecovery = false;
  await page.getByRole("button", { name: "Обновить", exact: true }).click();
  await expect(supplierAlert).toContainText("Показаны ранее загруженные данные");
  await expect(page.getByText("Учебный поставщик Север", { exact: true })).toBeVisible();
  await expect(page.getByText("Учебный поставщик Восток", { exact: true })).toBeVisible();
  await page.screenshot({ path: testInfo.outputPath("suppliers-stale-data.png"), fullPage: true });
  await testInfo.attach("suppliers-stale-data", { path: testInfo.outputPath("suppliers-stale-data.png"), contentType: "image/png" });
  await page.setViewportSize({ width: 390, height: 844 });
  await supplierAlert.scrollIntoViewIfNeeded();
  await page.screenshot({ path: testInfo.outputPath("suppliers-mobile-error.png"), fullPage: true });
  await testInfo.attach("suppliers-mobile-error", { path: testInfo.outputPath("suppliers-mobile-error.png"), contentType: "image/png" });
  const supplierCapture = async (name: string) => {
    await page.screenshot({ path: testInfo.outputPath(`${name}.png`), fullPage: true });
    await testInfo.attach(name, { path: testInfo.outputPath(`${name}.png`), contentType: "image/png" });
  };
  const addSupplier = page.getByRole("button", { name: "Добавить", exact: true });
  await addSupplier.scrollIntoViewIfNeeded();
  const addBounds = await addSupplier.boundingBox();
  expect(addBounds).not.toBeNull();
  expect(addBounds!.x).toBeGreaterThanOrEqual(0);
  expect(addBounds!.x + addBounds!.width).toBeLessThanOrEqual(390);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  const supplierTable = page.getByRole("region", { name: "Список поставщиков", exact: true });
  await expect(supplierTable.getByRole("columnheader")).toHaveCount(7);
  await supplierTable.scrollIntoViewIfNeeded();
  await supplierTable.focus();
  await page.keyboard.press("ArrowRight");
  await expect.poll(() => supplierTable.evaluate(element => element.scrollLeft)).toBeGreaterThan(0);
  await supplierCapture("suppliers-mobile-table");
  const editSupplier = page.getByRole("button", { name: "Открыть карточку Учебный поставщик Север", exact: true });
  await editSupplier.focus();
  await page.keyboard.press("Enter");
  const supplierDialog = page.getByRole("dialog", { name: "Поставщик", exact: true });
  const supplierClose = page.getByRole("button", { name: "Закрыть карточку поставщика", exact: true });
  await expect(supplierDialog).toBeVisible();
  await expect(supplierClose).toBeFocused();
  await page.keyboard.press("Shift+Tab");
  await expect(supplierDialog.getByRole("button", { name: "Отмена", exact: true })).toBeFocused();
  await page.keyboard.press("Tab");
  await expect(supplierClose).toBeFocused();
  await supplierCapture("suppliers-mobile-drawer");
  await page.keyboard.press("Escape");
  await expect(supplierDialog).toHaveCount(0);
  await expect(editSupplier).toBeFocused();
  await addSupplier.click();
  await expect(page.getByRole("dialog", { name: "Новый поставщик", exact: true })).toBeVisible();
  await supplierCapture("suppliers-mobile-create");
  await page.keyboard.press("Escape");
  await expect(addSupplier).toBeFocused();
  await page.setViewportSize({ width: 1440, height: 1000 });
  await editSupplier.click();
  await supplierCapture("suppliers-desktop-drawer");
  await page.keyboard.press("Escape");
  await page.getByRole("button", { name: "Включить тёмную тему", exact: true }).click();
  await page.getByRole("heading", { name: "Поставщики", exact: true }).scrollIntoViewIfNeeded();
  await supplierCapture("suppliers-dark-list");
  await editSupplier.click();
  await supplierCapture("suppliers-dark-drawer");
  await page.keyboard.press("Escape");
  await page.getByRole("button", { name: "Включить светлую тему", exact: true }).click();
  expect(supplierSuccessfulReads).toBe(1);
  expect(supplierFailedReads).toBeGreaterThanOrEqual(2);
  console.log("SUPPLIERS_AVAILABILITY_READS", JSON.stringify({ failed: supplierFailedReads, successful: supplierSuccessfulReads, manualRefreshClicks: 2 }));
  await page.unroute(suppliersUrl);

  // Inspect the existing calculator within the same synthetic procurement workflow.
  await page.goto("/erp/procurement/cost-calc");
  await expect(page.getByRole("heading", { name: "Предварительная себестоимость (Китай) → цена реализации", exact: true })).toBeVisible();
  for (const view of [
    { name: "cost-desktop", width: 1440, height: 1000, dark: false },
    { name: "cost-mobile", width: 390, height: 844, dark: false },
    { name: "cost-dark", width: 1440, height: 1000, dark: true },
  ]) {
    await page.setViewportSize({ width: view.width, height: view.height });
    if (view.dark) await page.getByRole("button", { name: "Включить тёмную тему", exact: true }).click();
    await page.getByRole("heading", { name: "Предварительная себестоимость (Китай) → цена реализации", exact: true }).scrollIntoViewIfNeeded();
    await page.screenshot({ path: testInfo.outputPath(`${view.name}.png`), fullPage: true });
    await testInfo.attach(view.name, { path: testInfo.outputPath(`${view.name}.png`), contentType: "image/png" });
    if (view.width === 390) {
      const lines = page.getByRole("region", { name: "Расчёт по позициям", exact: true });
      await lines.scrollIntoViewIfNeeded();
      await lines.focus();
      await expect(lines).toBeFocused();
      await page.keyboard.press("ArrowRight");
      await expect.poll(() => lines.evaluate((element) => element.scrollLeft)).toBeGreaterThan(0);
      await page.screenshot({ path: testInfo.outputPath("cost-mobile-table.png"), fullPage: true });
      await testInfo.attach("cost-mobile-table", { path: testInfo.outputPath("cost-mobile-table.png"), contentType: "image/png" });
    }
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    await testInfo.attach(`${view.name}-geometry`, { body: JSON.stringify(await page.evaluate(() => ({ viewport: innerWidth, documentWidth: document.documentElement.scrollWidth, tableWidth: document.querySelector("table")?.getBoundingClientRect().width }))), contentType: "application/json" });
  }

  // Exercise the sync response boundary without contacting 1C or writing ERP data.
  let syncRequests = 0;
  await page.route("**/api/integrations/1c/sync", async (route) => {
    expect(route.request().method()).toBe("POST");
    syncRequests += 1;
    await route.fulfill({ status: syncRequests === 1 ? 422 : 200, contentType: "application/json", body: JSON.stringify(syncRequests === 1
      ? { detail: { code: "legal_address_required", message: "PRIVATE_SOURCE_ID_AND_SECRET" } }
      : { counterparties: 5 }) });
  });
  await page.goto("/erp/spravochniki/import");
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.getByRole("button", { name: "Включить светлую тему", exact: true }).click();
  await page.getByRole("button", { name: "Синхронизировать", exact: true }).click();
  const syncAlert = page.getByRole("alert").filter({ hasText: /юридический адрес|Результат синхронизации/ });
  await expect(syncAlert).toContainText("Не подтверждён юридический адрес контрагента");
  await expect(syncAlert).not.toContainText("PRIVATE_SOURCE_ID_AND_SECRET");
  await syncAlert.scrollIntoViewIfNeeded();
  await page.screenshot({ path: testInfo.outputPath("sync-refusal-desktop.png"), fullPage: true });
  await testInfo.attach("sync-refusal-desktop", { path: testInfo.outputPath("sync-refusal-desktop.png"), contentType: "image/png" });
  await page.getByRole("button", { name: "Синхронизировать", exact: true }).click();
  await expect(syncAlert).toContainText("Результат синхронизации не подтверждён");
  await expect(page.getByText("Контрагентов обработано", { exact: true })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Синхронизировать", exact: true })).toBeEnabled();
  expect(syncRequests).toBe(2);
  await page.setViewportSize({ width: 390, height: 844 });
  await syncAlert.scrollIntoViewIfNeeded();
  await page.screenshot({ path: testInfo.outputPath("sync-unknown-mobile.png"), fullPage: true });
  await testInfo.attach("sync-unknown-mobile", { path: testInfo.outputPath("sync-unknown-mobile.png"), contentType: "image/png" });
});
