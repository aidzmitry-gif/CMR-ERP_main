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
  await page.getByRole("button", { name: "Банк и платежи", exact: true }).click();
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
  const candidatesResponse = await page.request.get(`/api/accounting/organizations/${org.id}/bank-import/candidates`);
  expect(candidatesResponse.ok(), await candidatesResponse.text()).toBeTruthy();
  const candidates = (await candidatesResponse.json()).filter(
    (candidate: { source_snapshot: { source_external_id: string } }) => candidate.source_snapshot.source_external_id === reference,
  );
  expect(candidates).toHaveLength(1);
  expect(candidates[0].binding_status).toBe("own");
  const source = candidates[0].source_snapshot;
  expect(source).toMatchObject({ source_provider: "Synthetic bank", account_code: "SYNTHETIC-ACCOUNT", direction: "payment", amount: "125.50", currency: "BYN" });
  const accountsResponse = await page.request.get(`/api/accounting/organizations/${org.id}/accounts?on=2026-09-03`);
  expect(accountsResponse.ok(), await accountsResponse.text()).toBeTruthy();
  const bankAccounts = (await accountsResponse.json()).filter((account: { code: string }) => account.code === "51");
  expect(bankAccounts).toHaveLength(1);
  const mappingResponse = await page.request.post(`/api/accounting/organizations/${org.id}/bank-account-mappings`, {
    data: { provider: source.source_provider, external_account: source.account_code, currency: "BYN",
      valid_from: "2026-09-01", ledger_account_id: bankAccounts[0].id,
      dimensions: { bank_statement: source.ext_id }, evidence: "Synthetic E2E bank mapping evidence" },
  });
  expect(mappingResponse.status(), await mappingResponse.text()).toBe(201);
  const mappingQuery = new URLSearchParams({ provider: source.source_provider, external_account: source.account_code, currency: "BYN", at: "2026-09-03" });
  const mappingsResponse = await page.request.get(`/api/accounting/organizations/${org.id}/bank-account-mappings?${mappingQuery}`);
  expect(mappingsResponse.ok(), await mappingsResponse.text()).toBeTruthy();
  const mappings = await mappingsResponse.json();
  expect(mappings).toHaveLength(1);
  expect(mappings[0]).toMatchObject({ organization_id: org.id, ledger_account_id: bankAccounts[0].id });
  await row.getByRole("button", { name: "Выбрать", exact: true }).click();
  await expect(page.getByLabel("Счёт банка импорта")).toHaveValue("51");
  await expect(page.getByLabel("Счёт банка импорта")).toBeDisabled();
  await page.getByLabel("Выбрать счета вручную").check();
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
