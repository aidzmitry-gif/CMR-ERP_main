import { randomUUID } from "node:crypto";
import { execFileSync } from "node:child_process";
import { resolve } from "node:path";
import { expect, type Page, type Locator } from "@playwright/test";

const sellerUnp = "190000007";
type Organization = { id: number; name: string; unp: string };
export type Buyer = { id: number; name: string; unp: string };

export async function assertSyntheticBackend(page: Page) {
  const response = await page.request.get("/api/__e2e_isolation");
  expect(response.ok(), await response.text()).toBe(true);
  expect(await response.json()).toMatchObject({ chain: "CRM-READY-001-H04-E2E", synthetic_only: true,
    background_workers: false, email_enabled: false, egress_guard: true });
}

export async function configuredOrganization(page: Page): Promise<Organization> {
  await assertSyntheticBackend(page);
  const response = await page.request.get("/api/system/instance-organization");
  expect(response.ok(), await response.text()).toBe(true);
  const context = await response.json();
  expect(context.configuration).toBe("AIOS_SELLER_UNP");
  expect(context.organization.unp).toBe(sellerUnp);
  expect(Number.isSafeInteger(context.organization.id) && context.organization.id > 0).toBe(true);
  return context.organization;
}

export async function ensureConfiguredOrganization(page: Page) {
  await assertSyntheticBackend(page);
  const response = await page.request.get("/api/accounting/organizations");
  expect(response.ok(), await response.text()).toBe(true);
  const organizations = await response.json() as Organization[];
  expect(Array.isArray(organizations)).toBe(true);
  const matches = organizations.filter(org => org.unp === sellerUnp);
  expect(matches.length).toBeLessThanOrEqual(1);
  let organization = matches[0];
  if (!organization) {
    const created = await page.request.post("/api/accounting/organizations", {
      data: { name: "E2E installation seller", unp: sellerUnp },
    });
    expect(created.status(), await created.text()).toBe(201);
    organization = await created.json();
  }
  expect(await configuredOrganization(page)).toEqual({ id: organization.id, name: organization.name, unp: organization.unp });
}

export async function createBuyer(page: Page, name: string): Promise<Buyer> {
  await assertSyntheticBackend(page);
  const unp = String(800000000 + Number.parseInt(randomUUID().slice(0, 7), 16) % 99999999);
  const response = await page.request.post("/api/system/mdm/counterparty", {
    data: { manual: { name, unp, legal_address: "Synthetic E2E buyer legal address" }, contacts: [] },
  });
  expect(response.status(), await response.text()).toBe(201);
  const buyer = await response.json();
  expect(Number.isSafeInteger(buyer.id) && buyer.id > 0).toBe(true);
  return { id: buyer.id, name, unp };
}

export async function createDealThroughUI(page: Page, buyer: Buyer, number: string) {
  await page.goto("/crm/deals");
  await expect(page.getByTestId("deals-client-ready")).toBeVisible();
  await page.getByRole("button", { name: /Создать сделку/ }).click();
  const form = page.locator("form.shadow-pop");
  await form.getByPlaceholder("CRM-2024-0200").fill(number);
  await form.getByPlaceholder("Название или УНП").fill(buyer.unp);
  await form.getByRole("button", { name: "Найти", exact: true }).click();
  const option = form.getByRole("list", { name: "Доступные контрагенты" }).getByRole("button")
    .filter({ hasText: `ID ${buyer.id}` }).filter({ hasText: buyer.name });
  await expect(option).toHaveCount(1);
  await option.click();
  const staff = await page.request.get("/api/system/users/crm-staff");
  expect(staff.ok(), await staff.text()).toBe(true);
  expect((await staff.json()).some((row: { employee_id: number }) => row.employee_id === 2901)).toBe(true);
  await form.getByRole("combobox", { name: "Ответственный", exact: true }).selectOption("2901");
  await form.getByPlaceholder("Поставка ...").fill("Поставка для E2E");
  const created = page.waitForResponse(r => new URL(r.url()).pathname === "/api/sales/deals" && r.request().method() === "POST");
  await form.getByRole("button", { name: "Создать", exact: true }).click();
  const response = await created;
  expect(response.status(), await response.text()).toBe(201);
  const deal = await response.json();
  expect(deal).toMatchObject({ counterparty_id: buyer.id, owner_id: 2901 });
  await expect(form).not.toBeVisible();
  return deal as { id: number };
}

