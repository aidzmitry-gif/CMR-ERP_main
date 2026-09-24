import { readFile } from "node:fs/promises";

import { expect, test } from "@playwright/test";

test("60/62: бухгалтер видит документ и скачивает только согласованную внутреннюю расшифровку", async ({ page }, testInfo) => {
  const stamp = Date.now();
  const first = await page.request.post("/api/accounting/organizations", {
    data: { name: `E2E settlements A ${stamp}`, unp: String(stamp).slice(-9) },
  });
  expect(first.ok(), await first.text()).toBeTruthy();
  const orgA = await first.json();
  const second = await page.request.post("/api/accounting/organizations", {
    data: { name: `E2E settlements B ${stamp}`, unp: String(stamp + 1).slice(-9) },
  });
  expect(second.ok(), await second.text()).toBeTruthy();
  const orgB = await second.json();

  let wrongScope = false;
  await page.route("**/api/accounting/organizations/*/reports/trade-settlements?*", async (route) => {
    const url = new URL(route.request().url());
    const selectedOrg = Number(url.pathname.match(/organizations\/(\d+)\/reports/)?.[1]);
    const mismatch = selectedOrg === orgB.id && !wrongScope;
    const report = {
      organization_id: wrongScope ? orgA.id : selectedOrg,
      from: url.searchParams.get("start"), to: url.searchParams.get("end"),
      status: "preliminary", scope: "posted_accounts_60_62",
      due_dates_verified: false, statutory_certified: false, review_items: [],
      osv_reconciliation: {
        status: mismatch ? "mismatch" : "matched", basis: "same_posted_journal",
        osv_line_count: mismatch ? 3 : 2, document_line_count: 2,
        missing_osv_lines: mismatch ? 1 : 0, extra_document_lines: 0,
        missing_postings: mismatch ? [{ entry_id: 9, line_id: 99 }] : [],
        accounts: [{ account: "62", matched: !mismatch,
          osv_byn: { opening: "100.00", debit: "0.00", credit: mismatch ? "50.00" : "40.00", closing: mismatch ? "50.00" : "60.00" },
          documents_byn: { opening: "100.00", debit: "0.00", credit: "40.00", closing: "60.00" } }],
      },
      totals_byn: { receivable: "60.00", payable: "0.00", customer_advance: "0.00", supplier_advance: "0.00", unclassified: "0.00" },
      rows: [{
        key: "synthetic-document-1", account: "62", account_title: "Расчёты с покупателями",
        category: "asset", counterparty: "Синтетический клиент", contract: "Договор 1",
        document: "Счёт 1", currencies: ["BYN"], classification: "receivable",
        balance_kind: "receivable", analytics_complete: true,
        opening_byn: "100.00", debit_byn: "0.00", credit_byn: "40.00", closing_byn: "60.00",
        bank_receipts_byn: "40.00", bank_payments_byn: "0.00", offset_debit_byn: "0.00", offset_credit_byn: "0.00",
        movements: [
          { entry_id: 11, line_id: 21, date: "2026-08-31", source: "sale:1", operation: "sale",
            source_version: 1, side: "debit", amount_byn: "100.00", period_bucket: "opening", kind: "posting" },
          { entry_id: 12, line_id: 22, date: "2026-09-10", source: "bank:1", operation: "bank_settlement",
            source_version: 1, side: "credit", amount_byn: "40.00", period_bucket: "movement", kind: "bank_receipt" },
        ],
      }],
    };
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(report) });
  });

  await page.goto("/erp/accounting");
  await page.getByLabel("Организация", { exact: true }).selectOption(String(orgA.id));
  await page.getByLabel("Начало периода").fill("2026-09-01");
  await page.getByLabel("Конец периода").fill("2026-09-30");
  await page.getByRole("navigation", { name: "Разделы бухгалтерии" }).getByRole("button", { name: "Отчёты" }).click();
  await page.getByRole("button", { name: "Расчёты 60/62", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Торговые расчёты по документам" })).toBeVisible();
  await expect(page.getByRole("status").filter({ hasText: "Внутренняя сверка с ОСВ" })).toContainText("это не сверка с 1С");
  await expect(page.getByText("Синтетический клиент · Счёт 1")).toBeVisible();
  await page.screenshot({ path: testInfo.outputPath("trade-settlements.png"), fullPage: true });

  const [download] = await Promise.all([
    page.waitForEvent("download"),
    page.getByRole("button", { name: "Скачать CSV для внутренней сверки" }).click(),
  ]);
  expect(download.suggestedFilename()).toBe(`trade-settlements-org-${orgA.id}-2026-09-01-2026-09-30.csv`);
  const csv = await readFile(await download.path(), "utf8");
  expect(csv.startsWith("\uFEFForganization_id,period_start,period_end,status,account")).toBe(true);
  expect(csv.trimEnd().split("\r\n")).toHaveLength(2);
  expect(csv).toContain('"Синтетический клиент","Договор 1","Счёт 1"');
  expect(csv).toContain(',100.00,0.00,40.00,60.00,2,"11:21|12:22"');

  await page.getByLabel("Организация", { exact: true }).selectOption(String(orgB.id));
  await expect(page.getByRole("alert").filter({ hasText: "Расхождение с ОСВ" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Скачать CSV для внутренней сверки" })).toHaveCount(0);
  wrongScope = true;
  await page.getByLabel("Конец периода").fill("2026-09-29");
  await expect(page.getByRole("alert").filter({ hasText: "Ответ расчётов не соответствует выбранной книге" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Скачать CSV для внутренней сверки" })).toHaveCount(0);
});
