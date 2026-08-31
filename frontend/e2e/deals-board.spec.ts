import { expect, test } from "@playwright/test";

// E2E: доска сделок /crm/deals — drag-and-drop, фильтры, переключение воронки.
// Все три теста самодостаточны на пустой CI-базе (создают своё состояние или проверяют UI-состояние).
// Важно: НЕ используем waitForLoadState("networkidle") — /crm/* держит постоянный SSE.

test.describe("deals board", () => {
  test("drag-and-drop: смена стадии перетаскиванием", async ({ page }) => {
    await page.goto("/crm/deals");
    // Ждём отрисовки канбана (SSR — колонки приходят сразу, SSE не блокирует)
    const newDropzone = page.locator('[data-testid="stage-column-new"]');
    await expect(newDropzone).toBeVisible();
    // Колонка SSR-видима раньше, чем React подключит onClick; ждём границу гидрации.
    await expect(page.getByTestId("deals-client-ready")).toBeVisible();

    // Создаём сделку для самодостаточности на пустой CI-базе.
    // Если БД накопила карточки — DRAG берём с ПЕРВОЙ карточки (вверх колонки),
    // а не с только что созданной (внизу). Это важно: при скролле к нижней карточке
    // qual-дропзона уходит выше viewport → e.over=null → drop не засчитывается.
    await page.getByRole("button", { name: /Создать сделку/ }).click();
    const form = page.locator("form.shadow-pop");
    await expect(form).toBeVisible();
    await form.getByPlaceholder("CRM-2024-0200").fill(`DND-${Date.now()}`);
    await form.getByPlaceholder("ООО ...").fill(`ООО E2E-DND-${Date.now()}`);
    await form.getByPlaceholder("Поставка ...").fill("DnD тест");
    await form.getByRole("button", { name: "Создать" }).click();
    await expect(form).not.toBeVisible();

    // ПЕРВАЯ карточка в new — у верха колонки; qual-дропзона тоже видна в этом viewport.
    const firstCard = newDropzone.locator('[data-testid^="deal-card-"]').first();
    await expect(firstCard).toBeVisible();
    // Запоминаем testid чтобы найти карточку в qual после drop
    const cardTestId = await firstCard.getAttribute("data-testid");
    if (!cardTestId) throw new Error("card data-testid not found");

    // Прокрутка к первой карточке минимальна (она у верха board),
    // поэтому qual-дропзона остаётся в viewport — оба элемента видны одновременно.
    await firstCard.scrollIntoViewIfNeeded();
    const cardBox = await firstCard.boundingBox();
    if (!cardBox) throw new Error("card bounding box not found");

    const qualDropzone = page.locator('[data-testid="stage-column-qual"]');
    await expect(qualDropzone).toBeVisible();
    const qualBox = await qualDropzone.boundingBox();
    if (!qualBox) throw new Error("qual column bounding box not found");

    const startX = cardBox.x + cardBox.width / 2;
    const startY = cardBox.y + cardBox.height / 2;
    const targetX = qualBox.x + qualBox.width / 2;
    const targetY = qualBox.y + qualBox.height / 2;

    // PointerSensor: activationConstraint { distance: 8 } — двигаемся >8px вправо
    // (qual правее new), активируем drag, затем перемещаем к цели.
    await page.mouse.move(startX, startY);
    await page.mouse.down();
    await page.mouse.move(startX + 15, startY, { steps: 3 }); // >8px → активирует drag
    await page.mouse.move(targetX, targetY, { steps: 20 });
    await page.mouse.up();

    // После drop: moveDealToStage обновляет React-стейт оптимистично
    await expect(qualDropzone.locator(`[data-testid="${cardTestId}"]`)).toBeVisible();
  });

  test("фильтры: приоритет и «Только висяки»", async ({ page }) => {
    await page.goto("/crm/deals");
    await expect(page.locator('[data-testid="stage-column-new"]')).toBeVisible();

    // Открываем панель фильтров. Якорь ^: у пустой отфильтрованной доски есть кнопка
    // «Сбросить фильтры» — substring-матч по имени дал бы strict mode violation.
    await page.getByRole("button", { name: /^Фильтры/ }).click();

    // Кнопки приоритета появляются — ждём «Высокий»
    const highBtn = page.getByRole("button", { name: "Высокий", exact: true });
    await expect(highBtn).toBeVisible();

    // Выбираем «Высокий» → кнопка получает bg-accent-soft
    await highBtn.click();
    await expect(page).toHaveURL(/priority=/);
    expect(new URL(page.url()).searchParams.get("priority")).toBe("Высокий");

    // Мульти-выбор (b7878fe): меню НЕ закрылось — сбрасываем в «Все» без переоткрытия.
    // «Все» есть в каждой секции (Приоритет/Ответственный/Внимание) — первый и есть приоритет.
    await page.getByRole("button", { name: "Все", exact: true }).first().click();
    await expect(page).not.toHaveURL(/priority=/);

    // Закрываем меню «Готово» — иначе фикс-бэкдроп меню перехватит клик по «Висяки».
    await page.getByRole("button", { name: "Готово" }).click();

    // Тогл «Только висяки»: неактивен (border-line) → активен (border-amber-400) → неактивен
    const stuckBtn = page.getByRole("button", { name: "Висяки" });
    await expect(stuckBtn).not.toHaveClass(/border-amber-400/);
    await stuckBtn.click();
    await expect(stuckBtn).toHaveClass(/border-amber-400/);
    await stuckBtn.click();
    await expect(stuckBtn).not.toHaveClass(/border-amber-400/);
  });

  test("переключение воронки", async ({ page }) => {
    await page.goto("/crm/deals");
    await expect(page.locator('[data-testid="stage-column-new"]')).toBeVisible();

    // Проверяем сколько воронок возвращает бэк (через Next.js proxy, с куками сессии страницы).
    // FunnelTabs рендерит null при ≤1 воронке (funnel-tabs.tsx:51) — в этом случае скипаем.
    const resp = await page.request.get("/api/sales/funnels");
    const funnels: Array<{ code: string; title: string; active_deals: number }> = resp.ok()
      ? ((await resp.json()) as Array<{ code: string; title: string; active_deals: number }>)
      : [];

    test.skip(
      funnels.length < 2,
      "Настроена только одна воронка — FunnelTabs.tsx:51 скрывает таб-переключатель " +
        "при funnels.length <= 1. Для активации теста заведи ≥2 воронки через POST /sales/funnels.",
    );

    // Находим кнопку второй воронки (FunnelTabs рендерит их как <button> с title)
    const second = funnels[1];
    const funnelSelect = page.getByRole("combobox", { name: "Воронка" });
    await expect(funnelSelect).toBeVisible();
    await funnelSelect.selectOption(second.code);

    // URL обновляется с параметром funnel= (router.replace в FunnelTabs)
    await expect(page).toHaveURL(/funnel=/);
    expect(new URL(page.url()).searchParams.get("funnel")).toBe(second.code);
    // SSR-страница перезагружает доску (key={activeFunnel} в page.tsx меняет стейт)
    await expect(page.locator('[data-testid^="stage-column-"]').first()).toBeVisible();
  });
});
