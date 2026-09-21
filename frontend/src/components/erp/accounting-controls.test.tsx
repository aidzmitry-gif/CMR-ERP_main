import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import { AccountingControls } from "./accounting-controls";

const fetchMock = vi.fn();
const closingAccounts = (org = 1) => [
  { organization_id: org, code: "11", title: "Расход", category: "expense", cash: false, quantity_tracking: false, required_dimensions: [] },
  { organization_id: org, code: "91", title: "Результат", category: "income", cash: false, quantity_tracking: false, required_dimensions: ["department"] },
  { organization_id: org, code: "81", title: "Капитал", category: "equity", cash: false, quantity_tracking: false, required_dimensions: ["owner"] },
];
const toggle = () => screen.getByRole("checkbox", {name:"Задать настройки переноса финансового результата"});
const submitPolicy = () => screen.getByRole("button", {name:"Утвердить версию политики"});
const policyPosts = () => fetchMock.mock.calls.filter(([url, opt]) => url.endsWith("/policies") && opt?.method === "POST");
function policyBase() {
  fireEvent.change(screen.getAllByLabelText("Действует с")[1], {target:{value:"2026-10-01"}});
  for (const [label,value] of [["Приказ об учётной политике","POLICY"],["Метод оценки запасов","specific"],["База распределения","direct_cost"],["Метод амортизации","straight_line"],["Проверенная нормативная база","Reviewed"]]) fireEvent.change(screen.getByLabelText(label),{target:{value}});
  fireEvent.click(screen.getByLabelText("Бухгалтер проверил применимую нормативную редакцию"));
}
function setupClosing(rows=closingAccounts()) {
  fetchMock.mockImplementation((url:string) => respond(url.includes("/accounts?on=") ? rows : url.endsWith("/catalog") ? {version:"test",accounts:[]} : []));
}
async function filled(treatment="include") {
  fireEvent.click(toggle()); fireEvent.click(await screen.findByRole("checkbox",{name:"11 · Расход"}));
  for(const [label,value] of [["Счёт финансового результата","91"],["Счёт накопленного результата","81"],["Подразделение счёта финансового результата","DEPT"],["Владелец счёта накопленного результата","OWNER"],["Месяц окончания финансового года","9"],["Начальные остатки в расчёте переноса",treatment]]) fireEvent.change(screen.getByLabelText(label),{target:{value}});
  fireEvent.change(screen.getByRole("textbox",{name:"Основание настроек переноса",exact:true}),{target:{value:"Explicit policy"}});
}
const respond = (data: unknown, ok = true) => Promise.resolve({ ok, json: async () => data });
const openingCommand = () => ({
  batch: "opening-2026-09",
  request_key: "00000000-0000-4000-8000-000000000001",
  protocol_version: "opening-balance-v1",
  source_system: "1c-export",
  source_digest: "a".repeat(64),
  cutover_date: "2026-09-01",
  evidence: "Approved opening reconciliation protocol",
  expected_entry_count: 1,
  expected_line_count: 2,
  expected_debit_byn: "100.00",
  expected_credit_byn: "100.00",
  entries: [{ source: "1c:opening:1", source_version: 1 }],
});
const jsonFile = (value: unknown) => {
  const bytes = new TextEncoder().encode(JSON.stringify(value));
  return { name: "opening.json", size: bytes.byteLength, arrayBuffer: async () => bytes.buffer } as unknown as File;
};
const openingPreview = (command: ReturnType<typeof openingCommand>, organization_id = 1) => ({
  organization_id,
  batch: command.batch,
  request_key: command.request_key,
  cutover_date: command.cutover_date,
  source_system: command.source_system,
  source_digest: command.source_digest,
  command_digest: "b".repeat(64),
  control_totals: { entry_count: command.expected_entry_count, line_count: command.expected_line_count, debit_byn: "100.00", credit_byn: "100.00" },
  confirmed: false,
});
const openingReceipt = (command: ReturnType<typeof openingCommand>) => ({
  ...openingPreview(command),
  confirmed: true,
  receipt_id: 8,
  entry_ids: [18],
  evidence: command.evidence,
  digest: "c".repeat(64),
  created_at: "2026-09-21T00:00:00Z",
});

