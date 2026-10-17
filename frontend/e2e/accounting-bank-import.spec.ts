import { execFileSync } from "node:child_process";
import { expect, test } from "@playwright/test";

test("импорт выписки сохраняет аналитику из формы", async ({ page }, testInfo) => {
  const stamp = Date.now();
  const response = await page.request.post("/api/accounting/organizations", { data: { name: `E2E bank dimensions ${stamp}`, unp: String(stamp).slice(-9) } });
  expect(response.ok(), await response.text()).toBeTruthy();
  const org = await response.json();
  execFileSync("python", ["e2e/seed_bank_import.py", String(org.id)], { timeout: 30000 });
  const candidatesResponse = await page.request.get(`/api/accounting/organizations/${org.id}/bank-import/candidates`);
  expect(candidatesResponse.ok(), await candidatesResponse.text()).toBeTruthy();
  const candidates = (await candidatesResponse.json()).filter(
    (candidate: { source_snapshot: { ext_id: string } }) => candidate.source_snapshot.ext_id === `E2E-BANK-${org.id}`,
  );
  expect(candidates).toHaveLength(1);
  expect(candidates[0].binding_status).toBe("own");
  const source = candidates[0].source_snapshot;
  expect(source).toMatchObject({ source_provider: "synthetic-bank", account_code: `E2E-ACCOUNT-${org.id}`, direction: "receipt", amount: "120.00", currency: "BYN" });
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
  await page.goto("/erp/accounting");
  await page.getByLabel("Организация", { exact: true }).selectOption(String(org.id));
  await page.getByRole("button", { name: "Банк и платежи", exact: true }).click();
  await page.getByRole("button", { name: "Импорт выписки", exact: true }).click();
  const row = page.getByRole("row").filter({ has: page.getByText(`E2E-BANK-${org.id}`, { exact: true }) });
  await expect(row).toHaveCount(1);
  await row.getByRole("button", { name: "Выбрать", exact: true }).click();
  await expect(page.getByLabel("Счёт банка импорта")).toHaveValue("51");
  await expect(page.getByLabel("Счёт банка импорта")).toBeDisabled();
  await page.getByLabel("Выбрать счета вручную").check();
  await page.getByLabel("Счёт расчётов импорта").selectOption("62");
  await page.getByLabel("Расчёты: counterparty").fill("BUYER-E2E");
  await page.getByLabel("Расчёты: contract").fill("CONTRACT-E2E");
  await page.getByRole("button", { name: "Рассчитать проводки", exact: true }).click();
  await expect(page.getByText("contract: CONTRACT-E2E", { exact: true })).toBeVisible();
  await page.screenshot({ path: testInfo.outputPath("bank-analytics-preview.png"), fullPage: true });
  const confirmed = page.waitForResponse(r => r.url().endsWith("/bank-import/confirm") && r.request().method() === "POST");
  await page.getByRole("button", { name: "Подтвердить импорт", exact: true }).click();
  const saved = await confirmed;
  expect(saved.ok(), await saved.text()).toBeTruthy();
  const receipt = await saved.json();
  const entryResponse = await page.request.get(`/api/accounting/organizations/${org.id}/entries/${receipt.entry_id}`);
  expect(entryResponse.ok(), await entryResponse.text()).toBeTruthy();
  const entry = await entryResponse.json();
  expect(entry.lines.find((line: { account_code: string }) => line.account_code === "62").dimensions).toMatchObject({ counterparty: "BUYER-E2E", contract: "CONTRACT-E2E" });
  await expect(row).toContainText("Проведено");
  await row.getByRole("button", { name: "Открыть проводку" }).click();
  const card = page.getByRole("region", { name: "Карточка проводки" });
  await expect(card.getByRole("heading", { name: `Операция № ${receipt.entry_id}` })).toBeVisible();
  await expect(card).toContainText("CONTRACT-E2E");
  await card.screenshot({ path: testInfo.outputPath("bank-entry-card.png") });
});
