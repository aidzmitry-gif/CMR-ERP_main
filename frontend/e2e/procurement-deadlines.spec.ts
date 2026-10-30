import { configureInstallationCompany } from "./installation-company";
import { expect, test } from "@playwright/test";

test("срок клиента переносится в черновик плана закупки", async ({ page }, testInfo) => {
  const stamp = Date.now();
  const post = async (url: string, data: unknown) => {
    const r = await page.request.post(`/api${url}`, { data });
    expect(r.ok(), await r.text()).toBeTruthy(); return r.json();
  };
  const get = async (url: string) => {
    const r = await page.request.get(`/api${url}`);
    expect(r.ok(), await r.text()).toBeTruthy(); return r.json();
  };
  const org = await post("/accounting/organizations", { name: `E2E deadlines ${stamp}`, unp: String(stamp).slice(-9) });
  const buyerName = `Synthetic deadline buyer ${stamp}`;
  const buyerUnp = String(800000000 + Number.parseInt(crypto.randomUUID().slice(0, 7), 16) % 99999999);
  const buyer = await post("/system/mdm/counterparty", { manual: { name: buyerName, unp: buyerUnp, legal_address: "Synthetic E2E buyer legal address" }, contacts: [] });
  expect(Number.isSafeInteger(buyer.id) && buyer.id > 0).toBe(true);
  const deal = await post("/sales/deals", { number: `DL-${stamp}`, title: "Deadline review", counterparty: buyerName, counterparty_id: buyer.id, amount: 0, ship_deadline: "2026-12-31", penalty_rate_pct: 1, penalty_cap_pct: 10, penalty_terms: "Synthetic contract penalty terms" });
  const ownership = `/sales/organizations/${org.id}/deals/${deal.id}`;
  const preview = await get(`${ownership}/ownership-preview`);
  await post(`${ownership}/ownership`, { expected_snapshot: preview.snapshot, evidence: "Synthetic browser fixture" });
  const supplierName = `Synthetic deadline supplier ${stamp}`;
  const supplierUnp = String(800000000 + Number.parseInt(crypto.randomUUID().slice(0, 7), 16) % 99999999);
  const supplierParty = await post("/system/mdm/counterparty", { manual: { name: supplierName, unp: supplierUnp, legal_address: "Synthetic E2E supplier legal address" }, contacts: [] });
  expect(Number.isSafeInteger(supplierParty.id) && supplierParty.id > 0).toBe(true);
  const supplier = await post("/procurement/suppliers", { counterparty_id: supplierParty.id, name: supplierName, unp: supplierUnp, status: "active" });
  expect(supplier).toMatchObject({ counterparty_id: supplierParty.id, name: supplierName, unp: supplierUnp });
  const scope = `/procurement/organizations/${org.id}`;
  const catalog = await get(`${scope}/sku-options?q=QA-ORDER`);
  expect(catalog.organization_id).toBe(org.id);
  const matches = catalog.items.filter((row: { code: string }) => row.code === "QA-ORDER");
  expect(matches).toHaveLength(1);
  const sku = matches[0];
  const identity = await get(`${scope}/request-plan-context`);
  expect(identity).toMatchObject({ organization_id: org.id, can_manage: true });
  const headers = { "X-Expected-Principal": identity.principal, "X-Expected-Organization": String(org.id) };
  const requestKey = crypto.randomUUID();
  const created = await page.request.post(`/api${scope}/orders`, { headers, data: {
    request_key: requestKey,
    document: { supplier: supplier.name, supplier_id: supplier.id, supplier_unp: supplier.unp,
      eta_date: null, freight_byn: "0.00", lines: [{ sku_code: sku.code, sku_id: sku.id,
        sku_title: sku.title, sku_unit: sku.unit, qty: "10.00", goods_value_byn: "100.00",
        weight: "0.000", volume: "0.0000" }] },
    ownership_evidence: "Synthetic browser fixture", request_basis: null,
  } });
  expect(created.status(), await created.text()).toBe(201);
  const receipt = await created.json();
  expect(receipt).toMatchObject({ organization_id: org.id, principal: identity.principal, request_key: requestKey, outcome: "created", status: "draft" });
  const order = { id: receipt.order_id };
  const statusKey = crypto.randomUUID();
  const ordered = await page.request.post(`/api${scope}/orders/${order.id}/edit-commands`, { headers, data: {
    version: 1, request_key: statusKey, order_id: order.id, action: "status", payload: { status: "ordered" },
  } });
  expect(ordered.status(), await ordered.text()).toBe(200);
  expect(await ordered.json()).toMatchObject({ organization_id: org.id, order_id: order.id, outcome: "applied", effect: { from: "draft", to: "ordered" } });
  const detail = await get(`/procurement/organizations/${org.id}/orders/${order.id}`);
  await post(`/procurement/organizations/${org.id}/expected-reservations`, { order_id: order.id, order_line_id: detail.lines[0].id, deal_id: deal.id, qty: "5.00", request_key: crypto.randomUUID(), evidence: "Synthetic customer reservation" });
  await configureInstallationCompany(page, org.id);
  await page.goto(`/erp/procurement/orders/${order.id}?org=${org.id}`);
  await expect(page.getByLabel("В Минске до", { exact: true })).toBeEnabled();
  await page.getByRole("button", { name: "Проверить клиентские сроки" }).click();
  await expect(page.getByText(/Самая ранняя дата прихода: 2026-12-28/)).toBeVisible();
  await expect(page.getByText(/ставка 1.00%; предел 10.00%.*Synthetic contract penalty terms/)).toBeVisible();
  await expect(page.getByText(/Запас по сроку не определён/)).toBeVisible();
  await page.getByRole("button", { name: "Обновить сроки и подставить дату в план" }).click();
  await expect(page.getByLabel("В Минске до", { exact: true })).toHaveValue("2026-12-28");
  const saved = await get(`/procurement/organizations/${org.id}/orders/${order.id}/plan`);
  expect(saved.target_arrival_date).toBeNull();
  await page.screenshot({ path: testInfo.outputPath("customer-deadline-draft.png"), fullPage: true });
  const command = page.waitForResponse(r => r.url().includes(`/orders/${order.id}/edit-commands`) && r.request().method() === "POST");
  await page.getByRole("button", { name: "Пересчитать план", exact: true }).click();
  expect((await command).ok()).toBeTruthy();
  await expect(page.getByLabel("В Минске до", { exact: true })).toBeEnabled();
  const confirmed = await get(`/procurement/organizations/${org.id}/orders/${order.id}/plan`);
  expect(confirmed.target_arrival_date).toBe("2026-12-28");
  expect(confirmed.milestones.length).toBeGreaterThan(0);
  await page.reload();
  await expect(page.getByLabel("В Минске до", { exact: true })).toHaveValue("2026-12-28");
  await page.getByRole("button", { name: "Проверить клиентские сроки" }).click();
  await expect(page.getByText(/Запас до требуемой даты прихода: 0 дн/)).toBeVisible();
  await expect(page.getByText(/ставка 1.00%; предел 10.00%/)).toBeVisible();
  const riskReview = await get(`${scope}/orders/${order.id}/customer-deadlines`);
  expect(riskReview.risk_details.slack_days).toBe(0);
  expect(riskReview.risk_details.items[0]).toMatchObject({ number: deal.number, penalty_rate_pct: "1.00", penalty_cap_pct: "10.00" });
  await testInfo.attach("customer-deadline-risk.json", { body: JSON.stringify(riskReview), contentType: "application/json" });
  await page.screenshot({ path: testInfo.outputPath("customer-deadline-saved.png"), fullPage: true });
});