it("submits production configuration through the existing policy form", async () => {
  setupClosing([
    { organization_id: 1, code: "20", title: "НЗП", category: "asset", cash: false, currency_tracking: false, quantity_tracking: false, required_dimensions: ["order", "department"] },
    { organization_id: 1, code: "25", title: "Накладные", category: "asset", cash: false, currency_tracking: false, quantity_tracking: false, required_dimensions: ["department"] },
  ]);
  render(<AccountingControls org="1" onChanged={vi.fn()} />); policyBase();
  fireEvent.click(screen.getByLabelText("Настроить затраты производства"));
  expect(submitPolicy()).toBeDisabled();
  fireEvent.change(screen.getByLabelText("Группировка производственных затрат"), { target: { value: "department" } });
  await screen.findByText("25 · Накладные");
  fireEvent.change(screen.getByLabelText("Счёт НЗП"), { target: { value: "20" } });
  fireEvent.click(screen.getByLabelText("25 · Накладные"));
  fireEvent.change(screen.getByLabelText("Округление производственных затрат"), { target: { value: "largest_remainder_cent" } });
  fireEvent.change(screen.getByLabelText("Основание распределения производственных затрат"), { target: { value: "Приказ о распределении затрат" } });
  fireEvent.click(submitPolicy());
  await waitFor(() => expect(policyPosts()).toHaveLength(1));
  expect(JSON.parse(policyPosts()[0][1].body).production_costing).toEqual({ overhead_accounts: ["25"], wip_account: "20",
    pool_dimensions: ["department"], order_dimension: "order", rounding: "largest_remainder_cent", reference: "Приказ о распределении затрат" });
});

it("late-cost policy requires explicit basis and rounding", async () => {
  setupClosing(); render(<AccountingControls org="1" onChanged={vi.fn()} />); policyBase();
  fireEvent.click(screen.getByLabelText("Настроить распределение поздних расходов"));
  expect(submitPolicy()).toBeDisabled();
  fireEvent.change(screen.getByLabelText("База поздних расходов"), { target: { value: "received_value" } });
  expect(submitPolicy()).toBeDisabled();
  fireEvent.change(screen.getByLabelText("Округление поздних расходов"), { target: { value: "largest_remainder_cent" } });
  fireEvent.click(submitPolicy());
  await waitFor(() => expect(policyPosts()).toHaveLength(1));
  expect(JSON.parse(policyPosts()[0][1].body).late_cost_allocation).toEqual({ basis: "received_value", rounding: "largest_remainder_cent" });
});

it("late-cost choices do not transfer to a different policy date", () => {
  setupClosing(); render(<AccountingControls org="1" onChanged={vi.fn()} />); policyBase();
  fireEvent.click(screen.getByLabelText("Настроить распределение поздних расходов"));
  fireEvent.change(screen.getByLabelText("База поздних расходов"), { target: { value: "quantity" } });
  fireEvent.change(screen.getAllByLabelText("Действует с")[1], { target: { value: "2026-11-01" } });
  expect(screen.getByLabelText("Настроить распределение поздних расходов")).not.toBeChecked();
  expect(screen.queryByLabelText("База поздних расходов")).not.toBeInTheDocument();
});
beforeEach(() => {
  vi.stubGlobal("fetch", fetchMock);
  fetchMock.mockImplementation((url: string, options?: RequestInit) => {
    if (options?.method === "POST" || options?.method === "PUT") return respond({ id: 1 });
    if (url.endsWith("catalog")) return respond({ version: "review-required", accounts: [{ code: "51", title: "Расчётные счета" }] });
    return respond([]);
  });
});
afterEach(() => { vi.unstubAllGlobals(); vi.clearAllMocks(); });

it("does not silently choose policy methods or certify the normative basis", async () => {
  render(<AccountingControls org="1" onChanged={vi.fn()} />);
  await screen.findByLabelText("Счёт из справочника");
  expect(screen.getByLabelText("Метод оценки запасов")).toHaveValue("");
  expect(screen.getByText("Утвердить версию политики")).toBeDisabled();
  expect(screen.getByLabelText("Бухгалтер проверил применимую нормативную редакцию")).not.toBeChecked();
  fireEvent.change(screen.getByLabelText("Приказ об учётной политике"), { target: { value: "Приказ 1" } });
  fireEvent.change(screen.getByLabelText("Метод оценки запасов"), { target: { value: "fifo" } });
  fireEvent.change(screen.getByLabelText("База распределения"), { target: { value: "direct_cost" } });
  fireEvent.change(screen.getByLabelText("Метод амортизации"), { target: { value: "straight_line" } });
  fireEvent.change(screen.getByLabelText("Проверенная нормативная база"), { target: { value: "Подлежит проверке" } });
  fireEvent.click(screen.getByText("Утвердить версию политики"));
  await screen.findByText("Версия политики сохранена.");
  const call = fetchMock.mock.calls.find(([url, init]) => url.endsWith("policies") && init.method === "POST");
  expect(JSON.parse(call?.[1].body).normative_verified).toBe(false);
});

