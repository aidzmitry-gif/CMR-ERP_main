import { expect, test } from "@playwright/test";
import { createBuyer, createDealFromBuyer } from "./fixtures";

// Render real server data in the existing disposable E2E application, without API mocks.
test.use({ screenshot: "only-on-failure", trace: "retain-on-failure" });

for (const scenario of [
  { name: "ERP каталог: данные, поиск и карточка", route: "/erp/spravochniki/sku", width: 1440 },
  { name: "CRM каталог: данные, поиск и подбор по сделке", route: "/crm/catalog", width: 1440 },
  { name: "ERP каталог на узком экране: данные и действия", route: "/erp/spravochniki/sku", width: 390 },
]) {
  test(scenario.name, async ({ page, request, baseURL }, testInfo) => {
    expect(baseURL, "Only the disposable local E2E application is allowed").toMatch(
      /^http:\/\/(?:localhost|127\.0\.0\.1):\d+$/,
    );
    const isolation = await request.get("/api/__e2e_isolation");
    expect(isolation.status(), "The application must expose its synthetic isolation marker").toBe(200);
    expect(await isolation.json()).toMatchObject({
      synthetic_only: true, background_workers: false, email_enabled: false, egress_guard: true,
    });

    // Each CRM case owns its ordinary synthetic buyer/deal; no spec-order dependency.
    const selectionDeal = scenario.route === "/crm/catalog"
      ? await createDealFromBuyer(page, await createBuyer(page, "E2E catalogue buyer"), `E2E-CATALOG-${Date.now()}`)
      : null;
    const itemsBefore = selectionDeal ? await page.request.get(`/api/sales/deals/${selectionDeal.id}/items`) : null;
    if (itemsBefore) expect(itemsBefore.ok()).toBe(true);
    const originalItems = itemsBefore ? await itemsBefore.json() : null;
    const itemWrites: string[] = [];
    page.on("request", (request) => {
      if (request.method() === "POST" && /\/api\/sales\/deals\/\d+\/items$/.test(new URL(request.url()).pathname)) itemWrites.push(request.method());
    });

    const pageErrors: string[] = [];
    const failedRequests: string[] = [];
    const requestDiagnostics: { pathId: number; status: number }[] = [];
    page.on("pageerror", (error) => pageErrors.push(error.message));
    page.on("response", (response) => {
      const url = new URL(response.url());
      if (url.origin === new URL(baseURL!).origin && response.status() >= 400) {
        failedRequests.push(`${response.status()} ${url.pathname}`);
        if (requestDiagnostics.length < 16) {
          // Fixed route families only; URLs, query strings and entity IDs stay private.
          const pathId = url.pathname === "/api/sales/chats" ? 1
            : url.pathname === "/api/sales/calls/stream" ? 2
            : url.pathname.startsWith("/api/sales/") ? 3
            : url.pathname.startsWith("/api/system/") ? 4
            : url.pathname.startsWith("/api/hr/") ? 5
            : url.pathname.startsWith("/api/finance/") ? 6
            : url.pathname.startsWith("/_next/") ? 7
            : url.pathname === "/favicon.ico" ? 8
            : url.pathname.startsWith("/api/auth/") ? 9 : 0;
          requestDiagnostics.push({ pathId, status: response.status() });
        }
      }
    });
    await page.setViewportSize({ width: scenario.width, height: 900 });
    await page.goto(scenario.route);
    if (selectionDeal) {
      await expect(page.getByRole("heading", { name: "Номенклатура", exact: true })).toBeVisible();
      await expect(page.getByRole("cell", { name: "QA-STOCK", exact: true })).toBeVisible();
      await expect(page.getByRole("cell", { name: "QA-ORDER", exact: true })).toBeVisible();
      const search = page.getByRole("textbox", { name: "Поиск товара", exact: true });
      await search.fill("QA-STOCK");
      await expect(page.getByRole("cell", { name: "QA-STOCK", exact: true })).toBeVisible();
      await expect(page.getByRole("cell", { name: "QA-ORDER", exact: true })).toHaveCount(0);
      await search.fill("");
      await expect(page.getByRole("cell", { name: "QA-ORDER", exact: true })).toBeVisible();
      const deal = page.getByLabel("Сделка для подбора");
      await expect(deal).toHaveValue("");
      await expect(page.getByRole("button", { name: "Подобрать товары", exact: true })).toBeDisabled();
      await deal.selectOption(String(selectionDeal.id));
      await page.getByRole("button", { name: "Подобрать товары", exact: true }).click();
      const picker = page.getByRole("dialog", { name: "Подбор товара", exact: true });
      const table = picker.getByRole("table", { name: "Товары по складам" });
      for (const heading of ["Наименование", "Склад", "Остаток", "Резерв", "Свободно", "Цены", "В подбор"]) {
        await expect(table.getByRole("columnheader", { name: heading, exact: true })).toBeVisible();
      }
      const row = table.getByRole("row").filter({ hasText: "Контрольный аккумулятор — в наличии" });
      await expect(row).toBeVisible();
      await expect(row.getByRole("cell").nth(1)).toHaveText("Главный");
      await expect(row.getByRole("cell").nth(2)).toHaveText("10");
      await expect(row.getByRole("cell").nth(3)).toHaveText("0");
      await expect(row.getByRole("cell").nth(4)).toHaveText("10");
      await expect(row.getByRole("cell").nth(5)).not.toHaveText("—");
      await testInfo.attach("catalog-rendered", { body: await page.screenshot(), contentType: "image/png" });
      await picker.getByRole("button", { name: "Закрыть", exact: true }).click();
      await expect(picker).toHaveCount(0);
      expect(itemWrites).toEqual([]);
      const itemsAfter = await page.request.get(`/api/sales/deals/${selectionDeal.id}/items`);
      expect(itemsAfter.ok()).toBe(true);
      expect(await itemsAfter.json()).toEqual(originalItems);
    } else {
      await expect(page.getByRole("heading", { name: "Номенклатура (SKU)", exact: true })).toBeVisible();
      await expect(page.getByRole("link", { name: "QA-STOCK", exact: true }),
        "SKU page opened but the known seeded product did not render").toBeVisible();
      await expect(page.getByText("Не удалось загрузить номенклатуру. Список товаров неизвестен.",
        { exact: true })).toHaveCount(0);

      await page.getByRole("textbox", { name: "Поиск номенклатуры", exact: true }).fill("QA-STOCK");
      await page.getByRole("button", { name: "Найти", exact: true }).click();
      await expect(page).toHaveURL(/search=QA-STOCK/);
      await expect(page.getByRole("link", { name: "QA-STOCK", exact: true })).toBeVisible();
      await expect(page.getByRole("link", { name: "QA-ORDER", exact: true })).toHaveCount(0);
      await page.getByRole("link", { name: "Сбросить фильтры", exact: true }).click();
      await expect(page).toHaveURL(new RegExp(`${scenario.route}$`));
      await expect(page.getByRole("link", { name: "QA-ORDER", exact: true })).toBeVisible();

      if (scenario.width === 390) {
        expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth),
          "The page must fit the viewport; the table may scroll inside its own container").toBe(true);
      }
      await testInfo.attach("catalog-rendered", {
        body: await page.screenshot(), contentType: "image/png",
      });
      await page.getByRole("link", { name: "QA-STOCK", exact: true }).click();
      await expect(page).toHaveURL(/\/erp\/spravochniki\/sku\/QA-STOCK$/);
      await expect(page.getByRole("heading", {
        name: "Контрольный аккумулятор — в наличии", exact: true,
      }), "The SKU link must open a filled product card").toBeVisible();
    }
    try {
      expect(pageErrors, "Browser rendering errors").toEqual([]);
      expect(failedRequests, "Failed application requests (status and path)").toEqual([]);
    } finally {
      await testInfo.attach("catalogue-http-numeric", {
        body: Buffer.from(JSON.stringify({
          total: failedRequests.length, dropped: failedRequests.length - requestDiagnostics.length,
          entries: requestDiagnostics,
        })), contentType: "application/json",
      });
    }
  });
}
