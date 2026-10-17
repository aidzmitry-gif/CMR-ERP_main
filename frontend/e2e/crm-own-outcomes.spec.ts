import { expect, test, type Request, type Response } from '@playwright/test';
import { createHash } from 'node:crypto';
import { writeFile } from 'node:fs/promises';
import { addSyntheticDealItem, createSyntheticCounterparty, createSyntheticCrmDeal, prepareInvoiceWizard, seedInvoiceE2E } from './crm-fixtures';

for (const mode of ['stock', 'on_order'] as const) {
  test(`own outcomes preserve originals, tasks and ${mode} reserve`, async ({ page, context, browser, baseURL }) => {
    test.setTimeout(180_000);
    const nonce = `${mode}-${Date.now()}`;
    test.info().annotations.push({ type: 'erp_ready_outcome_checkpoint', description: '1' });
    const counterparty = await createSyntheticCounterparty(browser, `Outcome ${nonce}`, baseURL, 2901);
    test.info().annotations.push({ type: 'erp_ready_outcome_checkpoint', description: '2' });
    await context.clearCookies();
    await page.goto('/login');
    await page.getByLabel('Сотрудник').selectOption('e2e_owner');
    await page.getByRole('button', { name: 'Войти', exact: true }).click();
    await expect(page).not.toHaveURL(/\/login/);
    // Synthetic prerequisites use the real own API; outcome and loss retry use the UI.
    test.info().annotations.push({ type: 'erp_ready_outcome_checkpoint', description: '3' });
    const { client, deal } = await createSyntheticCrmDeal(page.request, counterparty, {
      ownerId: 2901, number: `E2E-OUTCOME-${nonce}`, title: 'Synthetic outcome',
      nextStep: 'Согласовать доставку', nextStepAt: '2026-09-20T07:00:00',
      shipDeadline: '2026-09-25', expectedCloseDate: '2026-09-23',
    });
    expect(client.counterparty_id).toBe(counterparty.id);
    expect(deal.crm_client_id).toBe(client.id);
    const path = `/api/sales/deals/${deal.id}`;
    test.info().annotations.push({ type: 'erp_ready_outcome_checkpoint', description: '4' });
    await page.goto(`/crm/deals/${deal.id}`);
    await page.getByPlaceholder('Что сделать…').fill(`Проверить ${nonce}`);
    await page.getByTitle('Срок (необязательно)').fill('2026-09-21T10:00');
    await page.getByRole('button', { name: 'Задача', exact: true }).click();
    await expect(page.getByText(`Проверить ${nonce}`, { exact: true })).toBeVisible();
    test.info().annotations.push({ type: 'erp_ready_outcome_checkpoint', description: '5' });
    const message = await page.request.post(path + '/messages', { data: {
      text: `History ${nonce}`, channel: 'internal', request_key: `history-${nonce}`,
    } });
    expect(message.status()).toBe(201);
    test.info().annotations.push({ type: 'erp_ready_outcome_checkpoint', description: '6' });
    const item = await addSyntheticDealItem(page, deal.id, mode === 'stock' ? 'QA-STOCK' : 'QA-ORDER');
    expect(item.qty).toBe(2);
    expect(item.unit_price).toBe(125.5);
    test.info().annotations.push({ type: 'erp_ready_outcome_checkpoint', description: '7' });
    const fixture = await seedInvoiceE2E(page, deal.id, item.id, mode, { foreignBookReader: mode === 'stock' });
    test.info().annotations.push({ type: 'erp_ready_outcome_checkpoint', description: '8' });
    await prepareInvoiceWizard(page, fixture, mode);
    test.info().annotations.push({ type: 'erp_ready_outcome_checkpoint', description: '9' });
    const issueReply = page.waitForResponse(response => response.url().endsWith(`/api/sales/deals/${deal.id}/documents`)
      && response.request().method() === 'POST');
    await page.getByRole('button', { name: mode === 'stock' ? 'Выпустить счёт и зарезервировать' : 'Выпустить счёт под заказ', exact: true }).click();
    expect((await issueReply).status()).toBe(201);
    await expect(page.getByRole('link', { name: 'Открыть оригинал', exact: true })).toBeVisible();
    const issuedList = await page.request.get(`/api/sales/deals/${deal.id}/documents`);
    expect(issuedList.status()).toBe(200);
    const issuedDocuments = await issuedList.json();
    expect(issuedDocuments).toHaveLength(1);
    const invoice = issuedDocuments[0] as { id: number; amount: number; reserve_status: string };
    expect(invoice.reserve_status).toBe(mode === 'stock' ? 'reserved' : 'unreserved');
    expect(invoice.amount).toBe(301.2);
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
    const reservations = async () => {
      const response = await control.request.get(`/api/wms/reservations?organization_id=${fixture.organization}`);
      expect(response.status()).toBe(200);
      return (await response.json()).filter((row: { source: string }) => row.source.startsWith(`invoice:${invoice.id}:`));
    };
    try {
      test.info().annotations.push({ type: 'erp_ready_outcome_checkpoint', description: '10' });
      const before = {
        tasks: await read(path + '/tasks'), messages: await read(path + '/messages'),
        items: await read(path + '/items'), documents: await read(path + '/documents'),
        original_sha256: await originalHash(), stock: await stock(), reservations: await reservations(),
      };
      expect(before.documents[0].reserve_status).toBe(mode === 'stock' ? 'reserved' : 'unreserved');
      expect(Number(before.documents[0].amount)).toBe(301.2);
      if (mode === 'stock') {
        expect(before.reservations).toHaveLength(1);
        expect(before.reservations[0]).toMatchObject({ organization_id: fixture.organization,
          sku_code: fixture.sku, warehouse: 'E2E-W', version: 1, qty: '2.00', actor: 'e2e_owner' });
        expect(before.reservations[0].id).toBeGreaterThan(0);
      } else expect(before.reservations).toEqual([]);
      const preserved = async () => {
        expect(await read(path + '/tasks')).toEqual(before.tasks);
        expect(await read(path + '/messages')).toEqual(before.messages);
        expect(await read(path + '/items')).toEqual(before.items);
        expect(await read(path + '/documents')).toEqual(before.documents);
        expect(await originalHash()).toBe(before.original_sha256);
        expect(await stock()).toEqual(before.stock);
        expect(await reservations()).toEqual(before.reservations);
        const current = await read(path);
        expect(current).toMatchObject({ next_step: deal.next_step, next_step_at: deal.next_step_at,
          ship_deadline: deal.ship_deadline, expected_close_date: deal.expected_close_date, amount: deal.amount });
        return current;
      };
      const openDrawer = async (trackWin = false) => {
        await page.goto('/crm/deals');
        if (trackWin) test.info().annotations.push({ type: 'erp_ready_outcome_checkpoint', description: '12' });
        await page.getByPlaceholder('Поиск сделок...').fill(deal.number);
        if (trackWin) test.info().annotations.push({ type: 'erp_ready_outcome_checkpoint', description: '13' });
        await page.getByTestId(`deal-card-${deal.id}`).click();
        if (trackWin) test.info().annotations.push({ type: 'erp_ready_outcome_checkpoint', description: '14' });
      };
      test.info().annotations.push({ type: 'erp_ready_outcome_checkpoint', description: '11' });
      await openDrawer(true);
      const winRequests = [
        { url: new URL(path + '/loss-context', page.url()).href, method: 'GET' },
        { url: new URL('/api/sales/stages', page.url()).href, method: 'GET' },
        { url: new URL(path + '/win', page.url()).href, method: 'POST' },
      ].map((endpoint, index) => ({ ...endpoint, request: null as Request | null, attempts: 0,
        annotation: { type: 'erp_ready_win_request', description: `${index + 1}:null` } }));
      test.info().annotations.push(...winRequests.map(row => row.annotation));
      const observeWinRequest = (request: Request) => {
        const index = winRequests.findIndex(row => row.url === request.url() && row.method === request.method());
        if (index < 0) return;
        const row = winRequests[index];
        row.attempts = Math.min(2, row.attempts + 1);
        row.request = row.attempts === 1 ? request : null;
        row.annotation.description = `${index + 1}:null`;
      };
      const observeWinResponse = (response: Response) => {
        const index = winRequests.findIndex(row => row.attempts === 1 && row.request === response.request());
        const status = response.status();
        if (index >= 0 && Number.isInteger(status) && status >= 100 && status <= 599)
          winRequests[index].annotation.description = `${index + 1}:${status}`;
      };
      page.on('request', observeWinRequest);
      page.on('response', observeWinResponse);
      try {
        const won = page.waitForResponse(r => r.url().endsWith(`/deals/${deal.id}/win`) && r.request().method() === 'POST');
        await page.getByRole('button', { name: 'Выиграна', exact: true }).click();
        test.info().annotations.push({ type: 'erp_ready_outcome_checkpoint', description: '15' });
        expect((await won).status()).toBe(200);
        test.info().annotations.push({ type: 'erp_ready_outcome_checkpoint', description: '16' });
      } finally {
        page.off('request', observeWinRequest);
        page.off('response', observeWinResponse);
      }
      await page.reload();
      test.info().annotations.push({ type: 'erp_ready_outcome_checkpoint', description: '17' });
      expect((await preserved()).stage).toBe('won');
      expect((await read(path)).closed_date).toBeTruthy();
      test.info().annotations.push({ type: 'erp_ready_outcome_checkpoint', description: '18' });
      await expect(page.getByTestId('stage-column-won').getByTestId(`deal-card-${deal.id}`)).toBeVisible();
      test.info().annotations.push({ type: 'erp_ready_outcome_checkpoint', description: '19' });
      expect((await page.request.post(path + '/win')).status()).toBe(409);
      expect((await page.request.patch(path, { data: { stage: 'qual' } })).status()).toBe(200);
      expect((await preserved()).closed_date).toBeNull();
      test.info().annotations.push({ type: 'erp_ready_outcome_checkpoint', description: '20' });
      test.info().annotations.push({ type: 'erp_ready_outcome_checkpoint', description: '21' });
      const lossPreviewResponse = await page.request.get(`/api/sales/organizations/${fixture.organization}/deals/${deal.id}/loss-preview`);
      expect(lossPreviewResponse.status()).toBe(200);
      const lossPreview = await lossPreviewResponse.json();
      await openDrawer();
      await page.getByRole('button', { name: 'Отказ', exact: true }).click();
      const requestLoss = page.getByRole('button', { name: 'Запросить отказ', exact: true });
      await expect(requestLoss).toBeDisabled();
      await page.getByLabel('Причина отказа').selectOption(fixture.loss_reason);
      await expect(requestLoss).toBeEnabled();
      await page.getByPlaceholder('Комментарий (необязательно)').fill('Synthetic loss');
      let submission: Record<string, unknown> | null = null;
      let committedLoss: Record<string, unknown> | null = null;
      let attempts = 0;
      await page.route(`**/api/sales/deals/${deal.id}/lose`, async route => {
        if (route.request().method() !== 'POST') return route.continue();
        attempts += 1;
        const body = route.request().postDataJSON() as Record<string, unknown>;
        if (attempts === 1) {
          submission = body;
          expect(body).toMatchObject({ organization_id: fixture.organization, reason_code: fixture.loss_reason,
            comment: 'Synthetic loss', finalize_if_empty: false });
          expect(body.request_key).toEqual(expect.stringMatching(/^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/));
          expect(body.expected_composition_digest).toBe(lossPreview.composition_digest);
          if (mode === 'on_order') {
            const response = await route.fetch();
            expect(response.status()).toBe(200);
            committedLoss = await response.json() as Record<string, unknown>;
            expect(committedLoss).toMatchObject({ replayed: false, state: 'pending', command: body,
              request_id: body.request_key });
            await route.abort('failed');
            return;
          }
          return route.fulfill({ status: 503, contentType: 'application/json', body: '{"detail":"synthetic retry"}' });
        }
        expect(body).toEqual(submission);
        if (mode === 'on_order') {
          if (!committedLoss) throw new Error('No committed loss receipt before retry');
          const response = await route.fetch();
          expect(response.status()).toBe(200);
          expect(await response.json()).toEqual({ ...committedLoss, replayed: true });
          return route.fulfill({ response });
        }
        return route.continue();
      });
      test.info().annotations.push({ type: 'erp_ready_outcome_checkpoint', description: '22' });
      await requestLoss.click();
      await expect(page.getByText(/Результат исходной команды не установлен/)).toBeVisible();
      const retryLoss = page.getByRole('button', { name: 'Повторить исходную команду', exact: true });
      await expect(retryLoss).toBeEnabled();
      await preserved();
      test.info().annotations.push({ type: 'erp_ready_outcome_checkpoint', description: '23' });
      await retryLoss.click();
      await expect(page.getByText(/ожидает завершения/)).toBeVisible();
      await expect(page.getByRole('button', { name: 'Завершить отказ', exact: true })).toBeDisabled();
      expect(attempts).toBe(2);
      test.info().annotations.push({ type: 'erp_ready_outcome_checkpoint', description: '24' });
      const submissionKey = submission?.request_key;
      if (typeof submissionKey !== 'string') throw new Error('Loss request key was not retained');
      const lossRecord = await read(`/api/sales/organizations/${fixture.organization}/deals/${deal.id}/loss-requests/${submissionKey}`);
      expect(lossRecord.state).toBe('pending');
      expect(lossRecord.command).toEqual(submission);
      expect(lossRecord.ready_to_finalize).toBe(false);
      if (mode === 'on_order') {
        expect(lossRecord.request_id).toBe(committedLoss?.request_id);
        expect(lossRecord.request_digest).toBe(committedLoss?.request_digest);
      }
      expect((await preserved()).stage).toBe('qual');
      await page.reload();
      const afterPending = await preserved();
      expect(afterPending.stage).toBe('qual');
      expect(afterPending.closed_date).toBeNull();
      expect(afterPending.lost_reason_code).toBeNull();
      expect(afterPending.lost_comment).toBeNull();
      expect((await read(path + '/history')).slice(-2).map((row: { to_stage: string }) => row.to_stage)).toEqual(['won', 'qual']);
      await page.goto(`/crm/deals/${deal.id}`);
      await expect(page.getByText(`Проверить ${nonce}`, { exact: true })).toBeVisible();
      const money = page.getByRole('region', { name: 'Оплата и деньги', exact: true });
      await expect(money.getByText('Нет данных', { exact: true })).toHaveCount(2);
      await page.screenshot({ path: test.info().outputPath(`outcome-${mode}.png`), fullPage: true });
      test.info().annotations.push({ type: 'erp_ready_outcome_checkpoint', description: '25' });
      const foreign = await browser.newContext({ baseURL });
      try {
        const other = await foreign.newPage();
        await other.goto('/login');
        await other.getByLabel('Сотрудник').selectOption('e2e_foreign');
        await other.getByRole('button', { name: 'Войти', exact: true }).click();
        await expect(other).not.toHaveURL(/\/login/);
        expect((await other.request.post(path + '/win')).status()).toBe(404);
        const foreignLoss = await other.request.post(path + '/lose', {
          headers: { 'X-Expected-Principal': 'e2e_foreign' },
          data: {
            organization_id: fixture.organization, request_key: crypto.randomUUID(),
            expected_composition_digest: lossPreview.composition_digest,
            reason_code: fixture.loss_reason, comment: 'Synthetic foreign scope check', finalize_if_empty: false,
          },
        });
        expect(foreignLoss.status()).toBe(mode === 'stock' ? 404 : 403);
        expect((await other.request.patch(path, { data: { stage: 'qual' } })).status()).toBe(404);
        expect((await other.request.get(`/api/sales/documents/${invoice.id}/render`)).status()).toBe(404);
      } finally { await foreign.close(); }
      test.info().annotations.push({ type: 'erp_ready_outcome_checkpoint', description: '26' });
      expect(await preserved()).toEqual(afterPending);
      await writeFile(test.info().outputPath('preservation.json'), JSON.stringify({ mode, deal_id: deal.id, before, afterPending }, null, 2));
    } finally { await control.close(); }
  });
}

