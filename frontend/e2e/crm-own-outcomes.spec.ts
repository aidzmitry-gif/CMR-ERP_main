import { expect, test } from '@playwright/test';
import { createHash, randomUUID } from 'node:crypto';
import { execFileSync } from 'node:child_process';
import { resolve } from 'node:path';
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
    const actor = (await context.cookies()).find(cookie => cookie.name === 'aios_actor')?.value;
    expect(actor).toBe('e2e_owner');
    const fixture = JSON.parse(execFileSync(process.env.E2E_PYTHON ?? 'python', ['-m', 'scripts.seed_outcomes_e2e'], {
      cwd: resolve(process.cwd(), '..'), input: JSON.stringify({ deal_id: deal.id, actor }),
      env: { ...process.env, AIOS_E2E_SEED: '1' }, encoding: 'utf8',
    })) as { organization: number; item: number; buyer: number; loss_reason: string };
    const accounting = await browser.newContext({ baseURL, storageState: 'e2e/.auth/state.json' });
    const profile = await accounting.request.post(`/api/accounting/organizations/${fixture.organization}/seller-profiles`, { data: {
      source_key: `e2e-outcome-${nonce}`, expected_revision: 0, effective_from: '2026-01-01',
      currency: 'BYN', address: 'Synthetic seller address', account: 'TEST ACCOUNT', bank: 'TEST BANK',
      bik: 'TEST BIK', director: 'Synthetic director', evidence: 'Synthetic E2E profile', confirmed: true,
    } });
    expect(profile.status(), await profile.text()).toBe(201);
    await accounting.close();
    const invoiceBase = { reserve_mode: mode, organization_id: fixture.organization, currency: 'BYN',
      document_date: '2026-09-10', valid_until: '2026-09-15',
      pricing: [{ item_id: fixture.item, unit_price_net: '125.50', vat_rate: '20.00' }],
      pricing_evidence: 'Synthetic negotiated price and VAT' };
    const previewReply = await page.request.post(path + '/invoice-preview', { data: invoiceBase });
    expect(previewReply.status(), await previewReply.text()).toBe(200);
    const preview = await previewReply.json();
    expect(preview.lines).toHaveLength(1);
    const reservation = mode === 'stock'
      ? { allocations: [{ line_no: preview.lines[0].line_no, warehouse: 'E2E-W', qty: '2.00' }],
          evidence: 'Synthetic physical journal: 10 units, no previous reservations', journal_complete: true }
      : { allocations: [], unreserved_confirmed: true };
    const invoiceReply = await page.request.post(path + '/documents', { data: {
      ...invoiceBase, kind: 'invoice', request_key: `invoice-${nonce}`,
      expected_document_version: preview.document_version, expected_basis_digest: preview.basis_digest, ...reservation,
    } });
    expect(invoiceReply.status(), await invoiceReply.text()).toBe(201);
    const invoice = (await invoiceReply.json()).document;
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
      let invoiceCancelled = false;
      const preserved = async () => {
        expect(await read(path + '/tasks')).toEqual(before.tasks);
        expect(await read(path + '/messages')).toEqual(before.messages);
        expect(await read(path + '/items')).toEqual(before.items);
        expect(await read(path + '/documents')).toEqual(invoiceCancelled
          ? before.documents.map((document: { id: number }) => document.id === invoice.id
            ? { ...document, status: 'cancelled', reserve_status: 'released' } : document)
          : before.documents);
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
      const loss = page.getByRole('dialog');
      const close = loss.getByRole('button', { name: 'Запросить отказ', exact: true });
      await expect(close).toBeDisabled();
      await loss.getByLabel('Причина отказа', { exact: true }).selectOption(fixture.loss_reason);
      await loss.getByLabel('Комментарий к отказу', { exact: true }).fill('Synthetic loss');
      const commands: string[] = [];
      await page.route(`**/api/sales/deals/${deal.id}/lose`, async route => {
        commands.push(route.request().postData()!);
        if (commands.length === 1) return route.fulfill({ status: 503, contentType: 'application/json',
          body: '{"detail":"synthetic retry"}' });
        if (commands.length === 2 && mode === 'on_order') {
          expect((await route.fetch()).status()).toBe(200);
          return route.abort('failed');
        }
        return route.continue();
      });
      await close.click();
      await expect(loss.getByRole('alert')).toContainText('503');
      await expect(loss.getByText(/Результат исходной команды не установлен/)).toBeVisible();
      const journal = await page.evaluate(({ org, dealId }) => {
        const raw = sessionStorage.getItem(`deal-loss:v1:e2e_owner:${org}:${dealId}`);
        return raw ? JSON.parse(raw) : null;
      }, { org: fixture.organization, dealId: deal.id });
      expect(journal.body).toBe(commands[0]);
      expect(JSON.parse(journal.body).reason_code).toBe(fixture.loss_reason);
      expect(JSON.parse(journal.body).comment).toBe('Synthetic loss');
      expect((await preserved()).stage).toBe('qual');
      const retry = loss.getByRole('button', { name: 'Повторить исходную команду', exact: true });
      if (mode === 'on_order') {
        await retry.click();
        await expect(loss.getByRole('alert')).toContainText('Нет ответа сервера');
        expect((await preserved()).stage).toBe('qual');
      }
      const requested = page.waitForResponse(r => r.url().endsWith(`/deals/${deal.id}/lose`) && r.status() === 200);
      await retry.click();
      const requestReceipt = await (await requested).json();
      expect(requestReceipt.state).toBe('pending');
      expect(requestReceipt.replayed).toBe(mode === 'on_order');
      expect(commands.length).toBe(mode === 'on_order' ? 3 : 2);
      expect(new Set(commands).size).toBe(1);
      await expect(loss.getByText(/ожидает завершения/)).toBeVisible();
      await loss.getByLabel('Основание завершения или отзыва', { exact: true }).fill('Synthetic complete reconciliation');
      const finalize = loss.getByRole('button', { name: 'Завершить отказ', exact: true });
      await expect(finalize).toBeDisabled();
      expect((await preserved()).stage).toBe('qual');
      expect((await page.request.post(path + '/win')).status()).toBe(409);
      expect((await page.request.patch(path, { data: { stage: 'won' } })).status()).toBe(409);

      // Chief confirms the existing cancellation contract using synthetic archives.
      // Loss cannot silently cancel an issued invoice or release its reservation.
      const prefix = `/api/sales/organizations/${fixture.organization}/invoices/${invoice.id}`;
      const moneyBasis = await read(prefix + '/money-reconciliation');
      const reconciled = await control.request.post(prefix + '/money-reconciliation', { data: {
        source_key: randomUUID(), expected_basis_digest: moneyBasis.basis_digest,
        history_from: moneyBasis.required_history_from, history_through: moneyBasis.required_history_through,
        evidence: 'Synthetic complete bank and cash reconciliation',
        source_references: ['Synthetic bank archive', 'Synthetic cash archive'], all_money_sources_checked: true,
      } });
      expect(reconciled.status(), await reconciled.text()).toBe(201);
      const identity = { expected_version: invoice.version, expected_content_sha256: invoice.content_sha256 };
      const previewReply = await control.request.post(prefix + '/cancellation/preview', { data: identity });
      expect(previewReply.status(), await previewReply.text()).toBe(200);
      const basis = await previewReply.json();
      const bounds = basis.sections.legacy_fulfillment.facts;
      const reviewReply = await control.request.post(prefix + '/fulfillment-review', { data: {
        ...identity, request_key: randomUUID(), expected_basis_digest: basis.basis_digest,
        money_reconciliation_id: (await reconciled.json()).id, evidence: 'Synthetic complete fulfillment archive',
        external_sources: [{ system: 'Synthetic warehouse', reference: `Archive invoice ${invoice.id}`,
          history_from: bounds.required_history_from, history_through: bounds.required_history_through,
          confirmed_no_fulfillment: true }], all_fulfillment_sources_identified: true,
      } });
      expect(reviewReply.status(), await reviewReply.text()).toBe(201);
      const review = await reviewReply.json();
      const cancellation = { ...identity, request_key: randomUUID(), fulfillment_review_id: review.review_id,
        expected_review_digest: review.review_digest, evidence: 'Synthetic lost deal, fully reconciled',
        acknowledge_invoice_invalidation: true };
      const cancelled = await control.request.post(prefix + '/cancel', { data: cancellation });
      expect(cancelled.status(), await cancelled.text()).toBe(201);
      expect((await cancelled.json()).reserve_status).toBe('released');
      expect((await cancelled.json()).customer_notification).toBe('not_sent');
      expect(await (await control.request.post(prefix + '/cancel', { data: cancellation })).json()).toEqual(await cancelled.json());
      invoiceCancelled = true;
      expect((await preserved()).stage).toBe('qual');
      await loss.getByRole('button', { name: 'Обновить сведения', exact: true }).click();
      await expect(finalize).toBeEnabled();
      const finalized = page.waitForResponse(r => r.url().endsWith(`/loss-requests/${requestReceipt.request_id}/finalize`)
        && r.request().method() === 'POST');
      await finalize.click();
      const resolution = await finalized;
      expect(resolution.status()).toBe(200);
      const resolutionBody = resolution.request().postDataJSON();
      const resolutionPath = `/api/sales/organizations/${fixture.organization}/deals/${deal.id}/loss-requests/${requestReceipt.request_id}/finalize`;
      expect(await (await page.request.post(resolutionPath, { data: resolutionBody,
        headers: { 'X-Expected-Principal': 'e2e_owner' } })).json()).toEqual(await resolution.json());
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
          expect((await other.request.post(path + '/' + outcome, { data: JSON.parse(commands[0]),
            headers: { 'X-Expected-Principal': 'e2e_foreign' } })).status()).toBe(404);
        }
        expect((await other.request.patch(path, { data: { stage: 'qual' } })).status()).toBe(404);
        expect((await other.request.get(`/api/sales/documents/${invoice.id}/render`)).status()).toBe(404);
      } finally { await foreign.close(); }
      expect(await preserved()).toEqual(final);
      await writeFile(test.info().outputPath('preservation.json'), JSON.stringify({ mode, deal_id: deal.id, before, final }, null, 2));
    } finally { await control.close(); }
  });
}
