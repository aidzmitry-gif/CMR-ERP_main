"use client";

import { useEffect, useRef, useState } from "react";
import { AccountingPreparationDraft } from "./accounting-preparation-draft";
import { AccountingLotPicker } from "./accounting-lot-picker";
import { AccountingShipmentConfirm } from "./accounting-shipment-confirm";
import { Button } from "@/components/ui/button";
import { Input, Select } from "@/components/ui/input";
import { shipmentValidationMessage } from "@/lib/shipment-validation-message";

type Account = { code: string; title: string; required_dimensions: string[] };
type Act = { digest: string; source_key: string; snapshot: { organization_id: number; document_id: number; operation_date: string; lines: { source: string; line_no: number; warehouse: string; sku_code: string; qty: string }[] } };
type Allocation = { line_source: string; account: string; lot: string; quantity: string; expense_account: string; expense_dimensions: Record<string, string> };
type Terms = { line_no: number; net_amount: string; vat_rate: string; vat_basis: string; buyer_account: string; revenue_account: string; vat_revenue_account: string; vat_payable_account: string; buyer_dimensions: Record<string,string>; revenue_dimensions: Record<string,string>; vat_dimensions: Record<string,string> };
type Calculation = { organization_id: number; source: string; posted: boolean; status: string; net_byn: string; vat_byn: string; gross_byn: string; mapping: (Allocation & { cost_byn: string })[]; postings: { posting: { lines: { account: string; side: string; amount: string; quantity: string | null; dimensions: Record<string,string> }[] } }[] };
const names: Record<string,string> = { counterparty: "Контрагент", contract: "Договор", settlement_document: "Документ расчётов", warehouse: "Склад", sku: "Номенклатура", lot: "Партия", order: "Заказ", employee: "Сотрудник", asset: "Основное средство", department: "Подразделение" };
const keyOf = (org: string, source: string) => { const match = /^wms:physical-shipment:([1-9][0-9]*):([a-f0-9]{8}-(?:[a-f0-9]{4}-){3}[a-f0-9]{12})$/.exec(source); return match?.[1] === org ? match[2] : null; };

function AccountField({label, value, root, onChange, accounts}: {label: string; value: string; root: string; onChange: (value: string) => void; accounts: Account[]}) {
    return <label>{label}<Select aria-label={label} value={value} onChange={event => onChange(event.target.value)}><option value="">Выберите счёт</option>{accounts.filter(a => a.code === root || a.code.startsWith(root + ".")).map(a => <option key={a.code} value={a.code}>{a.code} · {a.title}</option>)}</Select></label>;
  }
function Dimensions({label, codes, values, onChange, required = [], accounts}: {label: string; codes: string[]; values: Record<string,string>; onChange: (value: Record<string,string>) => void; required?: string[]; accounts: Account[]}) {
    const keys = [...new Set([...required, ...Object.keys(values), ...codes.flatMap(code => accounts.find(a => a.code === code)?.required_dimensions ?? [])])];
    return keys.map(field => <label key={field}>{label} · {names[field] ?? field}<Input aria-label={`${label} · ${names[field] ?? field}`} value={field === "settlement_document" ? (values[field] ?? "").replace(/^sales:document:([1-9][0-9]*)$/, "Счёт № $1") : values[field] ?? ""} readOnly={field === "settlement_document" && /^sales:document:[1-9][0-9]*$/.test(values[field] ?? "")} onChange={event => onChange({ ...values, [field]: event.target.value })} /></label>);
  }

