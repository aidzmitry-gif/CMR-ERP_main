import { execFileSync } from "node:child_process";
import { resolve } from "node:path";
import { expect, test } from "@playwright/test";

// Критический путь карточки: создать сделку → проверить реквизиты → выпустить счёт ERP с резервом.
// Самодостаточно (на пустой доске CI карточек нет — создаём свою).
test("карточка сделки: выпуск счёта ERP с резервом", async ({ page }, testInfo) => {
  const clientName = `ООО E2E-Документ ${Date.now()}`;
  await page.goto("/crm/deals");
  // Кнопка SSR-видима до подключения React onClick; ждём завершения гидрации.
  await expect(page.getByTestId("deals-client-ready")).toBeVisible();

  await page.getByRole("button", { name: /Создать сделку/ }).click();
  const form = page.locator("form.shadow-pop");
  await expect(form).toBeVisible();
  await form.getByPlaceholder("CRM-2024-0200").fill(`E2E-DOC-${Date.now()}`);
  await form.getByPlaceholder("ООО ...").fill(clientName);
  await form.getByPlaceholder("Поставка ...").fill("Поставка для E2E");
  await form.getByRole("button", { name: "Создать" }).click();

  // открыть карточку созданной сделки (double-click: single-click открывает drawer-preview,
  // double-click — router.push на полную карточку /crm/deals/[id] с вкладкой Документы)
  await page.getByText(clientName).first().dblclick();
  await expect(page.getByText("Документы")).toBeVisible();

  const dealId = Number(new URL(page.url()).pathname.split("/").pop());
  const actor = (await page.context().cookies()).find(cookie => cookie.name === "aios_actor")?.value;
  expect(actor).toBeTruthy();
  const fixture = JSON.parse(execFileSync(process.env.E2E_PYTHON ?? "python", ["-m", "scripts.seed_invoice_e2e"], {
    cwd: resolve(process.cwd(), ".."),
    input: JSON.stringify({ deal_id: dealId, actor }),
    env: { ...process.env, AIOS_E2E_SEED: "1" }, encoding: "utf8",
  })) as { organization: number; item: number; sku: string; buyer: number };
  const profile = await page.request.post(`/api/accounting/organizations/${fixture.organization}/seller-profiles`, { data: {
    source_key: `e2e-seller-${dealId}`, expected_revision: 0, effective_from: "2026-01-01",
    currency: "BYN", address: "Synthetic seller address", account: "TEST ACCOUNT", bank: "TEST BANK",
    bik: "TEST BIK", director: "Synthetic director", evidence: "Synthetic E2E approved seller profile", confirmed: true,
  } });
  expect(profile.status(), await profile.text()).toBe(201);
  await page.getByRole("button", { name: /Сформировать/ }).click();
  await page.getByLabel("Юрлицо", { exact: true }).selectOption(String(fixture.organization));
  await page.getByText("Проверить принадлежность", { exact: true }).click();
  await page.getByText("Продолжить к счёту", { exact: true }).click();
  for (const [label, value] of [["Валюта", "BYN"], ["Дата счёта", "2026-09-10"], ["Действителен до", "2026-09-15"],
    [`Цена строки ${fixture.item}`, "100.00"], [`Ставка строки ${fixture.item}`, "20.00"], ["Основание цен и ставок", "Synthetic negotiated price and VAT for E2E"]]) {
    await page.getByLabel(label, { exact: true }).fill(value);
  }
  await page.getByText("Получить предпросмотр", { exact: true }).click();
  await expect(page.getByText("Всего: 240.00 BYN", { exact: true })).toBeVisible();
  await page.getByLabel("Склад распределения 1", { exact: true }).selectOption("E2E-W");
  await page.getByLabel("Количество распределения 1", { exact: true }).fill("2.00");
  await page.getByLabel("Основание полноты физического журнала", { exact: true }).fill("Synthetic opening physical stock: 10 units, no earlier reservations");
  await page.getByRole("checkbox", { name: /Подтверждаю полноту физического журнала/ }).check();
  await page.getByRole("button", { name: "Выпустить счёт и зарезервировать", exact: true }).click();
  await expect(page.getByRole("link", { name: "Открыть оригинал", exact: true })).toBeVisible();
  const documents = await page.request.get(`/api/sales/deals/${dealId}/documents`);
  expect(documents.ok()).toBeTruthy();
  const invoices = (await documents.json()).filter((doc: { kind: string }) => doc.kind === "invoice");
  expect(invoices).toHaveLength(1);
  expect(invoices[0]).toMatchObject({ status: "issued", reserve_status: "reserved", onec_ref: null, amount: 240 });
  const original = await page.request.get(`/api/sales/documents/${invoices[0].id}/render`);
  expect(original.ok()).toBeTruthy();
  expect(await original.text()).toContain("E2E invoice buyer");
  await page.goto(`/crm/deals/${dealId}?org=${fixture.organization}&invoice=${invoices[0].id}#document-register`);
  const dealRegister = page.getByRole("region", { name: "Реестр документов сделки", exact: true });
  await expect(dealRegister.getByRole("button", { name: "Аннулирование счёта", exact: true })).toBeVisible();
  await expect(dealRegister.getByRole("button", { name: "Фактическая отгрузка и акты", exact: true })).toBeVisible();
  await expect(dealRegister.getByText(/Зарезервирован/).first()).toBeVisible();
  await dealRegister.screenshot({ path: testInfo.outputPath("deal-document-register.png") });
  await page.goto(`/erp/spravochniki/counterparty/${fixture.buyer}`);
  const clientRegister = page.getByRole("region", { name: "Документы клиента по юрлицу", exact: true });
  await clientRegister.getByLabel("Юрлицо документов клиента", { exact: true }).selectOption(String(fixture.organization));
  await expect(clientRegister.getByRole("article", { name: `Документ клиента ${invoices[0].id}`, exact: true })).toBeVisible();
  await clientRegister.screenshot({ path: testInfo.outputPath("client-document-register.png") });
});