test('own no-invoice loss finalizes with date, reason and history', async ({ page, context, browser, baseURL }) => {
  const stamp = Date.now();
  const counterparty = await createSyntheticCounterparty(browser, `E2E empty loss ${stamp}`, baseURL, 2901);
  await context.clearCookies();
  await page.goto('/login');
  await page.getByLabel('Сотрудник').selectOption('e2e_owner');
  await page.getByRole('button', { name: 'Войти', exact: true }).click();
  await expect(page).not.toHaveURL(/\/login/);
  const { deal, client } = await createSyntheticCrmDeal(page.request, counterparty, {
    ownerId: 2901, number: `E2E-EMPTY-LOSS-${stamp}`, title: 'Synthetic no-invoice outcome',
  });
  expect(client.counterparty_id).toBe(counterparty.id);
  expect(deal.crm_client_id).toBe(client.id);
  const fixture = await seedInvoiceE2E(page, deal.id, null, null);
  const path = `/api/sales/deals/${deal.id}`;
  await page.goto(`/crm/deals/${deal.id}`);
  await page.getByRole('button', { name: 'Отказ / состояние запроса', exact: true }).click();
  const dialog = page.getByRole('dialog');
  await expect(dialog.getByText(/Счетов: 0\./)).toBeVisible();
  const noInvoice = dialog.getByRole('checkbox', { name: 'Закрыть сейчас, если счетов нет', exact: true });
  await noInvoice.check();
  await dialog.getByLabel('Причина отказа', { exact: true }).selectOption(fixture.loss_reason);
  const comment = 'Synthetic no-invoice terminal loss';
  await dialog.getByPlaceholder('Комментарий (необязательно)').fill(comment);

  const requestPromise = page.waitForRequest(request => request.url().endsWith(`/api/sales/deals/${deal.id}/lose`)
    && request.method() === 'POST');
  const responsePromise = page.waitForResponse(response => response.url().endsWith(`/api/sales/deals/${deal.id}/lose`)
    && response.request().method() === 'POST');
  await dialog.getByRole('button', { name: 'Запросить отказ', exact: true }).click();
  const request = await requestPromise;
  const body = request.postDataJSON() as Record<string, unknown>;
  expect(body).toMatchObject({ organization_id: fixture.organization, reason_code: fixture.loss_reason,
    comment, finalize_if_empty: true });
  expect(body.request_key).toEqual(expect.stringMatching(/^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/));
  expect(body.expected_composition_digest).toEqual(expect.stringMatching(/^[a-f0-9]{64}$/));
  const requestKey = body.request_key;
  if (typeof requestKey !== 'string') throw new Error('No durable no-invoice loss request key');
  const response = await responsePromise;
  expect(response.status()).toBe(200);
  const receipt = await response.json();
  expect(receipt).toMatchObject({ state: 'finalized', command: body,
    resolution: { action: 'finalized', request_id: body.request_key } });
  await expect(dialog.getByText(new RegExp(`Запрос ${requestKey}: отказ завершён`))).toBeVisible();

  const recordResponse = await page.request.get(`/api/sales/organizations/${fixture.organization}/deals/${deal.id}/loss-requests/${requestKey}`);
  expect(recordResponse.status()).toBe(200);
  expect(await recordResponse.json()).toMatchObject({ state: 'finalized', command: body,
    resolution: { action: 'finalized', snapshot: { to_stage: 'lost' } } });
  const dealResponse = await page.request.get(path);
  expect(dealResponse.status()).toBe(200);
  const finalized = await dealResponse.json();
  expect(finalized).toMatchObject({ stage: 'lost', lost_reason_code: fixture.loss_reason, lost_comment: comment });
  expect(finalized.closed_date).toMatch(/^\d{2}\.\d{2}\.\d{4}$/);
  const documents = await page.request.get(path + '/documents');
  expect(documents.status()).toBe(200);
  expect(await documents.json()).toEqual([]);
  const history = await page.request.get(path + '/history');
  expect(history.status()).toBe(200);
  expect((await history.json()).at(-1)).toMatchObject({ to_stage: 'lost' });
});
