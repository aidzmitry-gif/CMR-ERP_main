import { expect, test } from "@playwright/test";
import { createBuyer, createDealFromBuyer } from "./fixtures";

test("товары сделки: корзина, потерянный ответ, повтор без дублей и повторное открытие", async ({ page }, testInfo) => {
  const buyer = await createBuyer(page, `E2E goods buyer ${Date.now()}`);
  const number = `E2E-GOODS-${Date.now()}`;
  const deal = await createDealFromBuyer(page, buyer, number);
  const skuResponse = await page.request.get("/api/sales/skus");
  expect(skuResponse.ok(), await skuResponse.text()).toBe(true);
  const catalog = await skuResponse.json() as { id: number; code: string; title: string }[];
  const skus = ["QA-STOCK", "QA-ORDER"].map(code => {
    const matches = catalog.filter(sku => sku.code === code);
    expect(matches).toHaveLength(1);
    return matches[0];
  });
  await page.goto("/crm/deals");
  await expect(page.getByTestId("deals-client-ready")).toBeVisible();
  await page.getByTestId(`deal-card-${deal.id}`).click();
  const drawer = page.getByRole("dialog", { name: `Превью сделки ${number}`, exact: true });
  const goods = drawer.getByRole("region", { name: "Товары сделки", exact: true });
  await expect(goods).toContainText("В сделке пока нет товаров");
  await goods.getByRole("button", { name: "Добавить товары", exact: true }).click();
  const picker = page.getByRole("dialog", { name: "Подбор товара", exact: true });
  for (const [index, sku] of skus.entries()) {
    await picker.getByPlaceholder(/Название \/ артикул/).fill(sku.code);
    await picker.getByTitle(sku.title, { exact: true }).dblclick();
    await expect(picker).toBeVisible();
    await page.getByLabel("Количество товара", { exact: true }).fill(index === 0 ? "3" : "2");
    await page.getByLabel("Цена за единицу", { exact: true }).fill(index === 0 ? "100" : "200");
    await page.getByRole("button", { name: "Добавить в подбор", exact: true }).click();
  }
  const endpoint = `/api/sales/deals/${deal.id}/items`;
  expect(await (await page.request.get(endpoint)).json()).toEqual([]);
  const sends: { sku_id: number; request_key: string }[] = [];
  let lostReply = false;
  await page.route(`**${endpoint}`, async route => {
    if (route.request().method() !== "POST") return route.continue();
    const body = route.request().postDataJSON();
    sends.push(body);
    expect(body.request_key).toMatch(/^[0-9a-f-]{36}$/);
    if (body.sku_id === skus[1].id && !lostReply) {
      lostReply = true;
      const saved = await route.fetch();
      expect(saved.status(), await saved.text()).toBe(201);
      return route.abort("failed");
    }
    return route.continue();
  });
  await picker.getByRole("button", { name: "Перенести в документ", exact: true }).first().click();
  await expect(picker.getByRole("alert")).toContainText("Перенесено позиций: 1/2");
  const readback = await page.request.get(endpoint);
  expect(readback.ok(), await readback.text()).toBe(true);
  expect(await readback.json()).toHaveLength(2);
  await picker.getByRole("button", { name: "Перенести в документ", exact: true }).first().click();
  await expect(picker).not.toBeVisible();
  expect(sends).toHaveLength(3);
  const retried = sends.filter(body => body.sku_id === skus[1].id);
  expect(retried).toHaveLength(2);
  expect(retried[0]).toEqual(retried[1]);
  async function assertVisibleGoods() {
    await expect(goods.getByRole("table", { name: "Товары в сделке" }).locator("tbody tr")).toHaveCount(2);
    for (const [index, sku] of skus.entries()) {
      const cells = goods.getByRole("row").filter({ hasText: sku.title }).getByRole("cell");
      await expect(cells.nth(0)).toHaveText(sku.title);
      await expect(cells.nth(1)).toHaveText(index === 0 ? /^3\s*шт$/ : /^2\s*шт$/);
      await expect(cells.nth(2)).toHaveText(index === 0 ? "100 Br" : "200 Br");
      await expect(cells.nth(3)).toHaveText(index === 0 ? "300 Br" : "400 Br");
    }
    await expect(goods).toContainText("Итого по товарам: 700");
  }
  await assertVisibleGoods();
  await goods.screenshot({ path: testInfo.outputPath("deal-goods-readback.png") });
  await page.reload();
  await page.getByTestId(`deal-card-${deal.id}`).click();
  await assertVisibleGoods();
  const persisted = await page.request.get(endpoint);
  expect(persisted.ok(), await persisted.text()).toBe(true);
  expect((await persisted.json()).map((item: { sku_id: number; qty: number; unit_price: number }) =>
    ({ sku_id: item.sku_id, qty: item.qty, unit_price: item.unit_price }))).toEqual(expect.arrayContaining([
    { sku_id: skus[0].id, qty: 3, unit_price: 100 }, { sku_id: skus[1].id, qty: 2, unit_price: 200 },
  ]));
  expect(await persisted.json()).toHaveLength(2);
});
