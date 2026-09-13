import { expect, test } from "@playwright/test";

test("счёт под заказ: цена, потерянный ответ, повтор и неизменяемый оригинал", async ({ page }) => {
  test.setTimeout(120_000);
  await page.goto("/crm/deals");
  await expect(page.getByTestId("deals-client-ready")).toBeVisible();
  await page.getByRole("button", { name: /Создать сделку/ }).click();
  const form = page.locator("form.shadow-pop");
  const unique = `E2E-DOC-${Date.now()}`;
  await form.getByPlaceholder("CRM-2024-0200").fill(unique);
  await form.getByPlaceholder("ООО ...").fill(unique);
  await form.getByPlaceholder("Поставка ...").fill("Синтетическая проверка документа");
  const created = page.waitForResponse((r) => r.url().endsWith("/api/sales/deals") && r.request().method() === "POST");
  await form.getByRole("button", { name: "Создать" }).click();
  const createdResponse = await created;
  expect(createdResponse.status()).toBe(201);
  const deal = await createdResponse.json();
  await page.getByText(unique, { exact: true }).first().dblclick();
  await expect(page).toHaveURL(new RegExp(`/crm/deals/${deal.id}$`));
  const endpoint = `/api/sales/deals/${deal.id}/documents`;
  const generate = page.getByRole("button", { name: "Сформировать", exact: true });
  await page.getByRole("checkbox", { name: "Под заказ — без резерва" }).check();
  const selector = page.getByRole("combobox", { name: "Номенклатура (справочник из 1С через MDM)" });
  const option = selector.locator("option").filter({ hasText: "QA-ORDER" });
  await expect(option).toHaveCount(1);
  const skuId = await option.getAttribute("value");
  expect(Number(skuId)).toBeGreaterThan(0);
  await selector.selectOption(skuId!);
  await page.getByRole("spinbutton", { name: "Количество новой позиции", exact: true }).fill("2");
  await page.getByLabel("Цена за единицу новой позиции", { exact: true }).fill("");
  const added = page.waitForResponse((r) => r.url().endsWith(`/deals/${deal.id}/items`) && r.request().method() === "POST");
  await page.getByRole("button", { name: "Добавить", exact: true }).first().click();
  expect((await added).status()).toBe(201);
  await test.step("позиция с NULL требует подтверждения цены", async () => {
    const failure = page.waitForResponse((r) => r.url().endsWith(endpoint) && r.request().method() === "POST");
    await generate.click();
    expect((await failure).status()).toBe(422);
    expect(await (await page.request.get(endpoint)).json()).toEqual([]);
  });
  const price = page.getByRole("spinbutton", { name: "Цена за единицу Контрольный аккумулятор — под заказ", exact: true });
  const save = page.getByRole("button", { name: "Сохранить позицию Контрольный аккумулятор — под заказ", exact: true });
  await price.fill("150");
  await save.click();
  await expect(save).toBeDisabled();
  let issuedId: number | undefined;
  const bodies: Array<{ request_key: string }> = [];
  let loseReply = true;
  await page.route(`**${endpoint}`, async (route) => {
    if (route.request().method() !== "POST") return route.continue();
    bodies.push(route.request().postDataJSON());
    if (!loseReply) return route.continue();
    loseReply = false;
    const response = await route.fetch();
    expect(response.status()).toBe(201);
    issuedId = (await response.json()).id;
    await route.abort("failed"); // Commit succeeded; only its browser response was lost.
  });
  await generate.click();
  await expect(page.getByRole("alert").filter({ hasText: "Не удалось создать документ" })).toBeVisible();
  const retry = page.waitForResponse((r) => r.url().endsWith(endpoint) && r.request().method() === "POST");
  await generate.click();
  expect((await retry).status()).toBe(201);
  expect(bodies).toHaveLength(2);
  expect(bodies[0].request_key).toBeTruthy();
  expect(bodies[1].request_key).toBe(bodies[0].request_key);
  const documents = await (await page.request.get(endpoint)).json();
  expect(documents).toHaveLength(1);
  expect(documents[0]).toMatchObject({ id: issuedId, amount: 360, reserve_mode: "on_order",
    reserve_status: "unreserved", original_state: "issued", version: 1 });
  expect(documents[0].content_sha256).toMatch(/^[a-f0-9]{64}$/);
  const snapshotResponse = await page.request.get(`/api/sales/documents/${issuedId}/snapshot`);
  expect(snapshotResponse.ok()).toBe(true);
  const snapshot = await snapshotResponse.json();
  expect(snapshot.items).toHaveLength(1);
  expect(Number(snapshot.items[0].net)).toBe(300);
  expect(Number(snapshot.items[0].tax)).toBe(60);
  expect(Number(snapshot.items[0].total)).toBe(360);
  expect(snapshot.items[0].basis).toBe("confirmed_deal_item_price");
  const money = page.getByRole("region", { name: "Оплата и деньги" });
  await expect(money.getByText("360 BYN", { exact: true })).toBeVisible();
  await expect(money.getByText("Нет данных", { exact: true })).toHaveCount(2);
  const renderUrl = `/api/sales/documents/${issuedId}/render`;
  const original = await page.request.get(renderUrl);
  expect(original.ok()).toBe(true);
  const originalHtml = await original.text();
  await expect(page.getByText("Под заказ — товар не зарезервирован").first()).toBeVisible();
  await test.step("изменение сделки не меняет выпущенный оригинал", async () => {
    await page.getByRole("spinbutton", { name: "Количество Контрольный аккумулятор — под заказ", exact: true }).fill("3");
    await price.fill("200");
    await save.click();
    await expect(save).toBeDisabled();
    await page.reload();
    await expect(price).toHaveValue("200");
    await expect(money.getByText("360 BYN", { exact: true })).toBeVisible();
    const unchanged = await page.request.get(renderUrl);
    expect(unchanged.ok()).toBe(true);
    expect(await unchanged.text()).toBe(originalHtml);
    expect(await (await page.request.get(endpoint)).json()).toEqual(documents);
    const items = await (await page.request.get(`/api/sales/deals/${deal.id}/items`)).json();
    expect(items).toHaveLength(1);
    expect(Number(items[0].qty) * Number(items[0].unit_price)).toBe(600);
  });
  await test.step("новая версия и явно подтверждённая нулевая цена", async () => {
    await page.getByText("История версий (1)", { exact: true }).click();
    await page.getByRole("button", { name: `Новая версия #${issuedId}`, exact: true }).click();
    await page.getByRole("textbox", { name: "Причина новой версии" }).fill("Синтетическая проверка бесплатной позиции");
    const revised = page.waitForResponse((r) => r.url().endsWith(`/documents/${issuedId}/revision`) && r.request().method() === "POST");
    await page.getByRole("button", { name: "Создать черновик", exact: true }).click();
    const revisedResponse = await revised;
    expect(revisedResponse.status()).toBe(201);
    const draft = await revisedResponse.json();
    expect(draft).toMatchObject({ version: 2, status: "draft", supersedes_id: issuedId, reserve_mode: "on_order" });
    expect(await (await page.request.get(renderUrl)).text()).toBe(originalHtml);
    await price.fill("0");
    await save.click();
    await expect(save).toBeDisabled();
    const issued = page.waitForResponse((r) => r.url().endsWith(`/documents/${draft.id}/issue`) && r.request().method() === "POST");
    await page.getByRole("button", { name: "Выпустить версию", exact: true }).click();
    const issuedResponse = await issued;
    expect(issuedResponse.status()).toBe(200);
    expect(await issuedResponse.json()).toMatchObject({ id: draft.id, amount: 0, original_state: "issued", reserve_status: "unreserved" });
    await page.reload();
    const finalDocs = await (await page.request.get(endpoint)).json();
    await expect(money.getByText("0 BYN", { exact: true })).toBeVisible();
    await expect(money.getByText("Нет данных", { exact: true })).toHaveCount(2);
    expect(finalDocs).toHaveLength(2);
    expect(finalDocs.find((doc: { id: number }) => doc.id === issuedId)).toMatchObject({
      amount: 360, version: 1, content_sha256: documents[0].content_sha256, superseded_by_id: draft.id,
    });
    expect(await (await page.request.get(renderUrl)).text()).toBe(originalHtml);
  });
});

test("документы: ошибка загрузки отличается от пустого списка и допускает повтор", async ({ page }) => {
  const created = await page.request.post("/api/sales/deals", { data: {
    number: `E2E-DOC-LOAD-${Date.now()}`, title: "Синтетическая проверка загрузки", counterparty: "E2E document load",
  } });
  expect(created.status()).toBe(201);
  const deal = await created.json();
  let fail = true;
  await page.route(`**/api/sales/deals/${deal.id}/documents`, (route) => fail && route.request().method() === "GET"
    ? route.fulfill({ status: 500, contentType: "application/json", body: '{"detail":"synthetic failure"}' })
    : route.continue());
  await page.goto(`/crm/deals/${deal.id}`);
  await expect(page.getByText("Не удалось загрузить документы.", { exact: true })).toBeVisible();
  await expect(page.getByText("Документов пока нет", { exact: true })).toHaveCount(0);
  fail = false;
  await page.getByRole("button", { name: "Повторить загрузку документов", exact: true }).click();
  await expect(page.getByText("Документов пока нет", { exact: true })).toBeVisible();
});