export async function createDealFromBuyer(page: Page, buyer: Buyer, number: string) {
  await assertSyntheticBackend(page);
  const linked = await page.request.post("/api/sales/clients", { data: {
    counterparty_id: buyer.id, owner_id: 2901, request_key: randomUUID(),
  } });
  expect(linked.status(), await linked.text()).toBe(201);
  const client = await linked.json();
  expect(client).toMatchObject({ source: "crm", counterparty_id: buyer.id, owner_id: 2901 });
  const created = await page.request.post("/api/sales/deals", { data: {
    number, title: "Synthetic E2E deal", counterparty: buyer.name, crm_client_id: client.id, owner_id: 2901,
  } });
  expect(created.status(), await created.text()).toBe(201);
  const deal = await created.json();
  expect(deal).toMatchObject({ counterparty_id: buyer.id, owner_id: 2901 });
  return deal as { id: number };
}

export type InvoiceFixture = { organization: number; buyer: number; sku: string; sku_id: number; loss_reason: string; item: number };
type Seeded = Omit<InvoiceFixture, "item">;
export type InvoiceDocument = { id: number; number: string; version: number; content_sha256: string;
  amount: number; status: string; reserve_status: string; reserve_mode: "stock" | "on_order" };

export async function assignBuyerToOwner(chief: Page, buyer: Buyer) {
  await assertSyntheticBackend(chief);
  const response = await chief.request.post("/api/sales/clients", { data: {
    counterparty_id: buyer.id, owner_id: 2901, request_key: randomUUID(),
  } });
  expect(response.status(), await response.text()).toBe(201);
  const client = await response.json();
  expect(Number.isSafeInteger(client.id) && client.id > 0).toBe(true);
  expect(client).toMatchObject({ source: "crm", owner_id: 2901, counterparty_id: buyer.id,
    name: buyer.name, unp: buyer.unp });
  return client as { id: number; name: string; counterparty_id: number };
}

export async function seedInvoiceFacts(chief: Page, dealId: number, buyer: Buyer): Promise<Seeded> {
  let seedExecutable = process.env.E2E_PYTHON ?? "python";
  let seedArgs = ["-m", "scripts.seed_invoice_e2e"];
  const dockerKeys = ["E2E_DOCKER_BIN", "E2E_DOCKER_CONTAINER", "E2E_DOCKER_OWNER", "E2E_DOCKER_IMAGE"] as const;
  if (dockerKeys.some(key => process.env[key] !== undefined)) {
    const docker = process.env.E2E_DOCKER_BIN;
    const container = process.env.E2E_DOCKER_CONTAINER;
    const owner = process.env.E2E_DOCKER_OWNER;
    const image = process.env.E2E_DOCKER_IMAGE;
    if (!docker || !container || !owner || !/^[a-f0-9]{32}$/.test(owner) ||
        container !== `erp-ready-xk5-${owner}` ||
        image !== "sha256:d31d7d7e69812ff3f7dc8eb40f09e1249baedb6fb2a595f4d14df33f6becb5a5") {
      throw new Error("Complete owner-bound E2E Docker configuration is required");
    }
    const identity = execFileSync(docker, ["inspect", "--type", "container", "--format",
      '{{.Id}}|{{index .Config.Labels "crm.erp-ready.owner"}}|{{.Image}}', container],
    { encoding: "utf8" }).trim().split("|");
    if (identity.length !== 3 || !/^[a-f0-9]{64}$/.test(identity[0]) || identity[1] !== owner || identity[2] !== image) {
      throw new Error("E2E Docker container identity does not match");
    }
    seedExecutable = docker;
    seedArgs = ["exec", "-i", "-w", "/work", "-e", "AIOS_E2E_SEED=1", "-e", "AIOS_SELLER_UNP=190000007",
      identity[0], "python", "-m", "scripts.seed_invoice_e2e"];
  }
  await ensureConfiguredOrganization(chief);
  const org = await configuredOrganization(chief);
  const actor = (await chief.context().cookies()).find(c => c.name === "aios_actor")?.value;
  expect(actor).toBeTruthy();
  const seeded = JSON.parse(execFileSync(seedExecutable, seedArgs, {
    cwd: resolve(process.cwd(), ".."), input: JSON.stringify({ deal_id: dealId, actor,
      organization_id: org.id, buyer_id: buyer.id }),
    env: { ...process.env, AIOS_E2E_SEED: "1" }, encoding: "utf8",
  })) as Seeded;
  expect(seeded).toMatchObject({ organization: org.id, buyer: buyer.id, sku: `E2E-INV-${dealId}` });
  const versions = await chief.request.get(`/api/accounting/organizations/${org.id}/seller-profiles`);
  expect(versions.ok(), await versions.text()).toBe(true);
  const revisions = (await versions.json()).map((v: { revision: number }) => v.revision);
  expect(revisions.every((n: number) => Number.isSafeInteger(n) && n > 0)).toBe(true);
  const profile = await chief.request.post(`/api/accounting/organizations/${org.id}/seller-profiles`, { data: {
    source_key: `e2e-seller-${dealId}`, expected_revision: Math.max(0, ...revisions), effective_from: "2026-01-01",
    currency: "BYN", address: "Synthetic seller address", account: "TEST ACCOUNT", bank: "TEST BANK",
    bik: "TEST BIK", director: "Synthetic director", evidence: "Synthetic E2E approved seller profile", confirmed: true,
  } });
  expect(profile.status(), await profile.text()).toBe(201);
  return seeded;
}