it("requires every closing check and transmits the reviewed generation", async () => {
  fetchMock.mockImplementation((url: string, options?: RequestInit) => {
    if (options?.method === "POST") return respond({ detail: "Data changed after review" }, false);
    if (url.endsWith("periods")) return respond([{ month: "2026-09", generation: 7, closed: false }]);
    if (url.endsWith("catalog")) return respond({ version: "draft", accounts: [] });
    return respond([]);
  });
  render(<AccountingControls org="1" onChanged={vi.fn()} />);
  await screen.findByLabelText("Счёт из справочника");
  fireEvent.click(screen.getByText("Закрытие месяца"));
  fireEvent.change(screen.getByLabelText("Месяц закрытия"), { target: { value: "2026-09" } });
  expect(screen.getByText("Подтвердить проверки и закрыть")).toBeDisabled();
  for (const input of screen.getAllByPlaceholderText("Протокол сверки / документ с результатом проверки")) fireEvent.change(input, { target: { value: "Протокол 123" } });
  fireEvent.click(screen.getByText("Подтвердить проверки и закрыть"));
  expect(await screen.findByRole("alert")).toHaveTextContent("Data changed after review");
  const call = fetchMock.mock.calls.find(([url]) => url.endsWith("/close"));
  expect(JSON.parse(call?.[1].body).expected_generation).toBe(7);
  expect(screen.queryByText("Месяц заблокирован.")).not.toBeInTheDocument();
});

it("shows source lines before explicit inbox confirmation", async () => {
  fetchMock.mockImplementation((url: string, options?: RequestInit) => {
    if (options?.method === "POST") return respond({ id: 5 });
    if (url.endsWith("inbox")) return respond([{ id: 4, event_key: "receipt-1", month: "2026-09", error: null, payload: { source: "procurement:receipt:8", source_version: 2, operation: "inventory_purchase", document_date: "2026-09-01", operation_date: "2026-09-02", posting_date: "2026-09-03", policy_id: 7, rule_version: "purchase-v1", explanation: "Поступление", lines: [{ side: "debit", account: "41", amount: "123.45", dimensions: { warehouse: "Основной", sku: "SKU-1" }, currency: "USD", original_amount: "40.00", rate: "3.08625", rate_scale: 1, rate_date: "2026-09-01", rate_source: "НБ РБ", quantity: "2.00" }] } }]);
    if (url.endsWith("catalog")) return respond({ version: "draft", accounts: [] });
    return respond([]);
  });
  render(<AccountingControls org="1" onChanged={vi.fn()} />);
  await screen.findByLabelText("Счёт из справочника");
  fireEvent.click(screen.getByText("Не проведено"));
  fireEvent.click(await screen.findByText("receipt-1 · 2026-09"));
  expect(screen.getByText("Дт 41 — 123.45 USD · количество 2.00")).toBeInTheDocument();
  expect(screen.getByText("Аналитика: warehouse=Основной · sku=SKU-1")).toBeInTheDocument();
  expect(screen.getByText(/Исходная сумма: 40.00 USD; курс 3.08625/)).toBeInTheDocument();
  expect(screen.getByText("procurement:receipt:8 · версия 2")).toBeInTheDocument();
  expect(screen.getByText("inventory_purchase · правило purchase-v1")).toBeInTheDocument();
  expect(fetchMock.mock.calls.some(([, options]) => options.method === "POST")).toBe(false);
  fireEvent.click(screen.getByText("Подтвердить пакет и повторить проведение"));
  await waitFor(() => expect(fetchMock.mock.calls.some(([url]) => url.endsWith("/inbox/4/confirm"))).toBe(true));
});

