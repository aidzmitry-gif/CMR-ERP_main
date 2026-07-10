import { expect, test } from "@playwright/test";

type PurchaseOrder = {
  id: number;
  number: string;
};

type ImportShipment = {
  id: number;
  po_ref: string;
};

// The order and import screens do not expose creation controls. Prepare their
// upstream state through the authenticated API, then exercise both user-facing
// screens. Every run owns its PO/import pair, so an empty CI database is valid.
test("procurement PO is traceable in logistics and its import stage advances", async ({ page }) => {
  const runId = Date.now().toString(36).toUpperCase();
  const supplier = `E2E Supplier ${runId}`;
  const sku = `E2E-SKU-${runId}`;
  const cargo = `E2E cargo ${runId}`;

  const orderResponse = await page.request.post("/api/procurement/orders", {
    data: {
      supplier,
      number: `E2E-PO-${runId}`,
      status: "shipped",
      eta_date: "2030-01-15",
      freight_byn: 125,
      lines: [{ sku_code: sku, qty: 7, goods_value_byn: 700, weight: 14, volume: 0.2 }],
    },
  });
  expect(orderResponse.ok()).toBeTruthy();
  const order = (await orderResponse.json()) as PurchaseOrder;

  const importResponse = await page.request.post("/api/logistics/imports", {
    data: {
      supplier,
      cargo,
      qty: 7,
      amount: 125,
      stage: "factory",
      po_ref: order.number,
    },
  });
  expect(importResponse.ok()).toBeTruthy();
  const importShipment = (await importResponse.json()) as ImportShipment;
  expect(importShipment.po_ref).toBe(order.number);

  await page.goto("/erp/procurement/orders");
  const orderRow = page.locator("tr", { hasText: order.number });
  await expect(orderRow).toBeVisible();
  await expect(orderRow).toContainText(supplier);
  await expect(orderRow).toContainText(sku);

  await page.goto("/erp/logistics");
  await page.getByRole("button", { name: "\u0418\u043c\u043f\u043e\u0440\u0442", exact: true }).click();

  const importCard = page.getByRole("button", { name: new RegExp(cargo) });
  await expect(importCard).toBeVisible();
  await importCard.click();

  const drawer = page.locator("aside").filter({ hasText: order.number });
  await expect(drawer).toBeVisible();
  await expect(drawer).toContainText(order.number);
  await expect(drawer).toContainText(supplier);

  const advanceResponse = page.waitForResponse(
    (response) =>
      response.url().includes(`/api/logistics/imports/${importShipment.id}`) &&
      response.request().method() === "PATCH",
  );
  await drawer.getByRole("button", { name: /\u041a\u043e\u043d\u0441\u043e\u043b\u0438\u0434\u0430\u0446/ }).click();
  expect((await advanceResponse).ok()).toBeTruthy();
  await expect(drawer.getByRole("button", { name: /\u0412 \u043f\u0443\u0442\u0438/ })).toBeVisible();
});
