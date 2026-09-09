const path = require('node:path');
const fs = require('node:fs');
const crypto = require('node:crypto');
const { chromium, expect } = require('../frontend/node_modules/@playwright/test');
const origin = 'http://127.0.0.1:18817';
const backend = 'http://127.0.0.1:18816';
(async () => {
  const browser = await chromium.launch({headless:true, channel:'msedge'});
  try {
    const page = await browser.newPage({viewport:{width:1440,height:1100}});
    const state = await (await page.request.get(backend+'/qa/state')).json();
    const output = state.output;
    await page.context().addCookies([{name:'aios_role',value:'director',url:origin},{name:'aios_user',value:'Synthetic QA',url:origin}]);
    await page.goto(origin+'/crm/deals');
    await expect(page.getByTestId('deals-client-ready')).toBeVisible();
    await page.getByText('Контроль отправки CRM',{exact:true}).first().click();
    await page.getByRole('button',{name:'Email документов',exact:true}).click();
    const panel = page.getByRole('region',{name:'Отправка документов по email'});
    await panel.getByRole('button',{name:'Проверить перед отправкой'}).click();
    await expect(panel.getByText('Подготовлено — не отправлено',{exact:true}).first()).toBeVisible();
    const queued = await (await page.request.get(backend+'/qa/state')).json();
    expect(queued.received).toBe(0);
    const letter = await (await page.request.get(origin+`/api/sales/deals/${state.deal_id}/emails/${state.email_id}`)).json();
    for (let i=0; i<letter.attachments.length; i++) {
      const pdf = await (await page.request.get(origin+`/api/sales/deals/${state.deal_id}/emails/${state.email_id}/attachments/${i}`)).body();
      expect(crypto.createHash('sha256').update(pdf).digest('hex')).toBe(letter.attachments[i].sha256);
    }
    await panel.screenshot({path:path.join(output,'browser-preview.png')});
    await panel.getByRole('button',{name:'Подтвердить отправку',exact:true}).dblclick();
    await expect(panel.getByText('Принято почтовым сервером',{exact:true})).toBeVisible({timeout:45000});
    await expect(panel.getByText(/Доставка и прочтение не подтверждены/)).toBeVisible();
    await page.request.post(origin+`/api/sales/deals/${state.deal_id}/emails/${state.email_id}/send`,{data:{}});
    const first = await (await page.request.get(backend+'/qa/verify')).json();
    expect(first.smtp_received).toBe(1);
    expect(first.smtp_attempts).toBe(1);
    await panel.screenshot({path:path.join(output,'browser-accepted.png')});

    async function compose(subject, mode) {
      await page.request.post(backend+'/qa/mode/'+mode);
      await panel.getByLabel('Кому (To)',{exact:true}).fill('control@example.test');
      await panel.getByLabel('Копия (CC)',{exact:true}).fill('copy@example.test');
      await panel.getByLabel('Тема',{exact:true}).fill(subject);
      await panel.getByRole('button',{name:'Подготовить и проверить',exact:true}).click();
      await expect(panel.getByRole('button',{name:'Подтвердить отправку',exact:true})).toBeVisible({timeout:60000});
      await panel.getByRole('button',{name:'Подтвердить отправку',exact:true}).click();
      return panel.locator('article').filter({has:page.getByText(subject,{exact:true})});
    }
    const failure = await compose('Контроль отказа SMTP', 'failed');
    await expect(failure.getByText('Не отправлено',{exact:true})).toBeVisible({timeout:45000});
    await failure.screenshot({path:path.join(output,'browser-failed.png')});
    await page.request.post(backend+'/qa/mode/accepted');
    await failure.getByRole('button',{name:'Повторить это письмо',exact:true}).click();
    await expect(failure.getByText('Принято почтовым сервером',{exact:true})).toBeVisible({timeout:45000});
    await expect(failure.getByText(/Попыток: 2/)).toBeVisible();
    const uncertain = await compose('Контроль потери ответа SMTP', 'uncertain');
    await expect(uncertain.getByText('Результат отправки неизвестен',{exact:true})).toBeVisible({timeout:45000});
    await expect(uncertain.getByRole('button',{name:'Повторить это письмо',exact:true})).toBeDisabled();
    await uncertain.screenshot({path:path.join(output,'browser-uncertain.png')});
    const uncertainState = await (await page.request.get(backend+'/qa/state')).json();
    await page.waitForTimeout(4200);
    expect((await (await page.request.get(backend+'/qa/state')).json()).attempts).toBe(uncertainState.attempts);
    await uncertain.getByRole('checkbox').check();
    await page.request.post(backend+'/qa/mode/accepted');
    await uncertain.getByRole('button',{name:'Повторить это письмо',exact:true}).click();
    await expect(uncertain.getByText('Принято почтовым сервером',{exact:true})).toBeVisible({timeout:45000});
    const finalState = await (await page.request.get(backend+'/qa/state')).json();
    expect(finalState.received).toBe(4);
    expect(finalState.attempts).toBe(5);
    const evidence = {...first, browser:'Microsoft Edge headless', preview_before_send:true,
      double_click_one_delivery:true, fixed_old_version_sent:true, failed_then_manual_retry:true,
      uncertain_no_auto_retry:true, duplicate_ack_required:true, final_received:finalState.received,
      final_attempts:finalState.attempts};
    fs.writeFileSync(path.join(output,'browser-evidence.json'),JSON.stringify(evidence,null,2));
    await panel.screenshot({path:path.join(output,'browser-final-history.png')});
    console.log('PASS: preview, frozen PDFs, double click, actual SMTP, rejection/manual retry, uncertain/acknowledged retry');
    console.log(output);
  } finally { await browser.close(); }
})().catch(error=>{console.error(error);process.exit(1)});