it("lists primary receipts separately from posting event packages", async () => {
  fetchMock.mockImplementation((url: string) => respond(url.endsWith("source-controls") ? [{ id: 8, source: "procurement:receipt:8", version: 2, month: "2026-09" }] : url.endsWith("catalog") ? { version: "test", accounts: [] } : []));
  render(<AccountingControls org="1" onChanged={vi.fn()} />);
  fireEvent.click(screen.getByText("Не проведено"));
  await screen.findByText(/procurement:receipt:8/);
  expect(screen.queryByText("Нет ожидающих документов.")).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Открыть поступление" })).toBeInTheDocument();
  expect(screen.queryByRole("link", { name: "Открыть первичные накладные" })).not.toBeInTheDocument();
});

it('preserves the old policy payload without optional settings', async()=>{
 setupClosing();render(<AccountingControls org="1" onChanged={vi.fn()}/>);policyBase();fireEvent.click(submitPolicy());await waitFor(()=>expect(policyPosts()).toHaveLength(1));expect(JSON.parse(policyPosts()[0][1].body)).toEqual({effective_from:'2026-10-01',reference:'POLICY',inventory_method:'specific',allocation_basis:'direct_cost',depreciation_method:'straight_line',normative_reference:'Reviewed',normative_verified:true});expect(fetchMock.mock.calls.some(([url])=>url.includes('/accounts?'))).toBe(false);
});
it.each(['include','exclude'])('saves exact explicit %s configuration, no other write',async treatment=>{
 setupClosing();render(<AccountingControls org="1" onChanged={vi.fn()}/>);policyBase();await filled(treatment);expect(submitPolicy()).toBeEnabled();fireEvent.click(submitPolicy());await waitFor(()=>expect(policyPosts()).toHaveLength(1));const body=JSON.parse(policyPosts()[0][1].body);expect(body).toMatchObject({effective_from:'2026-10-01',reference:'POLICY',inventory_method:'specific',allocation_basis:'direct_cost',depreciation_method:'straight_line',normative_reference:'Reviewed',normative_verified:true});expect(body.financial_closing).toEqual({monthly_accounts:['11'],result_account:'91',retained_earnings_account:'81',year_end_month:9,result_dimensions:{department:'DEPT'},retained_dimensions:{owner:'OWNER'},opening_balance_treatment:treatment,reference:'Explicit policy'});expect(fetchMock.mock.calls.filter(([,o])=>o?.method==='POST')).toHaveLength(1);expect(fetchMock.mock.calls.some(([u])=>u==='/api/accounting/organizations/1/accounts?on=2026-10-01')).toBe(true);expect(screen.getByText(/Механизм месячного и годового переноса финансового результата ещё не активен/)).toBeInTheDocument();
});
it('has no guessed choices and excludes incompatible account tracking',async()=>{
 setupClosing([...closingAccounts(),{...closingAccounts()[0],code:'51',title:'Cash',cash:true},{...closingAccounts()[0],code:'52',title:'Qty',quantity_tracking:true},{...closingAccounts()[0],code:'53',title:'Asset',category:'asset'}]);render(<AccountingControls org="1" onChanged={vi.fn()}/>);policyBase();fireEvent.click(toggle());await screen.findByLabelText('Счёт финансового результата');for(const label of ['Счёт финансового результата','Счёт накопленного результата','Месяц окончания финансового года','Начальные остатки в расчёте переноса'])expect(screen.getByLabelText(label)).toHaveValue('');for(const name of ['51 · Cash','52 · Qty','53 · Asset'])expect(screen.queryByRole('checkbox',{name})).not.toBeInTheDocument();expect(screen.getByRole('checkbox',{name:'11 · Расход'})).not.toBeChecked();expect(submitPolicy()).toBeDisabled();
});
it.each(['','  ','\0','x'.repeat(201)])('blocks invalid target analytics %j',async value=>{
 setupClosing();render(<AccountingControls org="1" onChanged={vi.fn()}/>);policyBase();await filled();fireEvent.change(screen.getByLabelText('Подразделение счёта финансового результата'),{target:{value}});expect(submitPolicy()).toBeDisabled();fireEvent.click(submitPolicy());expect(policyPosts()).toHaveLength(0);
});
it('prevents role overlap and clears target analytics on account changes',async()=>{
 setupClosing([...closingAccounts(),{...closingAccounts()[1],code:'92',title:'No analytics',required_dimensions:[]}]);render(<AccountingControls org="1" onChanged={vi.fn()}/>);policyBase();await filled();expect(screen.getByRole('checkbox',{name:'91 · Результат'})).toBeDisabled();fireEvent.change(screen.getByLabelText('Счёт финансового результата'),{target:{value:'92'}});expect(screen.getByText('Аналитика не требуется этим счётом.')).toBeInTheDocument();expect(submitPolicy()).toBeEnabled();fireEvent.change(screen.getByLabelText('Счёт финансового результата'),{target:{value:'91'}});expect(screen.getByLabelText('Подразделение счёта финансового результата')).toHaveValue('');expect(submitPolicy()).toBeDisabled();
});
it('resets closing choices on effective date change, preserving existing policy fields',async()=>{
 setupClosing();render(<AccountingControls org="1" onChanged={vi.fn()}/>);policyBase();await filled();fireEvent.change(screen.getAllByLabelText('Действует с')[1],{target:{value:'2026-11-01'}});expect(toggle()).toBeChecked();expect(submitPolicy()).toBeDisabled();expect(screen.getByLabelText('Приказ об учётной политике')).toHaveValue('POLICY');await screen.findByLabelText('Счёт финансового результата');expect(screen.getByLabelText('Счёт финансового результата')).toHaveValue('');expect(submitPolicy()).toBeDisabled();
});
it('ignores a delayed prior organization response',async()=>{
 let resolveOld!:(v:unknown)=>void;fetchMock.mockImplementation((url:string)=>url.includes('/organizations/1/accounts?')?new Promise(r=>{resolveOld=r;}):respond(url.includes('/accounts?')?closingAccounts(2):url.endsWith('/catalog')?{version:'test',accounts:[]}:[]));const view=render(<AccountingControls org="1" onChanged={vi.fn()}/>);policyBase();fireEvent.click(toggle());await waitFor(()=>expect(resolveOld).toBeDefined());view.rerender(<AccountingControls org="2" onChanged={vi.fn()}/>);fireEvent.click(toggle());await screen.findByLabelText('Счёт финансового результата');await act(async()=>resolveOld({ok:true,json:async()=>[{...closingAccounts()[0],title:'STALE-ORG'}]}));await waitFor(()=>expect(screen.queryByText(/STALE-ORG/)).not.toBeInTheDocument());expect(submitPolicy()).toBeDisabled();
});
it('load error blocks enabled configuration and retry loads accounts',async()=>{
 let failed=true;fetchMock.mockImplementation((url:string)=>url.includes('/accounts?')?respond(failed?{}:closingAccounts(),!failed):respond(url.endsWith('/catalog')?{version:'test',accounts:[]}:[]));render(<AccountingControls org="1" onChanged={vi.fn()}/>);policyBase();fireEvent.click(toggle());await screen.findByRole('alert');expect(submitPolicy()).toBeDisabled();failed=false;fireEvent.click(screen.getByRole('button',{name:'Повторить загрузку счетов закрытия'}));await screen.findByLabelText('Счёт финансового результата');expect(submitPolicy()).toBeDisabled();
});
it('server refusal retains inputs and does not signal success',async()=>{
 const changed=vi.fn();fetchMock.mockImplementation((url:string,opt?:RequestInit)=>opt?.method==='POST'?respond({detail:'Accounts changed'},false):respond(url.includes('/accounts?')?closingAccounts():url.endsWith('/catalog')?{version:'test',accounts:[]}:[]));render(<AccountingControls org="1" onChanged={changed}/>);policyBase();await filled();fireEvent.click(submitPolicy());expect(await screen.findByRole('alert')).toHaveTextContent('Accounts changed');expect(screen.getByRole('textbox',{name:'Основание настроек переноса',exact:true})).toHaveValue('Explicit policy');expect(changed).not.toHaveBeenCalled();expect(screen.queryByText('Версия политики сохранена.')).not.toBeInTheDocument();
});
it('disables inflight settings and avoids a duplicate policy POST',async()=>{
 let finish!:(v:unknown)=>void;fetchMock.mockImplementation((url:string,opt?:RequestInit)=>opt?.method==='POST'?new Promise(r=>{finish=r;}):respond(url.includes('/accounts?')?closingAccounts():url.endsWith('/catalog')?{version:'test',accounts:[]}:[]));render(<AccountingControls org="1" onChanged={vi.fn()}/>);policyBase();await filled();fireEvent.click(submitPolicy());fireEvent.click(submitPolicy());expect(policyPosts()).toHaveLength(1);expect(toggle()).toBeDisabled();expect(screen.getByLabelText('Счёт финансового результата')).toBeDisabled();finish({ok:true,json:async()=>({id:1})});await screen.findByText('Версия политики сохранена.');
});

