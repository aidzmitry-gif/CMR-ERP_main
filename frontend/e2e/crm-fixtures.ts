import { expect, type APIRequestContext, type Browser, type Page } from "@playwright/test";
import { randomUUID } from "node:crypto";
import { execFileSync } from "node:child_process";
import { resolve } from "node:path";

export type SyntheticCounterparty = { id: number; name: string; unp: string; assignedClientId?: number };
export type SyntheticCrmClient = { id: number; name: string; owner_id: number; counterparty_id: number };
export type SyntheticDeal = {
  id: number; number: string; title: string; counterparty: string; counterparty_id: number;
  crm_client_id: number; owner_id: number; stage: string; amount: number;
  next_step?: string | null; next_step_at?: string | null; ship_deadline?: string | null; expected_close_date?: string | null;
};
export type InvoiceFixture = {
  organization: number; deal: number; client: number; buyer: number; buyer_name: string; buyer_unp: string; item: number | null;
  sku: string | null; warehouse: string | null; loss_reason: string;
};

async function expectStatus(response: Awaited<ReturnType<APIRequestContext["post"]>>, status: number, action: string) {
  if (response.status() !== status) throw new Error(`${action}: HTTP ${response.status()} ${await response.text()}`);
  return response.json() as Promise<Record<string, unknown>>;
}

export async function createSyntheticCounterparty(
  browser: Browser, name: string, baseURL?: string, assignOwnerId?: number,
): Promise<SyntheticCounterparty> {
  const admin = await browser.newContext({
    storageState: "e2e/.auth/state.json",
    ...(baseURL ? { baseURL } : {}),
  });
  try {
    const unp = String(100_000_000 + (Date.now() % 800_000_000));
    const response = await admin.request.post("/api/system/mdm/counterparty", { data: {
      manual: {
        name, display_name: name, legal_name: name, unp,
        legal_address: `Synthetic registered address for ${name}`,
      },
    } });
    const row = await expectStatus(response, 201, "Create synthetic MDM counterparty");
    if (!Number.isSafeInteger(row.id) || Number(row.id) <= 0) throw new Error("MDM returned no counterparty ID");
    const counterparty: SyntheticCounterparty = { id: Number(row.id), name, unp };
    if (assignOwnerId !== undefined) {
      const client = await createSyntheticCrmClient(admin.request, counterparty, assignOwnerId);
      counterparty.assignedClientId = client.id;
    }
    return counterparty;
  } finally {
    await admin.close();
  }
}

export async function createSyntheticCrmClient(
  request: APIRequestContext, counterparty: SyntheticCounterparty, ownerId: number, requestKey = `client-${randomUUID()}`,
): Promise<SyntheticCrmClient> {
  const assigned = counterparty.assignedClientId;
  const response = assigned === undefined ? await request.post("/api/sales/clients", { data: {
    counterparty_id: counterparty.id, owner_id: ownerId, request_key: requestKey,
  } }) : await request.get(`/api/sales/clients/${assigned}`);
  const client = await expectStatus(response, assigned === undefined ? 201 : 200, "Resolve synthetic MDM-linked CRM client");
  if (client.source !== "crm" || !Number.isSafeInteger(client.id) || client.counterparty_id !== counterparty.id
    || client.owner_id !== ownerId || client.name !== counterparty.name
    || (assigned !== undefined && client.id !== assigned)) {
    throw new Error("CRM client response did not preserve the selected MDM and owner");
  }
  return client as SyntheticCrmClient;
}

