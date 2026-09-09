const path=require('node:path');
const {chromium,expect}=require('../frontend/node_modules/@playwright/test');
(async()=>{
 const browser=await chromium.launch({headless:true,channel:'msedge'});
 try {
  const page=await browser.newPage({viewport:{width:1440,height:1100}});
  const origin='http://127.0.0.1:18817';
  const state=await(await page.request.get('http://127.0.0.1:18816/qa/state')).json();
  await page.context().addCookies([{name:'aios_role',value:'director',url:origin},{name:'aios_user',value:'Synthetic QA',url:origin}]);
  await page.goto(origin+'/crm/deals');
  await expect(page.getByTestId('deals-client-ready')).toBeVisible();
  await page.getByText('Контроль отправки CRM',{exact:true}).first().click();
  await page.getByRole('button',{name:'Email документов',exact:true}).click();
  const panel=page.getByRole('region',{name:'Отправка документов по email'});
  const letter=panel.locator('article').filter({has:page.getByText('Контроль потери ответа SMTP',{exact:true})});
  await letter.getByText('Попытки и идентификатор',{exact:true}).click();
  await expect(letter.getByText(/№ 1.*Результат отправки неизвестен/)).toBeVisible();
  await expect(letter.getByText(/№ 2.*SMTP 250/)).toBeVisible();
  await letter.screenshot({path:path.join(state.output,'browser-attempts.png')});
  console.log('PASS: visible attempt history retains uncertain attempt and subsequent SMTP250');
 } finally {await browser.close();}
})().catch(e=>{console.error(e);process.exit(1)});