it.each(['wrong-org','duplicate'])('rejects an unconfirmed %s account response',async mode=>{
 setupClosing(mode==='wrong-org'?closingAccounts(2):[...closingAccounts(),closingAccounts()[0]]);render(<AccountingControls org="1" onChanged={vi.fn()}/>);policyBase();fireEvent.click(toggle());expect(await screen.findByRole('alert')).toHaveTextContent('Ответ не подтверждает');expect(submitPolicy()).toBeDisabled();expect(policyPosts()).toHaveLength(0);
});
it('limits monthly selection to 200 distinct accounts',async()=>{
 setupClosing(Array.from({length:201},(_,i)=>({...closingAccounts()[0],code:String(1000+i),title:'Monthly '+i})));render(<AccountingControls org="1" onChanged={vi.fn()}/>);policyBase();fireEvent.click(toggle());await screen.findByRole('checkbox',{name:'1000 · Monthly 0'});const boxes=screen.getAllByRole('checkbox',{name:/^[0-9]+ · Monthly /});act(()=>{for(let i=0;i<200;i++)fireEvent.click(boxes[i]);});expect(screen.getByText('Выбрано: 200 из 200.')).toBeInTheDocument();expect(screen.getByRole('checkbox',{name:'1200 · Monthly 200'})).toBeDisabled();expect(submitPolicy()).toBeDisabled();
});
it.each(['','x'.repeat(1001)])('requires a bounded explicit closing reference %j',async value=>{
 setupClosing();render(<AccountingControls org="1" onChanged={vi.fn()}/>);policyBase();await filled();fireEvent.change(screen.getByRole('textbox',{name:'Основание настроек переноса',exact:true}),{target:{value}});expect(submitPolicy()).toBeDisabled();expect(policyPosts()).toHaveLength(0);
});