export async function createSyntheticCrmDeal(
  request: APIRequestContext,
  counterparty: SyntheticCounterparty,
  input: {
    ownerId: number; number: string; title: string; amount?: number; shipDeadline?: string;
    nextStep?: string; nextStepAt?: string; expectedCloseDate?: string;
  },
): Promise<{ client: SyntheticCrmClient; deal: SyntheticDeal }> {
  const client = await createSyntheticCrmClient(request, counterparty, input.ownerId);
  const response = await request.post("/api/sales/deals", { data: {
    number: input.number, title: input.title, counterparty: client.name,
    counterparty_id: counterparty.id, crm_client_id: client.id, owner_id: client.owner_id,
    amount: input.amount ?? 0, ...(input.shipDeadline ? { ship_deadline: input.shipDeadline } : {}),
    ...(input.nextStep ? { next_step: input.nextStep } : {}),
    ...(input.nextStepAt ? { next_step_at: input.nextStepAt } : {}),
    ...(input.expectedCloseDate ? { expected_close_date: input.expectedCloseDate } : {}),
  } });
  const deal = await expectStatus(response, 201, "Create synthetic MDM-linked CRM deal");
  if (!Number.isSafeInteger(deal.id) || deal.crm_client_id !== client.id || deal.counterparty_id !== counterparty.id
    || deal.owner_id !== client.owner_id || deal.counterparty !== client.name) {
    throw new Error("Deal response did not preserve the selected CRM client, MDM ID, and owner");
  }
  return { client, deal: deal as SyntheticDeal };
}

export async function createDealFromMdmDirectory(
  page: Page,
  counterparty: SyntheticCounterparty,
  input: { ownerId: number; number: string; title: string; amount?: number },
): Promise<{ client: SyntheticCrmClient; deal: SyntheticDeal }> {
  await page.goto("/crm/deals");
  await expect(page.getByTestId("deals-client-ready")).toBeVisible();
  await page.getByRole("button", { name: /Создать сделку/ }).click();
  const form = page.locator("form.shadow-pop");
  await expect(form).toBeVisible();
  await form.getByPlaceholder("CRM-2024-0200").fill(input.number);
  await form.getByPlaceholder("Поставка ...").fill(input.title);
  await form.getByPlaceholder("Название или УНП").fill(counterparty.name);
  await form.getByRole("button", { name: "Найти", exact: true }).click();
  const selected = form.getByRole("list", { name: "Доступные контрагенты" }).getByRole("button")
    .filter({ hasText: counterparty.name }).filter({ hasText: `ID ${counterparty.id}` });
  await expect(selected).toBeVisible();
  await selected.click();
  const company = form.getByLabel("Компания", { exact: true });
  await expect(company).toHaveValue(counterparty.name);
  await expect(company).toHaveAttribute("readonly", "");
  const owner = form.getByLabel("Ответственный", { exact: true });
  await expect(owner).toBeVisible();
  await owner.selectOption(String(input.ownerId));
  await expect(owner).toHaveValue(String(input.ownerId));
  if (input.amount !== undefined) await form.getByLabel("Сумма, BYN", { exact: true }).fill(String(input.amount));

  const clientReply = page.waitForResponse((response) => response.url().endsWith("/api/sales/clients")
    && response.request().method() === "POST");
  const dealReply = page.waitForResponse((response) => response.url().endsWith("/api/sales/deals")
    && response.request().method() === "POST");
  await form.getByRole("button", { name: "Создать", exact: true }).click();
  const clientResponse = await clientReply;
  const client = await expectStatus(clientResponse, 201, "Link CRM client to selected MDM counterparty") as unknown as SyntheticCrmClient;
  const dealResponse = await dealReply;
  const deal = await expectStatus(dealResponse, 201, "Create deal from selected MDM counterparty") as unknown as SyntheticDeal;
  if (client.source !== "crm" || client.counterparty_id !== counterparty.id || client.owner_id !== input.ownerId
    || deal.crm_client_id !== client.id || deal.counterparty_id !== counterparty.id || deal.owner_id !== input.ownerId) {
    throw new Error("Saved deal did not preserve the selected CRM client, MDM ID, and owner");
  }
  return { client, deal };
}

