import { expect, test } from "@playwright/test";
import { configuredOrganization, createBuyer, createDealFromBuyer } from "./fixtures";

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
  const org = await configuredOrganization(page);
  const buyer = await createBuyer(page, `E2E deadline buyer ${stamp}`);
  const deal = await createDealFromBuyer(page, buyer, `DL-${stamp}`);
  const deadline = await page.request.patch(`/api/sales/deals/${deal.id}`, { data: { ship_deadline: "2026-12-31" } });
  expect(deadline.ok(), await deadline.text()).toBeTruthy();
  expect(await deadline.json()).toMatchObject({ id: deal.id, ship_deadline: "2026-12-31" });
  expect(await get(`/sales/deals/${deal.id}`)).toMatchObject({ id: deal.id, ship_deadline: "2026-12-31" });
  const ownership = `/sales/organizations/${org.id}/deals/${deal.id}`;
  const preview = await get(`${ownership}/ownership-preview`);
  await post(`${ownership}/ownership`, { expected_snapshot: preview.snapshot, evidence: "Synthetic browser fixture" });
  const supplierParty = await createBuyer(page, `E2E deadline supplier ${stamp}`);
  const supplier = await post("/procurement/suppliers", {
    counterparty_id: supplierParty.id, name: supplierParty.name, unp: supplierParty.unp, status: "active",
  });
  expect(supplier).toMatchObject({ counterparty_id: supplierParty.id, name: supplierParty.name, unp: supplierParty.unp, status: "active" });
  expect(Number.isSafeInteger(supplier.id) && supplier.id > 0).toBe(true);
  const scope = `/procurement/organizations/${org.id}`;
  const suppliers = await get(`${scope}/supplier-options?q=${encodeURIComponent(supplierParty.unp)}`);
  expect(suppliers.organization_id).toBe(org.id);
  expect(suppliers.items).toEqual([{ id: supplier.id, name: supplier.name, unp: supplier.unp }]);
  const catalog = await get(`${scope}/sku-options?q=QA-ORDER`);
  expect(catalog.organization_id).toBe(org.id);
  const matches = catalog.items.filter((row: { code: string }) => row.code === "QA-ORDER");
  expect(matches).toHaveLength(1);
  const sku = matches[0];
  expect(Number.isSafeInteger(sku.id) && sku.id > 0).toBe(true);
  expect(sku.title).not.toBe("");
  expect(sku.unit).not.toBe("");
  const identity = await get(`${scope}/request-plan-context`);
  expect(identity).toMatchObject({ organization_id: org.id, can_manage: true });
  expect(typeof identity.principal === "string" && identity.principal.length > 0).toBe(true);
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
  expect(receipt).toMatchObject({ organization_id: org.id, principal: identity.principal,
    request_key: requestKey, outcome: "created", status: "draft" });
  expect(Number.isSafeInteger(receipt.order_id) && receipt.order_id > 0).toBe(true);
  expect(Number.isSafeInteger(receipt.ownership_id) && receipt.ownership_id > 0).toBe(true);
  expect(receipt.lines).toHaveLength(1);
  expect(receipt.lines[0]).toMatchObject({ sku_code: sku.code, qty: "10.00", goods_value_byn: "100.00" });
  expect(Number.isSafeInteger(receipt.lines[0].id) && receipt.lines[0].id > 0).toBe(true);
  const order = { id: receipt.order_id };
  const statusKey = crypto.randomUUID();
  const ordered = await page.request.post(`/api${scope}/orders/${order.id}/edit-commands`, { headers, data: {
    version: 1, request_key: statusKey, order_id: order.id, action: "status", payload: { status: "ordered" },
  } });
  expect(ordered.status(), await ordered.text()).toBe(200);
  expect(await ordered.json()).toMatchObject({ organization_id: org.id, principal: identity.principal,
    request_key: statusKey, order_id: order.id, ownership_id: receipt.ownership_id,
    outcome: "applied", effect: { from: "draft", to: "ordered" } });
  const detail = await get(`${scope}/orders/${order.id}`);
  expect(detail.status).toBe("ordered");
  expect(detail.lines).toHaveLength(1);
  expect(detail.lines[0]).toMatchObject({ id: receipt.lines[0].id, sku_code: sku.code, qty: "10.00", goods_value_byn: "100.00" });
  const reserved = await post(`${scope}/expected-reservations`, { order_id: order.id,
    order_line_id: detail.lines[0].id, deal_id: deal.id, qty: "5.00", request_key: crypto.randomUUID(),
    evidence: "Synthetic customer reservation" });
  expect(reserved).toMatchObject({ order_line_id: detail.lines[0].id, ordered: "10.00", expected_reserved: "5.00", free_expected: "5.00" });
  expect(reserved.reservations).toHaveLength(1);
  expect(reserved.reservations[0]).toMatchObject({ deal_id: deal.id, qty: "5.00" });
  await page.goto(`/erp/procurement/orders/${order.id}?org=${org.id}`);
  await expect(page.getByLabel("В Минске до", { exact: true })).toBeEnabled();
  await page.getByRole("button", { name: "Проверить клиентские сроки" }).click();
  await expect(page.getByText(/Самая ранняя дата прихода: 2026-12-28/)).toBeVisible();
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
  await page.screenshot({ path: testInfo.outputPath("customer-deadline-saved.png"), fullPage: true });
});