export async function addInvoiceItemUI(page: Page, dealId: number, seeded: Seeded, price: "100.00" | "125.50"): Promise<InvoiceFixture> {
  await page.goto(`/crm/deals/${dealId}`);
  const select = page.getByRole("combobox", { name: "Номенклатура (справочник из 1С через MDM)" });
  const option = select.locator("option").filter({ hasText: seeded.sku });
  await expect(option).toHaveCount(1);
  await select.selectOption((await option.getAttribute("value"))!);
  await page.getByRole("spinbutton", { name: "Количество новой позиции", exact: true }).fill("2");
  await page.getByLabel("Цена за единицу новой позиции", { exact: true }).fill(price);
  const added = page.waitForResponse(r => new URL(r.url()).pathname === `/api/sales/deals/${dealId}/items` && r.request().method() === "POST");
  await page.getByRole("button", { name: "Добавить", exact: true }).first().click();
  const reply = await added;
  expect(reply.status(), await reply.text()).toBe(201);
  const row = await reply.json();
  expect(Number.isSafeInteger(row.id) && row.id > 0).toBe(true);
  expect(Number(row.qty)).toBe(2);
  expect(row.sku_id).toBe(seeded.sku_id);
  return { ...seeded, item: row.id };
}

export async function confirmInvoicePartiesUI(chief: Page, dealId: number, fixture: InvoiceFixture, buyer: Buyer) {
  await chief.goto(`/crm/deals/${dealId}`);
  await chief.getByRole("button", { name: /Сформировать/ }).click();
  const dialog = chief.getByRole("dialog", { name: /Выпуск счёта/ });
  const configured = await configuredOrganization(chief);
  expect(configured.id).toBe(fixture.organization);
  await expect(dialog.getByRole("region", { name: "Юрлицо установки", exact: true }))
    .toContainText(`${configured.name} · УНП ${configured.unp} · #${fixture.organization}`);
  await expect(dialog.getByLabel("Юрлицо", { exact: true })).toHaveCount(0);
  await dialog.getByRole("button", { name: "Проверить принадлежность", exact: true }).click();
  await dialog.getByRole("button", { name: "Подтвердить новую принадлежность", exact: true }).click();
  await dialog.getByLabel("Основание принадлежности организации", { exact: true }).fill("Synthetic exact installation and same deal evidence");
  await dialog.getByRole("button", { name: "Подтвердить организацию сделки", exact: true }).click();
  const binding = dialog.getByRole("region", { name: "Подтверждение клиента сделки", exact: true });
  await binding.getByLabel("Поиск покупателя в справочнике", { exact: true }).fill(buyer.unp);
  await expect(binding.getByLabel("Покупатель из справочника", { exact: true }).locator(`option[value="${buyer.id}"]`)).toHaveCount(1);
  await binding.getByLabel("Покупатель из справочника", { exact: true }).selectOption(String(buyer.id));
  await binding.getByRole("button", { name: "Просмотреть привязку клиента", exact: true }).click();
  await expect(binding.getByText(new RegExp(`Проверяемый клиент ID ${buyer.id}`))).toBeVisible();
  await binding.getByLabel("Основание привязки клиента", { exact: true }).fill("Synthetic API-created legal buyer confirmed for this exact CRM deal");
  await binding.getByRole("button", { name: "Подтвердить клиента сделки", exact: true }).click();
  await expect(dialog.getByText(`Покупатель: ${buyer.name} · УНП ${buyer.unp} · #${buyer.id}.`, { exact: true })).toBeVisible();
  await dialog.getByRole("button", { name: "Продолжить к счёту", exact: true }).click();
  const register = await chief.request.get(`/api/sales/organizations/${fixture.organization}/deals/${dealId}/document-register?after_id=0&limit=50`);
  expect(register.status(), await register.text()).toBe(200);
  expect((await register.json()).client_identity).toMatchObject({ status: "confirmed", counterparty_id: buyer.id });
  chief.once("dialog", value => value.accept());
  await dialog.getByRole("button", { name: "Закрыть", exact: true }).click();
  await expect(dialog).not.toBeVisible();
}

