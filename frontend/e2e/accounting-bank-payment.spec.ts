import { execFileSync } from "node:child_process";
import { expect, test } from "@playwright/test";

test("ручное списание поставщику сохраняет аналитику и повторяется без дубля", async ({ page }, testInfo) => {
  const stamp = Date.now();
  const created = await page.request.post("/api/accounting/organizations", { data: {
    name: `E2E bank dimensions ${stamp}`, unp: String(stamp).slice(-9),
  } });
  expect(created.ok(), await created.text()).toBeTruthy();
  const org = await created.json();
  execFileSync("python", ["e2e/seed_bank_import.py", String(org.id)], { timeout: 30000 });
  const account = await page.request.post(`/api/accounting/organizations/${org.id}/accounts`, { data: {
    code: "60", title: "Поставщики E2E", category: "liability", cash: false,
    valid_from: "2026-01-01", required_dimensions: ["counterparty", "contract"],
    currency_tracking: false, quantity_tracking: false, normative_ref: "SYNTHETIC E2E ONLY",
  } });
  expect(account.ok(), await account.text()).toBeTruthy();
  await page.goto("/erp/accounting");
  await page.getByLabel("Организация", { exact: true }).selectOption(String(org.id));
  await page.getByRole("button", { name: "Банк", exact: true }).click();
  await page.getByLabel("Банковский источник", { exact: true }).fill(`E2E-PAYMENT-${org.id}`);
  await page.getByLabel("Банковская выписка", { exact: true }).fill(`E2E-STATEMENT-${org.id}`);
  await page.getByLabel("Направление платежа").selectOption("payment");
  await page.getByLabel("Банковский счёт", { exact: true }).selectOption("51");
  await page.getByLabel("Счёт расчётов", { exact: true }).selectOption("60");
  await page.getByLabel("Банковская сумма").fill("75.50");
  await page.getByLabel("Поток платежа").selectOption("operating");
  await page.getByLabel("Назначение платежа").fill("Синтетическая оплата поставщику");
  await page.getByLabel("bank_statement", { exact: true }).fill(`E2E-STATEMENT-${org.id}`);
  await page.getByLabel("Контрагент", { exact: true }).fill("SUPPLIER-E2E");
  await page.getByLabel("Договор", { exact: true }).fill("PURCHASE-E2E");
  async function confirmPayment() {
    await page.getByRole("button", { name: "Рассчитать банковские проводки", exact: true }).click();
    await expect(page.getByText(/Кт 51.*75\.50 BYN/)).toBeVisible();
    await expect(page.getByText(/Дт 60.*75\.50 BYN/)).toBeVisible();
    const response = page.waitForResponse(r => r.url().endsWith("/bank/confirm") && r.request().method() === "POST");
    await page.getByRole("button", { name: "Подтвердить банковскую операцию", exact: true }).click();
    const saved = await response;
    expect(saved.ok(), await saved.text()).toBeTruthy();
    return saved.json();
  }
  const first = await confirmPayment();
  await expect(page.getByRole("status").filter({ hasText: `Банковская операция № ${first.id} проведена.` })).toBeVisible();
  await expect(page.getByRole("status").filter({ hasText: "Загрузка…" })).toHaveCount(0);
  const repeated = await confirmPayment();
  expect(repeated.id).toBe(first.id);
  const entryResponse = await page.request.get(`/api/accounting/organizations/${org.id}/entries/${first.id}`);
  expect(entryResponse.ok(), await entryResponse.text()).toBeTruthy();
  const entry = await entryResponse.json();
  expect(entry.lines).toHaveLength(2);
  expect(entry.lines.find((line: { account_code: string }) => line.account_code === "51")).toMatchObject({ side: "credit", amount: "75.50", cash_activity: "operating" });
  expect(entry.lines.find((line: { account_code: string }) => line.account_code === "60")).toMatchObject({ side: "debit", amount: "75.50", dimensions: { counterparty: "SUPPLIER-E2E", contract: "PURCHASE-E2E" } });
  await page.screenshot({ path: testInfo.outputPath("bank-payment-confirmed.png"), fullPage: true });
});
