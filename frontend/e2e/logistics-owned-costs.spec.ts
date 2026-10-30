import { configureInstallationCompany } from "./installation-company";
import { expect, test } from "@playwright/test";

test("фрахт выбранного юрлица отделён от чужих и неоценённых поставок", async ({ page }, testInfo) => {
  const stamp = Date.now();
  const post = async (url: string, data: unknown) => {
    const response = await page.request.post(`/api${url}`, { data });
    expect(response.ok(), await response.text()).toBeTruthy();
    return response.json();
  };
  const company = async (suffix: number) => post("/accounting/organizations", {
    name: `Synthetic freight ${suffix} ${stamp}`, unp: String(stamp + suffix).slice(-9),
  });
  const own = await company(1), other = await company(2);
  let sequence = 0;
  const source = async (amount: number, org: number | null, ownership = "own", stage = "warehouse") => {
    const row = await post("/logistics/imports", {
      number: `SYN-COST-${stamp}-${++sequence}`, supplier: "Synthetic freight supplier",
      cargo: "Synthetic freight fixture", qty: 1, amount, stage,
    });
    if (org !== null) await post(`/accounting/organizations/${org}/source-bindings`, {
      source_type: "logistics_import", source_id: row.id, ownership,
      evidence: "Synthetic browser explicit source qualification",
    });
  };
  await source(12000, own.id); await source(5000, own.id);
  await source(8000, own.id, "own", "in_transit");
  await source(999999, other.id); await source(777777, null);
  await source(333333, own.id, "customer");

  await configureInstallationCompany(page, own.id);
  await page.goto("/erp/logistics");
  await page.getByRole("button", { name: "Экономия", exact: true }).click();
  const report = page.getByRole("region", { name: "Аналитика стоимости по юрлицу" });
  const selector = report.getByLabel("Юрлицо аналитики");
  await expect(selector).toHaveCount(0);
  const tile = (label: string) => report.getByText(label, { exact: true }).locator("..");
  await expect(tile("Известный фрахт")).toHaveText(/Известный фрахт\s*17\s000,00 Br/);
  await expect(tile("Поставок с известной ценой")).toHaveText(/Поставок с известной ценой\s*2/);
  await expect(tile("Средний известный фрахт")).toHaveText(/Средний известный фрахт\s*8\s500,00 Br/);
  await expect(tile("Итог по подтверждённым поставкам")).toHaveText(/17\s000,00 Br/);
  await expect(report.getByText(/Подтверждено источников: 3; на складе: 2; вне стадии «Склад»: 1/)).toBeVisible();
  await expect(report).not.toContainText(/999\s999|777\s777|333\s333/);
  await expect(report.getByText(/Показатель не определён/)).toHaveCount(3);
  expect((await page.request.get("/api/logistics/cost-insights")).status()).toBe(409);
  await page.screenshot({ path: testInfo.outputPath("company-qualified-freight.png"), fullPage: true });

  await configureInstallationCompany(page, other.id);
  await page.reload();
  await page.getByRole("button", { name: "Экономия", exact: true }).click();
  await expect(tile("Известный фрахт")).toHaveText(/999\s999,00 Br/);
  await expect(report).not.toContainText(/17\s000,00 Br/);
  await configureInstallationCompany(page, own.id);
  await page.reload();
  await page.getByRole("button", { name: "Экономия", exact: true }).click();
  await expect(tile("Известный фрахт")).toHaveText(/17\s000,00 Br/);
  await source(0, own.id);
  await report.getByRole("button", { name: "Обновить", exact: true }).click();
  await expect(tile("Известный фрахт")).toHaveText(/17\s000,00 Br/);
  await expect(tile("Итог по подтверждённым поставкам")).toHaveText(/Не определён/);
  await expect(report.getByRole("alert")).toHaveText(/Не оценён фрахт поставок: 1. Общий итог не определён/);
  const readback = await page.request.get(`/api/logistics/organizations/${own.id}/cost-insights`);
  expect(readback.status()).toBe(200);
  expect(readback.headers()["cache-control"]).toBe("private, no-store");
  const body = await readback.json();
  expect(body).toMatchObject({ organization_id: own.id, complete_cost_coverage: false, posting_status: "not_verified",
    import_freight: { status: "partial", known_total: "17000.00", known_average: "8500.00", total: null,
      known_count: 2, unpriced_count: 1, qualified_import_count: 4, excluded_nonwarehouse_count: 1 } });
  await testInfo.attach("qualified-freight-readback.json", { body: JSON.stringify(body), contentType: "application/json" });
  await page.screenshot({ path: testInfo.outputPath("company-partial-freight.png"), fullPage: true });
});
