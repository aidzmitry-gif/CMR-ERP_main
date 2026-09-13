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
  const deal = await post("/sales/deals", { number: `DL-${stamp}`, title: "Deadline review", counterparty: "Synthetic buyer", amount: 0, ship_deadline: "2026-12-31" });
  const ownership = `/sales/organizations/${org.id}/deals/${deal.id}`;
  const preview = await get(`${ownership}/ownership-preview`);
  await post(`${ownership}/ownership`, { expected_snapshot: preview.snapshot, evidence: "Synthetic browser fixture" });
  const order = await post("/procurement/orders", { supplier: "Synthetic supplier", status: "ordered", lines: [{ sku_code: `DL-${stamp}`, qty: 10, goods_value_byn: 100 }] });
  await post(`/procurement/organizations/${org.id}/purchase-ownership`, { kind: "order", source_id: order.id, evidence: "Synthetic browser fixture" });
  const detail = await get(`/procurement/organizations/${org.id}/orders/${order.id}`);
  await post(`/procurement/organizations/${org.id}/expected-reservations`, { order_id: order.id, order_line_id: detail.lines[0].id, deal_id: deal.id, qty: "5.00", request_key: crypto.randomUUID(), evidence: "Synthetic customer reservation" });
  await page.goto(`/erp/procurement/orders/${order.id}?org=${org.id}`);
  await expect(page.getByLabel("В Минске до", { exact: true })).toBeEnabled();
  await page.getByRole("button", { name: "Проверить клиентские сроки" }).click();
  await expect(page.getByText(/Самая ранняя дата прихода: 2026-12-28/)).toBeVisible();
  await page.getByRole("button", { name: "Обновить сроки и подставить дату в план" }).click();
  await expect(page.getByLabel("В Минске до", { exact: true })).toHaveValue("2026-12-28");
  const saved = await get(`/procurement/organizations/${org.id}/orders/${order.id}/plan`);
  expect(saved.target_arrival_date).toBeNull();
  await page.screenshot({ path: testInfo.outputPath("customer-deadline-draft.png"), fullPage: true });
});