export async function addSyntheticDealItem(
  page: Page, dealId: number, skuCode: "QA-STOCK" | "QA-ORDER",
): Promise<{ id: number; code: string; qty: number; unit_price: number }> {
  await page.goto(`/crm/deals/${dealId}`);
  const selector = page.getByRole("combobox", { name: "Номенклатура (справочник из 1С через MDM)" });
  const option = selector.locator("option").filter({ hasText: skuCode });
  await expect(option).toHaveCount(1);
  const skuId = await option.getAttribute("value");
  if (!skuId) throw new Error(`No MDM SKU ID for ${skuCode}`);
  await selector.selectOption(skuId);
  await page.getByRole("spinbutton", { name: "Количество новой позиции", exact: true }).fill("2");
  await page.getByLabel("Цена за единицу новой позиции", { exact: true }).fill("125.50");
  const created = page.waitForResponse((response) => response.url().endsWith(`/deals/${dealId}/items`)
    && response.request().method() === "POST");
  await page.getByRole("button", { name: "Добавить", exact: true }).first().click();
  await expectStatus(await created, 201, "Create deal item through the UI");
  const readback = await page.request.get(`/api/sales/deals/${dealId}/items`);
  const rows = await expectStatus(readback, 200, "Read back UI-created deal item");
  if (!Array.isArray(rows)) throw new Error("Deal item readback was not a list");
  const item = rows.find((row) => row && typeof row === "object" && (row as Record<string, unknown>).code === skuCode) as Record<string, unknown> | undefined;
  if (!item || !Number.isSafeInteger(item.id) || typeof item.qty !== "number" || typeof item.unit_price !== "number") {
    throw new Error("UI-created deal item was missing its persisted ID, quantity, or price");
  }
  return { id: Number(item.id), code: skuCode, qty: item.qty, unit_price: item.unit_price };
}

export async function seedInvoiceE2E(
  page: Page, dealId: number, itemId: number | null, reserveMode: "stock" | "on_order" | null,
  options: { physicalShipment?: boolean; foreignBookReader?: boolean } = {},
): Promise<InvoiceFixture> {
  const { physicalShipment = false, foreignBookReader = false } = options;
  const actor = (await page.context().cookies()).find((cookie) => cookie.name === "aios_actor")?.value;
  if (!actor) throw new Error("The authenticated E2E actor cookie is missing");
  const command = JSON.stringify({
    deal_id: dealId, actor, item_id: itemId, reserve_mode: reserveMode,
    physical_shipment: physicalShipment, foreign_book_reader: foreignBookReader,
  });
  const output = execFileSync(process.env.E2E_PYTHON ?? "python", ["-m", "scripts.seed_invoice_e2e"], {
    cwd: resolve(process.cwd(), ".."), input: command,
    env: { ...process.env, AIOS_E2E_SEED: "1" }, encoding: "utf8",
  });
  const value = JSON.parse(output) as InvoiceFixture;
  if (!Number.isSafeInteger(value.organization) || !Number.isSafeInteger(value.deal) || value.deal !== dealId
    || !Number.isSafeInteger(value.client) || !Number.isSafeInteger(value.buyer)
    || typeof value.buyer_name !== "string" || !value.buyer_name.trim()
    || typeof value.buyer_unp !== "string" || !value.buyer_unp.trim()
    || (itemId !== null && value.item !== itemId)
    || (itemId === null && value.item !== null)
    || typeof value.loss_reason !== "string") {
    throw new Error("Invoice E2E seed did not bind the requested CRM deal and item");
  }
  if (itemId !== null) {
    if (!value.sku || (reserveMode === "stock" && value.warehouse !== "E2E-W")) {
      throw new Error("Invoice E2E seed returned incomplete stock fixture identity");
    }
    const profileData = {
      source_key: `e2e-seller-${randomUUID()}`, expected_revision: 0, effective_from: "2026-01-01",
      currency: "BYN", address: "Synthetic seller address", account: "TEST ACCOUNT", bank: "TEST BANK",
      bik: "TEST BIK", director: "Synthetic director", evidence: "Synthetic E2E approved seller profile", confirmed: true,
    };
    const endpoint = `/api/accounting/organizations/${value.organization}/seller-profiles`;
    if (actor === "e2e_owner") {
      const denied = await page.request.post(endpoint, { data: profileData });
      expect(denied.status()).toBe(403);
      expect(await denied.json()).toEqual({ detail: "Нет доступа к модулю: accounting" });
    }
    const browser = page.context().browser();
    if (!browser) throw new Error("Synthetic accounting preparation requires the test browser");
    const admin = await browser.newContext({
      baseURL: new URL(page.url()).origin, storageState: "e2e/.auth/state.json",
    });
    try {
      const response = await admin.request.post(endpoint, { data: profileData });
      const profile = await expectStatus(response, 201, "Create synthetic seller profile");
      expect(profile).toMatchObject({ organization_id: value.organization, revision: 1,
        effective_from: profileData.effective_from, actor: "kharkovich_d",
        seller: { currency: "BYN", address: profileData.address, account: profileData.account } });
      expect(profile.profile_id).toBeGreaterThan(0);
      expect(profile.digest).toEqual(expect.stringMatching(/^[a-f0-9]{64}$/));
      const current = await admin.request.get(`/api/accounting/organizations/${value.organization}/seller-profile?on=2026-09-10&currency=BYN`);
      expect(current.status()).toBe(200);
      expect(await current.json()).toEqual(profile);
    } finally { await admin.close(); }
  }
  return value;
}