it('preserves enabled closing draft across section navigation',async()=>{
 setupClosing();render(<AccountingControls org="1" onChanged={vi.fn()}/>);policyBase();await filled();fireEvent.click(screen.getByRole('button',{name:'Закрытие месяца',exact:true}));fireEvent.click(screen.getByRole('button',{name:'Настройки книги',exact:true}));expect(toggle()).toBeChecked();expect(screen.getByLabelText('Счёт финансового результата')).toHaveValue('91');expect(screen.getByRole('textbox',{name:'Основание настроек переноса',exact:true})).toHaveValue('Explicit policy');fireEvent.click(submitPolicy());await waitFor(()=>expect(policyPosts()).toHaveLength(1));expect(JSON.parse(policyPosts()[0][1].body).financial_closing.result_account).toBe('91');
});

it("shows durable opening-balance protocol receipts", async () => {
  fetchMock.mockImplementation((url: string) => {
    if (url.endsWith("/imports")) return respond([{ receipt_id: 4, batch: "opening-1", request_key: "00000000-0000-0000-0000-000000000004", protocol_version: "opening-balance-v1", cutover_date: "2026-09-01", source_system: "1c-export", source_digest: "a".repeat(64), command_digest: "b".repeat(64), control_totals: { entry_count: 2, line_count: 4, debit_byn: "100.00", credit_byn: "100.00" }, confirmed: true, entry_ids: [8, 9], evidence: "Synthetic reconciliation protocol", digest: "c".repeat(64), created_at: "2026-09-12T00:00:00Z" }]);
    return respond(url.endsWith("catalog") ? { version: "test", accounts: [] } : []);
  });
  render(<AccountingControls org="1" initialSection="import" onChanged={vi.fn()} />);
  await screen.findByText("Протоколы переноса");
  expect(screen.getByText(/opening-1 · 2026-09-01 · 1c-export/)).toBeInTheDocument();
  expect(screen.getByText(/Дт 100.00 BYN = Кт 100.00 BYN/)).toBeInTheDocument();
  expect(screen.getByText(/Квитанция 4/)).toBeInTheDocument();
});

it("requires an explicit source digest instead of deriving one from the uploaded JSON", async () => {
  render(<AccountingControls org="1" initialSection="import" onChanged={vi.fn()} />);
  const command = openingCommand();
  const withoutDigest = { ...command };
  delete withoutDigest.source_digest;
  fireEvent.change(screen.getByLabelText("Файл остатков"), { target: { files: [jsonFile(withoutDigest)] } });
  expect(await screen.findByRole("alert")).toHaveTextContent("ERP не подставляет эти данные");
  expect(fetchMock.mock.calls.some(([url]) => String(url).endsWith("/imports/preview"))).toBe(false);
});