export async function prepareInvoiceUI(page: Page, dealId: number, fixture: InvoiceFixture, buyer: Buyer,
  mode: "stock" | "on_order", price: "100.00" | "125.50"): Promise<Locator> {
  await page.goto(`/crm/deals/${dealId}`);
  await page.getByRole("button", { name: /Сформировать/ }).click();
  const dialog = page.getByRole("dialog", { name: /Выпуск счёта/ });
  const configured = await configuredOrganization(page);
  expect(configured.id).toBe(fixture.organization);
  await expect(dialog.getByRole("region", { name: "Юрлицо установки", exact: true }))
    .toContainText(`${configured.name} · УНП ${configured.unp} · #${fixture.organization}`);
  await expect(dialog.getByLabel("Юрлицо", { exact: true })).toHaveCount(0);
  await dialog.getByRole("button", { name: "Проверить принадлежность", exact: true }).click();
  await expect(dialog.getByText(`Покупатель: ${buyer.name} · УНП ${buyer.unp} · #${buyer.id}.`, { exact: true })).toBeVisible();
  await dialog.getByRole("button", { name: "Продолжить к счёту", exact: true }).click();
  await dialog.getByLabel("Режим выпуска", { exact: true }).selectOption(mode);
  for (const [label, value] of [["Валюта", "BYN"], ["Дата счёта", "2026-09-10"], ["Действителен до", "2026-09-15"],
    [`Цена строки ${fixture.item}`, price], [`Ставка строки ${fixture.item}`, "20.00"],
    ["Основание цен и ставок", "Synthetic negotiated price and VAT for E2E"]]) {
    await dialog.getByLabel(label, { exact: true }).fill(value);
  }
  const previewReply = page.waitForResponse(r => new URL(r.url()).pathname === `/api/sales/deals/${dealId}/invoice-preview` && r.request().method() === "POST");
  await dialog.getByRole("button", { name: "Получить предпросмотр", exact: true }).click();
  const response = await previewReply;
  expect(response.status(), await response.text()).toBe(200);
  const preview = await response.json();
  expect(preview.buyer.counterparty_id).toBe(buyer.id);
  expect(preview.seller_profile.revision).toBeGreaterThan(0);
  expect(preview.lines).toHaveLength(1);
  expect(preview.lines[0]).toMatchObject({ sku_code: fixture.sku, qty: "2.00", vat_rate: "20.00" });
  await expect(dialog.getByText(`Всего: ${price === "100.00" ? "240.00" : "301.20"} BYN`, { exact: true })).toBeVisible();
  return dialog;
}