export async function prepareInvoiceWizard(
  page: Page, fixture: InvoiceFixture, mode: "stock" | "on_order",
): Promise<void> {
  if (fixture.item === null) throw new Error("Invoice issuance requires a selected UI-created deal item");
  if (mode === "on_order") {
    await page.getByRole("checkbox", { name: "Под заказ — без резерва", exact: true }).check();
  }
  await page.getByRole("button", { name: "Сформировать", exact: true }).click();
  await page.getByRole("dialog", { name: new RegExp(`Выпуск счёта · сделка #${fixture.deal}`) }).waitFor();
  await page.getByLabel("Юрлицо", { exact: true }).selectOption(String(fixture.organization));
  await page.getByText("Проверить принадлежность", { exact: true }).click();
  await page.getByText("Продолжить к счёту", { exact: true }).click();
  await expect(page.getByLabel("Режим выпуска", { exact: true })).toHaveValue(mode);
  for (const [label, value] of [
    ["Валюта", "BYN"], ["Дата счёта", "2026-09-10"], ["Действителен до", "2026-09-15"],
    [`Цена строки ${fixture.item}`, "125.50"], [`Ставка строки ${fixture.item}`, "20.00"],
    ["Основание цен и ставок", "Synthetic negotiated price and explicitly reviewed VAT rate"],
  ]) {
    await page.getByLabel(label, { exact: true }).fill(value);
  }
  await page.getByText("Получить предпросмотр", { exact: true }).click();
  await expect(page.getByRole("heading", { name: "Проверьте реквизиты и суммы", exact: true })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Проверьте реквизиты и суммы", exact: true }).locator("..").getByText(`Покупатель: ${fixture.buyer_name} · УНП ${fixture.buyer_unp} · #${fixture.buyer}`)).toBeVisible();
  await expect(page.getByText("Всего: 301.20 BYN", { exact: true })).toBeVisible();
  if (mode === "on_order") {
    await page.getByRole("checkbox", { name: "Подтверждаю выпуск без резерва и проверенные данные счёта", exact: true }).check();
    return;
  }
  if (fixture.warehouse !== "E2E-W") throw new Error("Stock invoice seed has no synthetic physical warehouse");
  await page.getByLabel("Склад распределения 1", { exact: true }).selectOption(fixture.warehouse);
  await page.getByLabel("Количество распределения 1", { exact: true }).fill("2.00");
  await page.getByLabel("Основание полноты физического журнала", { exact: true })
    .fill("Synthetic opening physical stock: 10 units, no earlier reservations");
  await page.getByRole("checkbox", { name: /Подтверждаю полноту физического журнала для выбранных складов/ }).check();
}
