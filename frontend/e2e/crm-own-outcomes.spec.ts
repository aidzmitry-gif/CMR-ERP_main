import { expect, test } from '@playwright/test';
import { createHash } from 'node:crypto';
import { writeFile } from 'node:fs/promises';
import { ensureConfiguredOrganization, createBuyer, assignBuyerToOwner, seedInvoiceFacts, addInvoiceItemUI, confirmInvoicePartiesUI, issueInvoiceUI, cancelInvoiceUI } from './fixtures';

for (const mode of ['stock', 'on_order'] as const) {
  test(`own outcomes preserve originals, tasks and ${mode} reserve`, async ({ page, context, browser, baseURL }) => {
    test.setTimeout(180_000);
    await ensureConfiguredOrganization(page);
    const buyer = await createBuyer(page, `E2E invoice buyer outcome ${mode} ${Date.now()}`);
    const client = await assignBuyerToOwner(page, buyer);
    await context.clearCookies();
    await page.goto('/login');
    await page.getByLabel('Сотрудник').selectOption('e2e_owner');
    await page.getByRole('button', { name: 'Войти', exact: true }).click();
    await expect(page).not.toHaveURL(/\/login/);
    // The director assigned the buyer; the owner creates this same client's deal.
    const nonce = `${mode}-${Date.now()}`;
    const ownClient = await page.request.get(`/api/sales/clients/${client.id}`);
    expect(ownClient.status()).toBe(200);
    expect(await ownClient.json()).toMatchObject({ id: client.id, owner_id: 2901, counterparty_id: buyer.id });
    const dealReply = await page.request.post('/api/sales/deals', { data: {
      number: `OUTCOME-${nonce}`, title: 'Synthetic outcome', counterparty: client.name,
      crm_client_id: client.id, next_step: 'Согласовать доставку',
      next_step_at: '2026-09-20T07:00:00', ship_deadline: '2026-09-25', expected_close_date: '2026-09-23',
    } });
    expect(dealReply.status()).toBe(201);
    const deal = await dealReply.json();
    expect(deal).toMatchObject({ owner_id: 2901, crm_client_id: client.id, counterparty_id: buyer.id });
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
    const control = await browser.newContext({ baseURL, storageState: 'e2e/.auth/state.json' });
    const chief = await control.newPage();
    const seeded = await seedInvoiceFacts(chief, deal.id, buyer);
    const fixture = await addInvoiceItemUI(page, deal.id, seeded, '125.50');
    await confirmInvoicePartiesUI(chief, deal.id, fixture, buyer);
    const invoice = await issueInvoiceUI(page, deal.id, fixture, buyer, mode, '125.50');
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
      let cancellation: { cancellation_id: string; digest: string; document_id: number; document_version: number; content_sha256: string; reserve_status: string; release_id: number | null; stock_outcome?: string } | null = null;
      const preserved = async () => {
        expect(await read(path + '/tasks')).toEqual(before.tasks);
        expect(await read(path + '/messages')).toEqual(before.messages);
        expect(await read(path + '/items')).toEqual(before.items);
        const documents = await read(path + '/documents');
        if (cancellation) {
          expect(documents).toHaveLength(1);
          expect(documents[0]).toMatchObject({ id: invoice.id, status: 'cancelled', reserve_status: cancellation.reserve_status });
          expect({ ...documents[0], status: before.documents[0].status,
            reserve_status: before.documents[0].reserve_status }).toEqual(before.documents[0]);
        } else expect(documents).toEqual(before.documents);
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
      await page.goto(`/crm/deals/${deal.id}`);
      await page.getByRole('button', { name: 'Отказ / состояние запроса', exact: true }).click();
      const loss = page.getByRole('dialog', { name: 'Отказ сделки', exact: true });
      const request = loss.getByRole('button', { name: 'Запросить отказ', exact: true });
      await expect(request).toBeDisabled();
      await loss.getByLabel('Причина отказа', { exact: true }).selectOption(fixture.loss_reason);
      await loss.getByLabel('Комментарий к отказу', { exact: true }).fill('Synthetic loss');
      const requested = page.waitForResponse(r => new URL(r.url()).pathname === path + '/lose' && r.request().method() === 'POST');
      await request.click();
      const pendingReply = await requested;
      expect(pendingReply.status(), await pendingReply.text()).toBe(200);
      const pending = await pendingReply.json();
      expect(pending).toMatchObject({ deal_id: deal.id, organization_id: fixture.organization, state: 'pending' });
      expect(pending.snapshot.invoices).toEqual([{ id: invoice.id, deal_id: deal.id, kind: 'invoice',
        version: invoice.version, content_sha256: invoice.content_sha256,
        supersedes_id: before.documents[0].supersedes_id, superseded_by_id: before.documents[0].superseded_by_id }]);
      await expect(loss.getByText(/ожидает завершения/)).toBeVisible();
      await loss.getByLabel('Основание завершения или отзыва', { exact: true }).fill('Synthetic same invoice not yet cancelled');
      await expect(loss.getByRole('button', { name: 'Завершить отказ', exact: true })).toBeDisabled();
      expect((await preserved()).stage).toBe('qual');
      cancellation = await cancelInvoiceUI(chief, deal.id, fixture, invoice, mode === 'on_order');
      expect(cancellation).toMatchObject({ document_id: invoice.id, document_version: invoice.version,
        content_sha256: invoice.content_sha256, reserve_status: mode === 'stock' ? 'released' : 'unreserved' });
      if (mode === 'stock') {
        expect(cancellation!.release_id).toBeGreaterThan(0);
        expect(cancellation).not.toHaveProperty('stock_outcome');
      } else {
        expect(cancellation).toMatchObject({ release_id: null, stock_outcome: 'no_stock_release' });
      }
      await preserved();
      await loss.getByRole('button', { name: 'Обновить сведения', exact: true }).click();
      await loss.getByLabel('Основание завершения или отзыва', { exact: true }).fill('Synthetic verified same invoice cancellation receipt');
      const finalize = loss.getByRole('button', { name: 'Завершить отказ', exact: true });
      await expect(finalize).toBeEnabled();
      const endpoint = `/api/sales/organizations/${fixture.organization}/deals/${deal.id}/loss-requests/${pending.request_id}/finalize`;
      const commands: string[] = [], actors: string[] = [], endpoints: string[] = [];
      let stored: { resolution_id: string; digest: string } | undefined;
      await page.route(`**${endpoint}`, async route => {
        commands.push(route.request().postData()!);
        endpoints.push(new URL(route.request().url()).pathname);
        actors.push((route.request().headers().cookie ?? '').split(';').find(v => v.trim().startsWith('aios_actor='))?.trim() ?? '');
        if (commands.length === 1) return route.fulfill({ status: 503, contentType: 'application/json', body: '{"detail":"synthetic retry"}' });
        if (mode === 'on_order' && commands.length === 2) {
          const actual = await route.fetch();
          expect(actual.status()).toBe(200);
          stored = await actual.json();
          return route.abort('failed');
        }
        return route.continue();
      });
      await finalize.click();
      const retry = loss.getByRole('button', { name: 'Повторить исходную команду', exact: true });
      await expect(retry).toBeVisible();
      expect((await read(path)).stage).toBe('qual');
      if (mode === 'on_order') {
        await retry.click();
        await expect(retry).toBeEnabled();
        await expect.poll(async () => (await read(path)).stage).toBe('lost');
      }
      const finalized = page.waitForResponse(r => new URL(r.url()).pathname === endpoint && r.status() === 200);
      await retry.click();
      const resolved = await (await finalized).json();
      expect(resolved).toMatchObject({ request_id: pending.request_id, action: 'finalized' });
      if (stored) expect(resolved).toMatchObject(stored);
      expect(commands).toHaveLength(mode === 'stock' ? 2 : 3);
      expect(new Set(commands).size).toBe(1);
      expect(new Set(endpoints)).toEqual(new Set([endpoint]));
      expect(actors[0]).not.toBe('');
      expect(new Set(actors).size).toBe(1);
      const finalRequest = await read(`/api/sales/organizations/${fixture.organization}/deals/${deal.id}/loss-requests/${pending.request_id}`);
      expect(finalRequest).toMatchObject({ request_id: pending.request_id, state: 'finalized', resolution: resolved });
      await loss.getByRole('button', { name: 'Закрыть окно', exact: true }).click();
      await expect(loss).not.toBeVisible();
      await page.reload();
      const final = await preserved();
      expect(final.stage).toBe('lost');
      expect(final.closed_date).toBeTruthy();
      expect(final.lost_reason_code).toBe(fixture.loss_reason);
      expect(final.lost_comment).toBe('Synthetic loss');
      await page.goto('/crm/deals');
      await expect(page.getByTestId('stage-column-lost').getByTestId(`deal-card-${deal.id}`)).toBeVisible();
      expect((await read(path + '/history')).slice(-3).map((row: { to_stage: string }) => row.to_stage)).toEqual(['won', 'qual', 'lost']);
      await page.goto(`/crm/deals/${deal.id}`);
      await expect(page.getByText(`Проверить ${nonce}`, { exact: true })).toBeVisible();
      const money = page.getByRole('region', { name: 'Оплата и деньги', exact: true });
      for (const label of ['Оплачено', 'Остаток к оплате', 'Сумма счёта (с НДС)']) {
        await expect(money.getByText(label, { exact: true }).locator('..').locator('dd')).toHaveText('Нет данных');
      }
      await expect(money.getByRole('link', { name: `Счёт ${invoice.number} · версия ${invoice.version}`, exact: true })).toHaveCount(0);
      await expect(money.getByText('Сумма выпущенного счёта пока не подтверждена.', { exact: true })).toBeVisible();
      await page.screenshot({ path: test.info().outputPath(`outcome-${mode}.png`), fullPage: true });
      const foreign = await browser.newContext({ baseURL });
      try {
        const other = await foreign.newPage();
        await other.goto('/login');
        await other.getByLabel('Сотрудник').selectOption('e2e_foreign');
        await other.getByRole('button', { name: 'Войти', exact: true }).click();
        await expect(other).not.toHaveURL(/\/login/);
        expect((await other.request.post(path + '/win')).status()).toBe(404);
        const foreignKey = crypto.randomUUID();
        const foreignLoss = await other.request.post(path + '/lose', { headers: { 'X-Expected-Principal': 'e2e_foreign' }, data: {
          ...pending.command, request_key: foreignKey,
        } });
        expect(foreignLoss.status()).toBe(403);
        expect(await foreignLoss.json()).toEqual({ detail: "No access to this organization's books" });
        expect((await other.request.patch(path, { data: { stage: 'qual' } })).status()).toBe(404);
        expect((await other.request.get(`/api/sales/documents/${invoice.id}/render`)).status()).toBe(404);
      } finally { await foreign.close(); }
      expect(await preserved()).toEqual(final);
      await writeFile(test.info().outputPath('preservation.json'), JSON.stringify({ mode, deal_id: deal.id, before, cancellation, final }, null, 2));
    } finally { await control.close(); }
  });
}
