import { expect, test } from "@playwright/test";
import { ensureConfiguredOrganization, configuredOrganization, createBuyer, createDealFromBuyer, createDealThroughUI, seedInvoiceFacts, addInvoiceItemUI, confirmInvoicePartiesUI, issueInvoiceUI, prepareInvoiceUI } from "./fixtures";

// Критический путь карточки: создать сделку → проверить реквизиты → выпустить счёт ERP с резервом.
// Самодостаточно (на пустой доске CI карточек нет — создаём свою).
test("карточка сделки: выпуск счёта ERP с резервом", async ({ page }, testInfo) => {
  test.setTimeout(120_000);
  await ensureConfiguredOrganization(page);
  const buyer = await createBuyer(page, `E2E invoice buyer ${Date.now()}`);
  const createdDeal = await createDealThroughUI(page, buyer, `E2E-DOC-${Date.now()}`);
  const cardLink = page.getByTestId(`deal-card-${createdDeal.id}`).getByRole("link");
  await expect(cardLink).toHaveAttribute("href", `/crm/deals/${createdDeal.id}`);
  await cardLink.dblclick();
  await expect(page).toHaveURL(new RegExp(`/crm/deals/${createdDeal.id}$`));
  await expect(page.getByText("Документы", { exact: true })).toBeVisible();
  const dealId = Number(new URL(page.url()).pathname.split("/").pop());
  expect(dealId).toBe(createdDeal.id);
  const configured = await configuredOrganization(page);
  const seeded = await seedInvoiceFacts(page, dealId, buyer);
  const fixture = await addInvoiceItemUI(page, dealId, seeded, "100.00");
  expect(fixture.organization).toBe(configured.id);
  await confirmInvoicePartiesUI(page, dealId, fixture, buyer);
  await issueInvoiceUI(page, dealId, fixture, buyer, "stock", "100.00");
  const documents = await page.request.get(`/api/sales/deals/${dealId}/documents`);
  expect(documents.ok()).toBeTruthy();
  const invoices = (await documents.json()).filter((doc: { kind: string }) => doc.kind === "invoice");
  expect(invoices).toHaveLength(1);
  expect(invoices[0]).toMatchObject({ status: "issued", reserve_status: "reserved", onec_ref: null, amount: 240 });
  const original = await page.request.get(`/api/sales/documents/${invoices[0].id}/render`);
  expect(original.ok()).toBeTruthy();
  expect(await original.text()).toContain(buyer.name);
  await page.goto(`/crm/deals/${dealId}?org=${fixture.organization}&invoice=${invoices[0].id}#document-register`);
  const dealRegister = page.getByRole("region", { name: "Реестр документов сделки", exact: true });
  await expect(dealRegister.getByRole("button", { name: "Аннулирование счёта", exact: true })).toBeVisible();
  await expect(dealRegister.getByRole("button", { name: "Фактическая отгрузка и акты", exact: true })).toBeVisible();
  await expect(dealRegister.getByText(/Зарезервирован/).first()).toBeVisible();
  await dealRegister.screenshot({ path: testInfo.outputPath("deal-document-register.png") });
  await page.goto(`/erp/spravochniki/counterparty/${fixture.buyer}`);
  const clientRegister = page.getByRole("region", { name: "Документы клиента", exact: true });
  await expect(clientRegister).toContainText(`${configured.name} · УНП ${configured.unp}`);
  await expect(clientRegister.getByLabel("Юрлицо документов клиента", { exact: true })).toHaveCount(0);
  await expect(clientRegister.getByRole("article", { name: `Документ клиента ${invoices[0].id}`, exact: true })).toBeVisible();
  await clientRegister.screenshot({ path: testInfo.outputPath("client-document-register.png") });
  // Partial shipment and release use the same invoice; released stock is not a full shipment.
  const identity = { expected_version: invoices[0].version, expected_content_sha256: invoices[0].content_sha256 };
  const warehousePath = `/api/accounting/organizations/${fixture.organization}/invoices/${invoices[0].id}/document-shipments`;
  const shipmentPreview = await page.request.post(`${warehousePath}/preview`, { data: identity });
  expect(shipmentPreview.ok()).toBeTruthy();
  const basis = await shipmentPreview.json();
  expect(basis.lines).toHaveLength(1);
  expect(basis.lines[0]).toMatchObject({ sku_code: fixture.sku, warehouse: "E2E-W", execution_mode: "document", prohibit_negative_stock: true });
  const shipped = await page.request.post(warehousePath, { data: {
    ...identity, source_key: crypto.randomUUID(), expected_reservation_digest: basis.reservation_digest,
    expected_remaining_digest: basis.remaining_digest, expected_physical_digest: basis.physical_digest,
    operation_date: new Date().toISOString().slice(0, 10), evidence: "Synthetic partial shipment",
    lines: [{ line_no: basis.lines[0].line_no, warehouse: basis.lines[0].warehouse, qty: "1.00" }],
  } });
  expect(shipped.status(), await shipped.text()).toBe(201);
  await page.goto(`/crm/deals/${dealId}?org=${fixture.organization}&invoice=${invoices[0].id}#document-register`);
  await page.getByRole("button", { name: "Фактическая отгрузка и акты", exact: true }).click();
  const shipmentPanel = page.getByRole("region", { name: "Фактическая отгрузка счёта", exact: true });
  await expect(shipmentPanel).toContainText("Без WMS · по накладной");
  await shipmentPanel.getByLabel("Причина снятия остатка", { exact: true }).fill("Synthetic customer declined unshipped remainder");
  await shipmentPanel.getByRole("button", { name: "Рассчитать снятие остатка", exact: true }).click();
  await expect(shipmentPanel.getByText(/снять 1.00/)).toBeVisible();
  await shipmentPanel.getByRole("region", { name: "Снятие неотгруженного остатка", exact: true }).screenshot({ path: testInfo.outputPath("remainder-confirmation.png") });
  await shipmentPanel.getByRole("button", { name: "Подтвердить снятие остатка", exact: true }).click();
  await expect(shipmentPanel.getByText(/Остаток резерва снят. Квитанция №/)).toBeVisible();
  await expect(shipmentPanel.getByText("Неотгруженный остаток резерва снят", { exact: true })).toBeVisible();
  await expect(shipmentPanel.getByRole("button", { name: "Проверить выбранную отгрузку", exact: true })).toBeDisabled();
  await shipmentPanel.screenshot({ path: testInfo.outputPath("released-remainder.png") });
  await page.goto(`/crm/deals/${dealId}?org=${fixture.organization}`);
  const beforeLoss = await page.request.get(`/api/sales/deals/${dealId}/loss-context`);
  expect(beforeLoss.ok()).toBeTruthy();
  const originalStage = (await beforeLoss.json()).stage;
  await page.getByRole("button", { name: "Отказ / состояние запроса", exact: true }).click();
  const loss = page.getByRole("dialog");
  await loss.getByLabel("Причина отказа", { exact: true }).selectOption(fixture.loss_reason);
  await loss.getByRole("button", { name: "Запросить отказ", exact: true }).click();
  await expect(loss.getByText(/ожидает завершения/)).toBeVisible();
  await loss.getByLabel("Основание завершения или отзыва", { exact: true }).fill("Synthetic review; invoice has not been cancelled");
  await expect(loss.getByRole("button", { name: "Завершить отказ", exact: true })).toBeDisabled();
  const afterLoss = await page.request.get(`/api/sales/deals/${dealId}/loss-context`);
  expect((await afterLoss.json()).stage).toBe(originalStage);
  const retained = await page.request.get(`/api/sales/deals/${dealId}/documents`);
  expect((await retained.json()).find((doc: { id: number }) => doc.id === invoices[0].id)).toMatchObject({ status: "issued", reserve_status: "reserved" });
  await loss.screenshot({ path: testInfo.outputPath("pending-deal-loss.png") });
});

