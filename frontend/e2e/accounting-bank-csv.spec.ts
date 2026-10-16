import { expect, test } from "@playwright/test";

test("CSV проверяется и сохраняется без повторных операций", async ({ page }, testInfo) => {
  const stamp = Date.now();
  const created = await page.request.post("/api/accounting/organizations", {
    data: { name: `E2E bank CSV ${stamp}`, unp: String(stamp).slice(-9) },
  });
  expect(created.ok(), await created.text()).toBeTruthy();
  const org = await created.json();
  await page.goto("/erp/accounting");
  await page.getByLabel("Организация", { exact: true }).selectOption(String(org.id));
  await page.getByRole("button", { name: "Импорт выписки", exact: true }).click();
  await page.getByText("Загрузить выписку CSV", { exact: true }).click();
  await page.getByLabel("Банк для CSV", { exact: true }).fill("Synthetic CSV bank");
  await page.getByLabel("Наш банковский счёт для CSV", { exact: true }).fill(`TEST-${stamp}`);
  await page.getByLabel("Основание принадлежности счёта для CSV", { exact: true }).fill("Synthetic ownership");
  const header = "external_id,direction,operation_date,amount,currency,counterparty_name,counterparty_identifier,purpose\n";
  const body = `CSV-IN-${stamp},receipt,2026-09-01,100.00,BYN,,,Sale\nCSV-OUT-${stamp},payment,2026-09-01,20.50,BYN,,,Purchase\n`;
  await page.getByLabel("Файл банковской выписки CSV").setInputFiles({ name: "synthetic.csv", mimeType: "text/csv", buffer: Buffer.from(header + body) });
  await page.getByRole("button", { name: "Проверить CSV", exact: true }).click();
  await expect(page.getByText("Корректных строк: 2.", { exact: false })).toContainText("100.00 BYN; списания: 20.50 BYN");
  await page.getByRole("button", { name: "Сохранить строки выписки", exact: true }).click();
  await expect(page.getByRole("status").filter({ hasText: "Обработано строк:" })).toContainText("Обработано строк: 2");
  await expect(page.getByRole("row").filter({ hasText: `CSV-IN-${stamp}` })).toHaveCount(1);
  await expect(page.getByRole("row").filter({ hasText: `CSV-OUT-${stamp}` })).toHaveCount(1);
  await page.getByRole("button", { name: "Проверить CSV", exact: true }).click();
  await page.getByRole("button", { name: "Сохранить строки выписки", exact: true }).click();
  await expect(page.getByRole("status").filter({ hasText: "Обработано строк:" })).toContainText("Обработано строк: 2");
  await expect(page.getByRole("row").filter({ hasText: `CSV-IN-${stamp}` })).toHaveCount(1);
  await page.screenshot({ path: testInfo.outputPath("bank-csv-import.png"), fullPage: true });
});
