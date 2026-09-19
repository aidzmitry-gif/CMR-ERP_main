import { execFileSync } from "node:child_process";
import { expect, test } from "@playwright/test";

test("строка списания проходит из формы выписки в проводку один раз", async ({ page }, testInfo) => {
  const stamp = Date.now();
  const created = await page.request.post("/api/accounting/organizations", {
    data: { name: `E2E bank dimensions ${stamp}`, unp: String(stamp).slice(-9) },
  });
  expect(created.ok(), await created.text()).toBeTruthy();
  const org = await created.json();
  execFileSync("python", ["e2e/seed_bank_import.py", String(org.id)], { timeout: 30000 });
  const account = await page.request.post(`/api/accounting/organizations/${org.id}/accounts`, {
    data: { code: "60", title: "Поставщики", category: "liability", cash: false,
      valid_from: "2026-01-01", required_dimensions: [], currency_tracking: false,
      quantity_tracking: false, normative_ref: "Synthetic browser test only" },
  });
  expect(account.ok(), await account.text()).toBeTruthy();
  await page.goto("/erp/accounting");
  await page.getByLabel("Организация", { exact: true }).selectOption(String(org.id));
  await page.getByRole("button", { name: "Импорт выписки", exact: true }).click();
  await page.getByText("Добавить строку из выписки", { exact: true }).click();
  const reference = `BANK-PAYMENT-${stamp}`;
  const fields = {
    "Банк (одинаковое обозначение во всех выписках)": "Synthetic bank",
    "Наш банковский счёт": "SYNTHETIC-ACCOUNT",
    "Идентификатор операции в банке": reference,
    "Дата операции": "2026-09-03",
    "Сумма BYN": "125.50",
    "Контрагент": "Synthetic supplier",
    "Назначение платежа": "Synthetic supplier payment",
    "Название файла или номер выписки": "synthetic.csv",
    "Основание принадлежности счёта выбранному юрлицу": "Synthetic owned account",
  };
  for (const [label, value] of Object.entries(fields)) await page.getByLabel(label, { exact: true }).fill(value);
  await page.getByLabel("Направление строки выписки").selectOption("payment");
  await page.getByRole("button", { name: "Сохранить строку выписки", exact: true }).click();
  const row = page.getByRole("row").filter({ hasText: reference });
  await expect(row).toContainText("Списание");
  await expect(row).toContainText("125.50");
  // Saving the same source again must not add another queue row.
  await page.getByRole("button", { name: "Сохранить строку выписки", exact: true }).click();
  await expect(page.getByRole("button", { name: "Сохранить строку выписки", exact: true })).toBeEnabled();
  await expect(row).toHaveCount(1);
  await row.getByRole("button", { name: "Выбрать", exact: true }).click();
  await page.getByLabel("Счёт расчётов импорта").selectOption("60");
  await page.getByRole("button", { name: "Рассчитать проводки", exact: true }).click();
  await expect(page.getByText(/Кт 51.*125.50 BYN/)).toBeVisible();
  const pending = page.waitForResponse(r => r.url().endsWith("/bank-import/confirm") && r.request().method() === "POST");
  await page.getByRole("button", { name: "Подтвердить импорт", exact: true }).click();
  const confirmed = await pending;
  expect(confirmed.ok(), await confirmed.text()).toBeTruthy();
  await expect(row).toContainText("Проведено");
  await row.getByRole("button", { name: "Открыть проводку" }).click();
  const card = page.getByRole("region", { name: "Карточка проводки" });
  await expect(card).toContainText("125.50");
  await card.screenshot({ path: testInfo.outputPath("bank-payment-entry.png") });
});