export async function issueInvoiceUI(page: Page, dealId: number, fixture: InvoiceFixture, buyer: Buyer,
  mode: "stock" | "on_order", price: "100.00" | "125.50"): Promise<InvoiceDocument> {
  const dialog = await prepareInvoiceUI(page, dealId, fixture, buyer, mode, price);
  if (mode === "stock") {
    await dialog.getByLabel("Склад распределения 1", { exact: true }).selectOption("E2E-W");
    await dialog.getByLabel("Количество распределения 1", { exact: true }).fill("2.00");
    await dialog.getByLabel("Основание полноты физического журнала", { exact: true }).fill("Synthetic opening physical stock 10, no earlier reservations");
    await dialog.getByRole("checkbox", { name: /Подтверждаю полноту физического журнала/ }).check();
  } else {
    await dialog.getByRole("checkbox", { name: "Подтверждаю выпуск без резерва и проверенные данные счёта", exact: true }).check();
  }
  const issued = page.waitForResponse(r => new URL(r.url()).pathname === `/api/sales/deals/${dealId}/documents` && r.request().method() === "POST");
  await dialog.getByRole("button", { name: mode === "stock" ? "Выпустить счёт и зарезервировать" : "Выпустить счёт под заказ", exact: true }).click();
  const reply = await issued;
  expect(reply.status(), await reply.text()).toBe(201);
  const receipt = await reply.json();
  expect(receipt.document).toMatchObject({ status: "issued", reserve_mode: mode,
    reserve_status: mode === "stock" ? "reserved" : "unreserved", amount: price === "100.00" ? 240 : 301.2 });
  expect(receipt.content_sha256).toMatch(/^[a-f0-9]{64}$/);
  await expect(dialog.getByRole("link", { name: "Открыть оригинал", exact: true })).toBeVisible();
  await dialog.getByRole("button", { name: "Готово", exact: true }).click();
  return receipt.document as InvoiceDocument;
}