export function AccountingShipmentPreview({ org, source, accounts, date, policyId, disabled, onDate, onPosted }: { org: string; source: string; accounts: Account[]; date: string; policyId?: number; disabled: boolean; onDate: (date: string) => void; onPosted?: () => void | Promise<void> }) {
  const [act, setAct] = useState<Act | null>(null), [error, setError] = useState(() => keyOf(org, source) ? "" : "Источник не относится к выбранному юрлицу.");
  const [draftBusy, setDraftBusy] = useState(false);
  const [postingLocked, setPostingLocked] = useState(false);
  const [confirmation, setConfirmation] = useState<{ org: string; source: string; sourceKey: string; body: string; scope: string } | null>(null);
  const [loading, setLoading] = useState(() => !!keyOf(org, source)), [busy, setBusy] = useState(false);
  const [allocations, setAllocations] = useState<Allocation[]>([]), [terms, setTerms] = useState<Terms[]>([]);
  const [form, setForm] = useState({ document_date: "", explanation: "", recognition_basis: "", unit_basis: "", cost_allocation: "", vat_rounding: "" });
  const [result, setResult] = useState<{ scope: string; value: Calculation } | null>(null), [page, setPage] = useState(0);
  const pending = useRef<AbortController | null>(null);
  const scope = `${org}/${source}/${date}/${policyId}`;
  const [previousScope, setPreviousScope] = useState(scope);
  if (previousScope !== scope) {
    setPreviousScope(scope);
    setBusy(false);
    setResult(null);
    setError("");
  }
  const current = result?.scope === scope ? result.value : null;
  const key = keyOf(org, source);
  const sourceScope = `${org}/${key}`;
  const [previousSourceScope, setPreviousSourceScope] = useState(sourceScope);
  if (previousSourceScope !== sourceScope) {
    setPreviousSourceScope(sourceScope);
    setAct(null);
    setResult(null);
    setLoading(!!key);
    setError(key ? "" : "Источник не относится к выбранному юрлицу.");
  }
  useEffect(() => {
    // A parent can change the date/policy while a calculation is in flight.
    // Discard it permanently, including when the user returns to the old date.
    pending.current?.abort();
  }, [scope]);
  useEffect(() => {
    const controller = new AbortController();
    if (!key) return;
    void fetch(`/api/accounting/organizations/${org}/shipments/${key}/source`, { cache: "no-store", signal: controller.signal }).then(async response => {
      const data = await response.json();
      if (!response.ok) throw new Error(typeof data.detail === "string" ? data.detail : "Не удалось получить акт отгрузки.");
      const value = data as Act;
      if (String(value.snapshot.organization_id) !== org || value.source_key !== key) throw new Error("Получен акт другого источника.");
      if (controller.signal.aborted) return;
      setAct(value);
      setAllocations(value.snapshot.lines.map(line => ({ line_source: line.source, account: "", lot: "", quantity: line.qty, expense_account: "", expense_dimensions: {} })));
      setTerms([...new Set(value.snapshot.lines.map(line => line.line_no))].map(line_no => ({ line_no, net_amount: "", vat_rate: "", vat_basis: "", buyer_account: "", revenue_account: "", vat_revenue_account: "", vat_payable_account: "", buyer_dimensions: { settlement_document: `sales:document:${value.snapshot.document_id}` }, revenue_dimensions: {}, vat_dimensions: {} })));
    }).catch(reason => { if (!controller.signal.aborted) setError(reason instanceof Error ? reason.message : "Ошибка чтения акта."); }).finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => { controller.abort(); pending.current?.abort(); };
  }, [org, key]);
  function invalidate() { pending.current?.abort(); setBusy(false); setResult(null); setError(""); }
  function updateAllocation(index: number, patch: Partial<Allocation>) { invalidate(); setAllocations(rows => rows.map((row, i) => i === index ? { ...row, ...patch } : row)); }
  function updateTerms(index: number, patch: Partial<Terms>) { invalidate(); setTerms(rows => rows.map((row, i) => i === index ? { ...row, ...patch } : row)); }
  function restoreDraft(value: unknown) {
    const record = (row: unknown): row is Record<string, unknown> => !!row && typeof row === "object" && !Array.isArray(row);
    const strings = (row: unknown): row is Record<string,string> => record(row) && Object.entries(row).every(([key,value]) => key.length <= 200 && typeof value === "string" && value.length <= 1000);
    if (!act || !record(value) || value.act_digest !== act.digest || typeof value.posting_date !== "string" || !/^\d{4}-\d{2}-\d{2}$/.test(value.posting_date) || !strings(value.form) || !Object.keys(form).every(key => typeof (value.form as Record<string,string>)[key] === "string") || !Array.isArray(value.allocations) || value.allocations.length > 10000 || !Array.isArray(value.terms) || value.terms.length > 1000) throw new Error("Черновик повреждён или относится к другой версии акта.");
    const lines = new Set(act.snapshot.lines.map(line => line.source));
    const lineNumbers = new Set(act.snapshot.lines.map(line => line.line_no));
    if (!value.allocations.every(row => record(row) && ['line_source','account','lot','quantity','expense_account'].every(key => typeof row[key] === 'string' && row[key].length <= 200) && lines.has(String(row.line_source)) && strings(row.expense_dimensions)) || !value.terms.every(row => record(row) && typeof row.line_no === 'number' && lineNumbers.has(row.line_no) && ['net_amount','vat_rate','vat_basis','buyer_account','revenue_account','vat_revenue_account','vat_payable_account'].every(key => typeof row[key] === 'string' && row[key].length <= 200) && strings(row.buyer_dimensions) && row.buyer_dimensions.settlement_document === `sales:document:${act.snapshot.document_id}` && strings(row.revenue_dimensions) && strings(row.vat_dimensions))) throw new Error("Строки черновика не соответствуют акту или имеют неверный формат.");
    const restoredTerms = value.terms as Terms[];
    if (new Set(restoredTerms.map(row => row.line_no)).size !== restoredTerms.length || restoredTerms.length !== lineNumbers.size) throw new Error("Черновик не покрывает все строки счёта.");
    invalidate();
    setForm(Object.fromEntries(Object.keys(form).map(key => [key,(value.form as Record<string,string>)[key]])) as typeof form);
    setAllocations(value.allocations as Allocation[]); setTerms(restoredTerms); if (value.posting_date !== date) onDate(value.posting_date);
  }
  async function calculate() {
    if (!act || !policyId || !key || busy || disabled || postingLocked) return;
    if (Object.values(form).some(value => !value.trim())) { setError("Заполните даты, основания и методы расчёта."); return; }
    const controller = new AbortController(); pending.current?.abort(); pending.current = controller;
    setBusy(true); setResult(null); setError("");
    try {
      const inputs = { ...form, expected_act_digest: act.digest, policy_id: policyId, posting_date: date, recognition: "sale_on_shipment", allocations, commercial_lines: terms };
      const response = await fetch(`/api/accounting/organizations/${org}/shipments/${key}/preview`, { method: "POST", headers: { "Content-Type": "application/json" }, signal: controller.signal, body: JSON.stringify(inputs) });
      const data = await response.json();
      if (!response.ok) throw new Error(shipmentValidationMessage(data.detail));
      const value = data as Calculation;
      if (String(value.organization_id) !== org || value.source !== source || value.status !== "preview" || value.posted !== false) throw new Error("Получен результат другого источника или состояния.");
      if (!controller.signal.aborted) {
        setConfirmation(typeof data.basis_digest === "string" && /^[a-f0-9]{64}$/.test(data.basis_digest)
          ? { org, source, sourceKey: key, scope, body: JSON.stringify({ ...inputs, expected_basis_digest: data.basis_digest }) } : null);
        setResult({ scope, value }); setPage(0);
      }
    } catch (reason) { if (!controller.signal.aborted) setError(reason instanceof Error ? reason.message : "Расчёт не выполнен."); }
    finally { if (!controller.signal.aborted) setBusy(false); }
  }
  return <section aria-label="Подготовка отгрузки" className="min-w-0 space-y-4 break-words rounded-xl border border-line bg-surface p-4 [&_fieldset]:min-w-0 [&_label]:min-w-0 [&_legend]:max-w-full [&_select]:min-w-0 [&_button]:max-w-full [&_button]:whitespace-normal">
    <h2 className="font-semibold">Подготовка проводок по отгрузке</h2>
    <p>Предварительный расчёт продажи товаров в BYN при признании выручки по отгрузке. Источник останется в очереди до проведения.</p>
    {loading && <p role="status">Проверяется акт отгрузки…</p>}{error && <p role="alert">{error}</p>}
    {act && <>
      <p>Счёт № {act.snapshot.document_id} · Отгрузка {act.snapshot.operation_date} · Политика {policyId ? `№ ${policyId}` : "не выбрана для даты"}</p>
      {key && <AccountingPreparationDraft key={`${org}/${key}`} org={org} source={source} sourceKey={key} payload={{act_digest:act.digest,posting_date:date,policy_id:policyId ?? null,form,allocations,terms}} disabled={busy || disabled || postingLocked} onRestore={restoreDraft} onBusy={setDraftBusy} />}
      <fieldset disabled={busy || draftBusy || disabled || postingLocked} className="space-y-4">
        <div className="grid gap-3 md:grid-cols-2"><label>Дата отражения<Input aria-label="Дата отражения отгрузки" type="date" value={date} onChange={event => { invalidate(); onDate(event.target.value); }} /></label>
          {([['document_date','Дата первичного документа'],['explanation','Содержание операции'],['recognition_basis','Основание признания выручки'],['unit_basis','Основание соответствия единиц']] as const).map(([field,label]) => <label key={field}>{label}<Input aria-label={label} type={field === 'document_date' ? 'date' : 'text'} value={form[field]} onChange={event => { invalidate(); setForm({ ...form, [field]: event.target.value }); }} /></label>)}
          <label>Распределение стоимости<Select aria-label="Распределение стоимости" value={form.cost_allocation} onChange={event => { invalidate(); setForm({ ...form, cost_allocation: event.target.value }); }}><option value="">Выберите метод</option><option value="cumulative_floor_last">По накопленному количеству, остаток копеек последней доле</option></Select></label>
          <label>Округление НДС<Select aria-label="Округление НДС" value={form.vat_rounding} onChange={event => { invalidate(); setForm({ ...form, vat_rounding: event.target.value }); }}><option value="">Выберите метод</option><option value="commercial_line_half_up">До копеек по строке счёта, половина вверх</option></Select></label>
        </div>
        {act.snapshot.lines.map(line => <article key={line.source} className="space-y-3 rounded border border-line p-3"><h3>Строка счёта {line.line_no} · {line.sku_code} · Склад {line.warehouse} · Отгружено {line.qty}</h3>
          {allocations.map((row,index) => row.line_source === line.source && <fieldset key={index} aria-label={`Распределение ${index + 1}`} className="grid gap-3 border-b border-line pb-3 md:grid-cols-2">
            <AccountField accounts={accounts} label={`Счёт запасов ${index + 1}`} value={row.account} root='41' onChange={value => updateAllocation(index,{ account: value })} />
            <label>Партия<Input aria-label={`Партия ${index + 1}`} value={row.lot} onChange={event => updateAllocation(index,{lot:event.target.value})} /></label>
            <AccountingLotPicker key={`${org}/${date}/${policyId}/${row.account}/${line.warehouse}/${line.sku_code}`} org={org} date={date} policyId={policyId} account={row.account} warehouse={line.warehouse} sku={line.sku_code} onSelect={lot => updateAllocation(index,{lot})} />
            <label>Количество<Input aria-label={`Количество ${index + 1}`} value={row.quantity} onChange={event => updateAllocation(index,{quantity:event.target.value})} /></label>
            <AccountField accounts={accounts} label={`Счёт себестоимости ${index + 1}`} value={row.expense_account} root='90.4' onChange={value => updateAllocation(index,{expense_account:value,expense_dimensions:{}})} />
            <Dimensions accounts={accounts} label={`Расход ${index + 1}`} codes={[row.expense_account]} values={row.expense_dimensions} onChange={value => updateAllocation(index,{expense_dimensions:value})} />
            <Button variant="ghost" onClick={() => { invalidate(); setAllocations(rows => rows.filter((_,i) => i !== index)); }}>Удалить распределение {index + 1}</Button>
          </fieldset>)}
          <Button variant="secondary" onClick={() => { invalidate(); setAllocations(rows => [...rows,{line_source:line.source,account:"",lot:"",quantity:"",expense_account:"",expense_dimensions:{}}]); }}>Добавить партию для строки {line.line_no} · {line.warehouse}</Button>
        </article>)}
        {terms.map((row,index) => <fieldset key={row.line_no} aria-label={`Продажа строки ${row.line_no}`} className="grid gap-3 rounded border border-line p-3 md:grid-cols-2"><legend>Продажа по строке счёта {row.line_no} — вся отгруженная часть по всем складам</legend>
          {([['net_amount','Без НДС, BYN'],['vat_rate','Ставка НДС, %'],['vat_basis','Основание НДС']] as const).map(([field,label]) => <label key={field}>{label}<Input aria-label={`${label} · строка ${row.line_no}`} value={row[field]} onChange={event => updateTerms(index,{[field]:event.target.value})} /></label>)}
          {([['buyer_account','Покупатель','62'],['revenue_account','Выручка','90.1'],['vat_revenue_account','НДС из выручки','90.2'],['vat_payable_account','НДС к уплате','68']] as const).map(([field,label,root]) => <div key={field}><AccountField accounts={accounts} label={`${label} · строка ${row.line_no}`} value={row[field]} root={root} onChange={value => updateTerms(index,{[field]:value})} /></div>)}
          <Dimensions accounts={accounts} label={`Покупатель строки ${row.line_no}`} codes={[row.buyer_account]} values={row.buyer_dimensions} onChange={value => updateTerms(index,{buyer_dimensions:value})} required={['counterparty','contract','settlement_document']} />
          <Dimensions accounts={accounts} label={`Выручка строки ${row.line_no}`} codes={[row.revenue_account]} values={row.revenue_dimensions} onChange={value => updateTerms(index,{revenue_dimensions:value})} />
          <Dimensions accounts={accounts} label={`НДС строки ${row.line_no}`} codes={[row.vat_revenue_account,row.vat_payable_account]} values={row.vat_dimensions} onChange={value => updateTerms(index,{vat_dimensions:value})} />
        </fieldset>)}
        <Button disabled={!policyId || !allocations.length} onClick={() => void calculate()}>Рассчитать проводки отгрузки</Button>
      </fieldset>
    </>}
    {busy && <p role="status">Рассчитывается весь акт…</p>}
    {current && <section aria-label="Расчёт отгрузки" className="space-y-3"><p>Расчёт пакета. Нормативная и налоговая проверка не подтверждена.</p><p>Без НДС: {current.net_byn} BYN · НДС: {current.vat_byn} BYN · Всего: {current.gross_byn} BYN</p>
      {current.mapping.map((row,index) => <p key={index}>Партия {row.lot} · {row.quantity} · Себестоимость {row.cost_byn} BYN</p>)}
      <label>Страница проводок<Select aria-label="Страница проводок" value={page} onChange={event => setPage(Number(event.target.value))}>{current.postings.map((_,index) => <option key={index} value={index}>{index + 1} из {current.postings.length}</option>)}</Select></label>
      <div className="overflow-x-auto"><table className="w-full text-left text-sm"><thead><tr><th>Сторона</th><th>Счёт</th><th>BYN</th><th>Количество</th><th>Аналитика</th></tr></thead><tbody>{current.postings[page]?.posting.lines.map((line,index) => <tr key={index}><td>{line.side === 'debit' ? 'Дт' : 'Кт'}</td><td>{line.account}</td><td>{line.amount}</td><td>{line.quantity ?? '—'}</td><td>{Object.entries(line.dimensions).map(([field,value]) => `${names[field] ?? field}: ${value}`).join('; ')}</td></tr>)}</tbody></table></div>
    </section>}
    {confirmation && (postingLocked || (current && !disabled && confirmation.scope === scope)) && <div>
      {confirmation.scope !== scope && <p role="alert">Подтверждение относится к предыдущему выбору: юрлицо {confirmation.org}, отгрузка {confirmation.sourceKey}. Завершите проверку ответа.</p>}
      <AccountingShipmentConfirm key={`${confirmation.org}/${confirmation.sourceKey}/${confirmation.body}`} {...confirmation} onLock={setPostingLocked} onPosted={onPosted} />
    </div>}
  </section>;
}