test("документы: ошибка загрузки отличается от пустого списка и допускает повтор", async ({ page }) => {
  const buyer = await createBuyer(page, `E2E document load ${Date.now()}`);
  const deal = await createDealFromBuyer(page, buyer, `E2E-DOC-LOAD-${Date.now()}`);
  let fail = true;
  await page.route(`**/api/sales/deals/${deal.id}/documents`, (route) => fail && route.request().method() === "GET"
    ? route.fulfill({ status: 500, contentType: "application/json", body: '{"detail":"synthetic failure"}' })
    : route.continue());
  await page.goto(`/crm/deals/${deal.id}`);
  await expect(page.getByText("Не удалось загрузить документы.", { exact: true })).toBeVisible();
  await expect(page.getByText("Документов пока нет", { exact: true })).toHaveCount(0);
  fail = false;
  await page.getByRole("button", { name: "Повторить загрузку документов", exact: true }).click();
  await expect(page.getByText("Документов пока нет", { exact: true })).toBeVisible();
});

test("счёт под заказ: потерянный ответ, повтор и неизменяемый оригинал", async ({ page }) => {
  test.setTimeout(120_000);
  await ensureConfiguredOrganization(page);
  const buyer = await createBuyer(page, `E2E invoice buyer ${Date.now()}`);
  const createdDeal = await createDealThroughUI(page, buyer, `E2E-DOC-${Date.now()}`);
  const cardLink = page.getByTestId(`deal-card-${createdDeal.id}`).getByRole("link");
  await expect(cardLink).toHaveAttribute("href", `/crm/deals/${createdDeal.id}`);
  await cardLink.dblclick();
  await expect(page).toHaveURL(new RegExp(`/crm/deals/${createdDeal.id}$`));
  await expect(page.getByText("Документы", { exact: true })).toBeVisible();
  const dealId = Number(new URL(page.url()).pathname.split("/").pop());
  expect(dealId).toBe(createdDeal.id);
  const configured = await configuredOrganization(page);
  const seeded = await seedInvoiceFacts(page, dealId, buyer);
  const fixture = await addInvoiceItemUI(page, dealId, seeded, "100.00");
  expect(fixture.organization).toBe(configured.id);
  await confirmInvoicePartiesUI(page, dealId, fixture, buyer);
  await prepareInvoiceUI(page, dealId, fixture, buyer, "on_order", "100.00");
  const endpoint = `/api/sales/deals/${dealId}/documents`;
  let originalCommand: unknown;
  let originalHtml = "";
  let originalId = 0;
  let attempts = 0;
  await page.route(`**${endpoint}`, async route => {
    if (route.request().method() !== "POST") return route.continue();
    const command = route.request().postDataJSON();
    attempts += 1;
    if (attempts === 1) {
      originalCommand = command;
      const response = await route.fetch();
      expect(response.status()).toBe(201);
      const receipt = await response.json();
      originalId = receipt.document.id;
      originalHtml = await (await page.request.get(`/api/sales/documents/${originalId}/render`)).text();
      await route.abort("failed");
    } else {
      expect(command).toEqual(originalCommand);
      await route.continue();
    }
  });
  await page.getByRole("checkbox", { name: "Подтверждаю выпуск без резерва и проверенные данные счёта" }).check();
  await page.getByRole("button", { name: "Выпустить счёт под заказ", exact: true }).click();
  await expect(page.getByRole("button", { name: "Повторить исходный запрос", exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Повторить исходный запрос", exact: true }).click();
  await expect(page.getByText("Подтверждён результат исходного запроса.", { exact: true })).toBeVisible();
  expect(attempts).toBe(2);
  const response = await page.request.get(endpoint);
  expect(response.ok()).toBeTruthy();
  const invoices = (await response.json()).filter((doc: { kind: string }) => doc.kind === "invoice");
  expect(invoices).toHaveLength(1);
  expect(invoices[0]).toMatchObject({ id: originalId, status: "issued", reserve_mode: "on_order", reserve_status: "unreserved", amount: 240 });
  expect(await (await page.request.get(`/api/sales/documents/${originalId}/render`)).text()).toBe(originalHtml);
  await page.reload();
  expect(await (await page.request.get(`/api/sales/documents/${originalId}/render`)).text()).toBe(originalHtml);
});