export async function cancelInvoiceUI(chief: Page, dealId: number, fixture: InvoiceFixture,
  invoice: InvoiceDocument, loseReply = false) {
  await chief.goto(`/crm/deals/${dealId}?org=${fixture.organization}&invoice=${invoice.id}#document-register`);
  await chief.getByRole("region", { name: "Реестр документов сделки", exact: true })
    .getByRole("button", { name: "Аннулирование счёта", exact: true }).click();
  const panel = chief.getByRole("region", { name: "Аннулирование счёта", exact: true });
  await expect(panel.getByRole("button", { name: "Сохранить денежную сверку", exact: true })).toBeEnabled();
  await expect(panel.getByLabel("Начало денежной истории", { exact: true })).toHaveValue(/^\d{4}-\d{2}-\d{2}$/);
  await expect(panel.getByLabel("Конец денежной истории", { exact: true })).toHaveValue(/^\d{4}-\d{2}-\d{2}$/);
  await panel.getByLabel("Денежные источники и ссылки, по одному на строку", { exact: true }).fill("Synthetic isolated bank and cash ledgers; complete lifetime of this invoice");
  await panel.getByLabel("Основание денежной сверки", { exact: true }).fill("Synthetic database contains no receipts for this exact invoice");
  await panel.getByRole("checkbox", { name: "Проверены банк, касса и полная историческая оплата", exact: true }).check();
  const money = chief.waitForResponse(r => r.url().endsWith(`/invoices/${invoice.id}/money-reconciliation`) && r.request().method() === "POST");
  await panel.getByRole("button", { name: "Сохранить денежную сверку", exact: true }).click();
  expect((await money).status()).toBe(201);
  await panel.getByRole("button", { name: "Добавить внешний источник", exact: true }).click();
  await panel.getByLabel("Система или источник 1", { exact: true }).fill("Synthetic complete 1C and manual fulfillment history");
  await panel.getByLabel("Документ или ссылка 1", { exact: true }).fill(`Synthetic invoice ${invoice.id}: no external fulfillment, carrier orders or physical shipment`);
  await expect(panel.getByLabel("Проверено с 1", { exact: true })).toHaveValue(/^\d{4}-\d{2}-\d{2}$/);
  await expect(panel.getByLabel("Проверено по 1", { exact: true })).toHaveValue(/^\d{4}-\d{2}-\d{2}$/);
  await panel.getByRole("checkbox", { name: "Источник 1: отсутствие исполнения подтверждено", exact: true }).check();
  await panel.getByLabel("Основание сверки исполнения", { exact: true }).fill("Synthetic complete lifetime reviewed: no fulfilled warehouse, carrier or accounting source");
  await panel.getByRole("checkbox", { name: "Все источники исполнения выявлены и проверены", exact: true }).check();
  const reviewed = chief.waitForResponse(r => r.url().endsWith(`/invoices/${invoice.id}/fulfillment-review`) && r.request().method() === "POST");
  await panel.getByRole("button", { name: "Сохранить сверку исполнения", exact: true }).click();
  const review = await reviewed;
  expect(review.status(), await review.text()).toBe(201);
  const reviewReceipt = await review.json();
  expect(reviewReceipt).toMatchObject({ document_id: invoice.id, document_version: invoice.version,
    content_sha256: invoice.content_sha256, cancellation_authorized: false });
  await panel.getByLabel("Причина аннулирования", { exact: true }).fill("Synthetic customer declined the same invoice before fulfillment");
  await panel.getByRole("checkbox", { name: "Подтверждаю, что счёт больше не будет действителен", exact: true }).check();
  const endpoint = `/api/sales/organizations/${fixture.organization}/invoices/${invoice.id}/cancel`;
  const bodies: string[] = [], actors: string[] = [], paths: string[] = [];
  let stored: { cancellation_id: string; digest: string } | undefined;
  await chief.route(`**${endpoint}`, async route => {
    bodies.push(route.request().postData()!);
    actors.push((route.request().headers().cookie ?? "").split(";").find(v => v.trim().startsWith("aios_actor="))?.trim() ?? "");
    paths.push(new URL(route.request().url()).pathname);
    if (loseReply && bodies.length === 1) {
      const reply = await route.fetch();
      expect(reply.status()).toBe(201);
      stored = await reply.json();
      await route.abort("failed");
    } else await route.continue();
  });
  if (loseReply) {
    await panel.getByRole("button", { name: "Аннулировать счёт", exact: true }).click();
    const retry = panel.getByRole("button", { name: "Повторить сохранённый запрос", exact: true });
    await expect(retry).toBeVisible();
    const response = chief.waitForResponse(r => new URL(r.url()).pathname === endpoint && r.request().method() === "POST");
    await retry.click();
    const reply = await response;
    expect(reply.status(), await reply.text()).toBe(201);
    const receipt = await reply.json();
    expect(receipt).toMatchObject(stored!);
    expect(bodies).toHaveLength(2);
    expect(bodies[1]).toBe(bodies[0]);
    expect(paths).toEqual([endpoint, endpoint]);
    expect(actors[0]).not.toBe("");
    expect(actors[1]).toBe(actors[0]);
    await expect(panel.getByText(invoice.reserve_mode === "on_order" ? "Счёт аннулирован. Резерв отсутствовал." : "Счёт аннулирован. Резерв снят.", { exact: true })).toBeVisible();
    await expect(panel.getByText("Уведомление клиенту не отправлено.", { exact: true })).toBeVisible();
    return receipt;
  }
  const response = chief.waitForResponse(r => new URL(r.url()).pathname === endpoint && r.request().method() === "POST");
  await panel.getByRole("button", { name: "Аннулировать счёт", exact: true }).click();
  const reply = await response;
  expect(reply.status(), await reply.text()).toBe(201);
  const receipt = await reply.json();
  await expect(panel.getByText(invoice.reserve_mode === "on_order" ? "Счёт аннулирован. Резерв отсутствовал." : "Счёт аннулирован. Резерв снят.", { exact: true })).toBeVisible();
  await expect(panel.getByText("Уведомление клиенту не отправлено.", { exact: true })).toBeVisible();
  return receipt;
}