it("rejects an organization embedded in an opening package instead of silently routing it", async () => {
  render(<AccountingControls org="1" initialSection="import" onChanged={vi.fn()} />);
  fireEvent.change(screen.getByLabelText("Файл остатков"), { target: { files: [jsonFile({ ...openingCommand(), organization_id: 2 })] } });
  expect(await screen.findByRole("alert")).toHaveTextContent("Юрлицо не берётся из файла");
  expect(fetchMock.mock.calls.some(([url]) => String(url).endsWith("/imports/preview"))).toBe(false);
});

it("previews and confirms only the exact package for the selected organization", async () => {
  const command = openingCommand();
  const changed = vi.fn();
  fetchMock.mockImplementation((url: string) => {
    if (url.endsWith("/imports/preview")) return respond(openingPreview(command));
    if (url.endsWith("/imports/confirm")) return respond(openingReceipt(command));
    if (url.endsWith("catalog")) return respond({ version: "test", accounts: [] });
    return respond([]);
  });
  render(<AccountingControls org="1" initialSection="import" onChanged={changed} />);
  fireEvent.change(screen.getByLabelText("Файл остатков"), { target: { files: [jsonFile(command)] } });
  await screen.findByText(/Пакет: opening-2026-09/);
  const previewCall = fetchMock.mock.calls.find(([url]) => String(url).endsWith("/imports/preview"));
  expect(JSON.parse(previewCall?.[1].body)).toEqual(command);
  fireEvent.click(screen.getByRole("button", { name: "Подтвердить перенос остатков" }));
  expect(await screen.findByRole("status")).toHaveTextContent("Квитанция №8");
  const confirmCall = fetchMock.mock.calls.find(([url]) => String(url).endsWith("/imports/confirm"));
  expect(JSON.parse(confirmCall?.[1].body)).toEqual(command);
  expect(changed).toHaveBeenCalledTimes(1);
});

it("rejects a preview returned for another organization before it can be confirmed", async () => {
  const command = openingCommand();
  fetchMock.mockImplementation((url: string) => {
    if (url.endsWith("/imports/preview")) return respond(openingPreview(command, 2));
    if (url.endsWith("catalog")) return respond({ version: "test", accounts: [] });
    return respond([]);
  });
  render(<AccountingControls org="1" initialSection="import" onChanged={vi.fn()} />);
  fireEvent.change(screen.getByLabelText("Файл остатков"), { target: { files: [jsonFile(command)] } });
  expect(await screen.findByRole("alert")).toHaveTextContent("не подтверждающий выбранное юрлицо");
  expect(screen.queryByRole("button", { name: "Подтвердить перенос остатков" })).not.toBeInTheDocument();
});

it("retries an unknown confirmation with the frozen exact opening package", async () => {
  const command = openingCommand();
  let confirms = 0;
  fetchMock.mockImplementation((url: string) => {
    if (url.endsWith("/imports/preview")) return respond(openingPreview(command));
    if (url.endsWith("/imports/confirm")) {
      confirms += 1;
      return confirms === 1 ? Promise.reject(new Error("network unavailable")) : respond(openingReceipt(command));
    }
    if (url.endsWith("catalog")) return respond({ version: "test", accounts: [] });
    return respond([]);
  });
  render(<AccountingControls org="1" initialSection="import" onChanged={vi.fn()} />);
  fireEvent.change(screen.getByLabelText("Файл остатков"), { target: { files: [jsonFile(command)] } });
  await screen.findByText(/Пакет: opening-2026-09/);
  fireEvent.click(screen.getByRole("button", { name: "Подтвердить перенос остатков" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("Результат подтверждения неизвестен");
  expect(screen.getByLabelText("Файл остатков")).toBeDisabled();
  fireEvent.click(screen.getByRole("button", { name: "Повторить подтверждение того же пакета" }));
  expect(await screen.findByText(/Квитанция №8/)).toBeInTheDocument();
  const calls = fetchMock.mock.calls.filter(([url]) => String(url).endsWith("/imports/confirm"));
  expect(calls).toHaveLength(2);
  expect(JSON.parse(calls[0][1].body)).toEqual(JSON.parse(calls[1][1].body));
  expect(JSON.parse(calls[1][1].body)).toEqual(command);
});
