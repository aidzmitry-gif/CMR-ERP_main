import { execFileSync } from "node:child_process";
import { expect, test } from "@playwright/test";
import { configuredOrganization } from "./fixtures";

test("строка списания проходит из формы выписки в проводку один раз", async ({ page }, testInfo) => {
  const stamp = Date.now();
  const org = await configuredOrganization(page);
  const actor = (await page.context().cookies()).find(cookie => cookie.name === "aios_actor")?.value;
  expect(actor).toBeTruthy();
  const fixture = JSON.parse(execFileSync(process.env.E2E_PYTHON ?? "python", ["e2e/seed_bank_import.py"], {
    input: JSON.stringify({ organization_id: org.id, actor }), env: { ...process.env, AIOS_E2E_SEED: "1" },
    encoding: "utf8", timeout: 30000,
  })) as { organization_id: number; ext_id: string };
  expect(fixture.organization_id).toBe(org.id);
  const accountInput = { code: "60", title: "Поставщики", category: "liability", cash: false,
    valid_from: "2026-01-01", required_dimensions: [], currency_tracking: false,
    quantity_tracking: false, normative_ref: "Synthetic browser test only" };
  const accounts = await page.request.get(`/api/accounting/organizations/${org.id}/accounts?on=2026-09-03`);
  expect(accounts.ok(), await accounts.text()).toBeTruthy();
  const payable = (await accounts.json()).filter((account: { code: string }) => account.code === "60");
  expect(payable.length).toBeLessThanOrEqual(1);
  if (payable.length) expect(payable[0]).toMatchObject(accountInput);
  else {
    const created = await page.request.post(`/api/accounting/organizations/${org.id}/accounts`, { data: accountInput });
    expect(created.status(), await created.text()).toBe(201);
    expect(await created.json()).toMatchObject(accountInput);
  }
  const bank = (await accounts.json()).filter((account: { code: string }) => account.code === "51");
  expect(bank).toHaveLength(1);
  expect(bank[0]).toMatchObject({ code: "51", title: "Банк", category: "asset", cash: true,
    valid_from: "2026-01-01", required_dimensions: ["bank_statement"], currency_tracking: false, quantity_tracking: false });
  expect(Number.isSafeInteger(bank[0].id) && bank[0].id > 0).toBe(true);
  const mappingInput = { provider: "Synthetic bank", external_account: "SYNTHETIC-ACCOUNT", currency: "BYN",
    valid_from: "2026-09-03", ledger_account_id: bank[0].id,
    dimensions: { bank_statement: "SYNTHETIC-E2E-BANK" }, evidence: "Synthetic E2E account mapping" };
  const mappingKey = { provider: mappingInput.provider, external_account: mappingInput.external_account, currency: "BYN" };
  const history = await page.request.get(`/api/accounting/organizations/${org.id}/bank-account-mappings?${new URLSearchParams({ ...mappingKey, include_closed: "true" })}`);
  expect(history.ok(), await history.text()).toBeTruthy();
  const mappings = await history.json();
  expect(Array.isArray(mappings)).toBe(true);
  expect(mappings.length).toBeLessThanOrEqual(1);
  let mapping = mappings[0];
  if (!mapping) {
    const created = await page.request.post(`/api/accounting/organizations/${org.id}/bank-account-mappings`, { data: mappingInput });
    expect(created.status(), await created.text()).toBe(201);
    mapping = await created.json();
  }
  expect(mapping).toMatchObject({ ...mappingInput, organization_id: org.id, valid_to: null, actor });
  expect(Number.isSafeInteger(mapping.mapping_id) && mapping.mapping_id > 0).toBe(true);
  expect(Number.isSafeInteger(mapping.version) && mapping.version > 0).toBe(true);
  expect(mapping.digest).toMatch(/^[a-f0-9]{64}$/);
  const effectiveMapping = await page.request.get(`/api/accounting/organizations/${org.id}/bank-account-mappings?${new URLSearchParams({ ...mappingKey, at: "2026-09-03" })}`);
  expect(effectiveMapping.ok(), await effectiveMapping.text()).toBeTruthy();
  expect(await effectiveMapping.json()).toEqual([mapping]);
  await page.goto("/erp/accounting");
  await expect(page.getByText(`${org.name} · УНП ${org.unp}`, { exact: true })).toBeVisible();
  await expect(page.getByLabel("Организация", { exact: true })).toHaveCount(0);
  await page.getByRole("navigation", { name: "Разделы бухгалтерии", exact: true })
    .getByRole("button", { name: "Банк и платежи", exact: true }).click();
  await page.getByRole("navigation", { name: "Страницы раздела Банк и платежи", exact: true })
    .getByRole("button", { name: "Импорт выписки", exact: true }).click();
  await page.getByRole("checkbox", { name: "Выбрать счета вручную", exact: true }).check();
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
  await expect(page.getByLabel("Счёт банка импорта")).toHaveValue("51");
  await expect(page.getByLabel("Счёт банка импорта")).toBeDisabled();
  await page.getByLabel("Счёт расчётов импорта").selectOption("60");
  await expect(page.getByRole("button", { name: "Рассчитать проводки", exact: true })).toBeEnabled();
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
