import { expect, test } from '@playwright/test';
import { createHash } from 'node:crypto';
import { writeFile } from 'node:fs/promises';

for (const mode of ['stock', 'on_order'] as const) {
  test(`own outcomes preserve originals, tasks and ${mode} reserve`, async ({ page, context, browser, baseURL }) => {
    test.setTimeout(180_000);
    await context.clearCookies();
    await page.goto('/login');
    await page.getByLabel('Сотрудник').selectOption('e2e_owner');
    await page.getByRole('button', { name: 'Войти', exact: true }).click();
    await expect(page).not.toHaveURL(/\/login/);
    // Synthetic prerequisites use the real own API; outcome and loss retry use the UI.
    const nonce = `${mode}-${Date.now()}`;
    const clientReply = await page.request.post('/api/sales/clients', { data: {
      name: `Outcome ${nonce}`, request_key: `client-${nonce}`,
    } });
    expect(clientReply.status()).toBe(201);
    const client = await clientReply.json();
    const dealReply = await page.request.post('/api/sales/deals', { data: {
      number: `OUTCOME-${nonce}`, title: 'Synthetic outcome', counterparty: client.name,
      crm_client_id: client.id, next_step: 'Согласовать доставку',
      next_step_at: '2026-09-20T07:00:00', ship_deadline: '2026-09-25', expected_close_date: '2026-09-23',
    } });
    expect(dealReply.status()).toBe(201);
    const deal = await dealReply.json();
    const path = `/api/sales/deals/${deal.id}`;
    await page.goto(`/crm/deals/${deal.id}`);
    await page.getByPlaceholder('Что сделать…').fill(`Проверить ${nonce}`);
    await page.getByTitle('Срок (необязательно)').fill('2026-09-21T10:00');
    await page.getByRole('button', { name: 'Задача', exact: true }).click();
    await expect(page.getByText(`Проверить ${nonce}`, { exact: true })).toBeVisible();
    const message = await page.request.post(path + '/messages', { data: {
      text: `History ${nonce}`, channel: 'internal', request_key: `history-${nonce}`,
    } });
    expect(message.status()).toBe(201);
    const selector = page.getByRole('combobox', { name: 'Номенклатура (справочник из 1С через MDM)' });
    const sku = selector.locator('option').filter({ hasText: mode === 'stock' ? 'QA-STOCK' : 'QA-ORDER' });
    await expect(sku).toHaveCount(1);
    await selector.selectOption((await sku.getAttribute('value'))!);
    await page.getByRole('spinbutton', { name: 'Количество новой позиции', exact: true }).fill('2');
    await page.getByLabel('Цена за единицу новой позиции', { exact: true }).fill('125.50');
    const added = page.waitForResponse(r => r.url().endsWith(`/deals/${deal.id}/items`) && r.request().method() === 'POST');
    await page.getByRole('button', { name: 'Добавить', exact: true }).first().click();
    expect((await added).status()).toBe(201);
    const invoiceReply = await page.request.post(path + '/documents', { data: {
      kind: 'invoice', reserve_mode: mode, request_key: `invoice-${nonce}`,
    } });
    expect(invoiceReply.status()).toBe(201);
    const invoice = await invoiceReply.json();
    const read = async (url: string) => {
      const response = await page.request.get(url);
      expect(response.status()).toBe(200);
      return response.json();
    };
    const originalHash = async () => {
      const response = await page.request.get(`/api/sales/documents/${invoice.id}/render`);
      expect(response.status()).toBe(200);
      return createHash('sha256').update(await response.body()).digest('hex');
    };
    const control = await browser.newContext({ baseURL, storageState: 'e2e/.auth/state.json' });
    const stock = async () => {
      const response = await control.request.get('/api/integrations/1c/stock');
      expect(response.status()).toBe(200);
      return response.json();
    };
    try {
      const before = {
        tasks: await read(path + '/tasks'), messages: await read(path + '/messages'),
        items: await read(path + '/items'), documents: await read(path + '/documents'),
        original_sha256: await originalHash(), stock: await stock(),
      };
      expect(before.documents[0].reserve_status).toBe(mode === 'stock' ? 'reserved' : 'unreserved');
      expect(Number(before.documents[0].amount)).toBe(301.2);
      const preserved = async () => {
        expect(await read(path + '/tasks')).toEqual(before.tasks);
        expect(await read(path + '/messages')).toEqual(before.messages);
        expect(await read(path + '/items')).toEqual(before.items);
        expect(await read(path + '/documents')).toEqual(before.documents);
        expect(await originalHash()).toBe(before.original_sha256);
        expect(await stock()).toEqual(before.stock);
        const current = await read(path);
        for (const field of ['next_step', 'next_step_at', 'ship_deadline', 'expected_close_date', 'amount']) {
          expect(current[field]).toEqual(deal[field]);
        }
        return current;
      };
      const openDrawer = async () => {
        await page.goto('/crm/deals');
        await page.getByPlaceholder('Поиск сделок...').fill(deal.number);
        await page.getByTestId(`deal-card-${deal.id}`).click();
      };
      await openDrawer();
      const won = page.waitForResponse(r => r.url().endsWith(`/deals/${deal.id}/win`) && r.request().method() === 'POST');
      await page.getByRole('button', { name: 'Выиграна', exact: true }).click();
      expect((await won).status()).toBe(200);
      await page.reload();
      expect((await preserved()).stage).toBe('won');
      expect((await read(path)).closed_date).toBeTruthy();
      await expect(page.getByTestId('stage-column-won').getByTestId(`deal-card-${deal.id}`)).toBeVisible();
      expect((await page.request.post(path + '/win')).status()).toBe(409);
      expect((await page.request.patch(path, { data: { stage: 'qual' } })).status()).toBe(200);
      expect((await preserved()).closed_date).toBeNull();
      await openDrawer();
      await page.getByRole('button', { name: 'Отказ', exact: true }).click();
      const close = page.getByRole('button', { name: 'Закрыть в отказ', exact: true });
      await expect(close).toBeDisabled();
      await page.getByLabel('Причина отказа').selectOption('price');
      await page.getByPlaceholder('Комментарий (необязательно)').fill('Synthetic loss');
      let failOnce = true;
      let loseReply = mode === 'on_order';
      await page.route(`**/api/sales/deals/${deal.id}/lose`, async route => {
        if (!failOnce) {
          if (!loseReply) return route.continue();
          loseReply = false;
          expect((await route.fetch()).status()).toBe(200);
          return route.abort('failed');
        }
        failOnce = false;
        return route.fulfill({ status: 503, contentType: 'application/json', body: '{"detail":"synthetic retry"}' });
      });
      await close.click();
      await expect(page.getByRole('alert').filter({ hasText: 'Не удалось закрыть сделку в отказ' })).toBeVisible();
      await expect(page.getByLabel('Причина отказа')).toHaveValue('price');
      expect((await preserved()).stage).toBe('qual');
      if (mode === 'on_order') {
        await close.click();
        await expect(close).toBeEnabled();
        await expect(page.getByRole('alert').filter({ hasText: 'Не удалось закрыть сделку в отказ' })).toBeVisible();
        expect((await preserved()).stage).toBe('lost');
      }
      const lost = page.waitForResponse(r => r.url().endsWith(`/deals/${deal.id}/lose`)
        && r.status() === (mode === 'on_order' ? 409 : 200));
      await close.click();
      await lost;
      await expect(page.getByText('Закрыть сделку в отказ', { exact: true })).not.toBeVisible();
      await page.reload();
      const final = await preserved();
      expect(final.stage).toBe('lost');
      expect(final.closed_date).toBeTruthy();
      expect(final.lost_reason_code).toBe('price');
      expect(final.lost_comment).toBe('Synthetic loss');
      await expect(page.getByTestId('stage-column-lost').getByTestId(`deal-card-${deal.id}`)).toBeVisible();
      expect((await read(path + '/history')).slice(-3).map((row: { to_stage: string }) => row.to_stage)).toEqual(['won', 'qual', 'lost']);
      await page.goto(`/crm/deals/${deal.id}`);
      await expect(page.getByText(`Проверить ${nonce}`, { exact: true })).toBeVisible();
      const money = page.getByRole('region', { name: 'Оплата и деньги', exact: true });
      await expect(money.getByText('Нет данных', { exact: true })).toHaveCount(2);
      await page.screenshot({ path: test.info().outputPath(`outcome-${mode}.png`), fullPage: true });
      const foreign = await browser.newContext({ baseURL });
      try {
        const other = await foreign.newPage();
        await other.goto('/login');
        await other.getByLabel('Сотрудник').selectOption('e2e_foreign');
        await other.getByRole('button', { name: 'Войти', exact: true }).click();
        await expect(other).not.toHaveURL(/\/login/);
        for (const outcome of ['win', 'lose']) {
          expect((await other.request.post(path + '/' + outcome, { data: { reason_code: 'price' } })).status()).toBe(404);
        }
        expect((await other.request.patch(path, { data: { stage: 'qual' } })).status()).toBe(404);
        expect((await other.request.get(`/api/sales/documents/${invoice.id}/render`)).status()).toBe(404);
      } finally { await foreign.close(); }
      expect(await preserved()).toEqual(final);
      await writeFile(test.info().outputPath('preservation.json'), JSON.stringify({ mode, deal_id: deal.id, before, final }, null, 2));
    } finally { await control.close(); }
  });
}
