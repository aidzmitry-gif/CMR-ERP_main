"use client";
import { useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { Input, Select } from "@/components/ui/input";

const dimensionNames: Record<string, string> = { counterparty: "Контрагент", contract: "Договор", settlement_document: "Документ расчётов", department: "Подразделение", employee: "Сотрудник", asset: "Основное средство", warehouse: "Склад", sku: "Номенклатура", lot: "Партия", order: "Заказ" };

type Account = { code: string; title: string; category: string; cash: boolean; quantity_tracking: boolean; required_dimensions: string[] };
type Evidence = { entry_id: number | null; line_id: number | null; receipt_id?: number; source: string; source_version: number; amount_byn: string; quantity: string; zero_value_disposal?: boolean };
type SourceLayer = { entry_id: number; line_id: number; quantity: string };
type Cost = { issue_quantity?: string; method?: string; basis_digest: string; book_quantity: string; book_value_byn: string; remaining_quantity: string; remaining_value_byn: string; issue_cost_byn?: string; inventory_layers?: { lot: string; quantity: string; amount_byn: string; dimensions: Record<string, string> }[]; evidence: Evidence[] };
type Calculation = { kind?: "monetary"; net_amount_byn?: string; vat_amount_byn?: string; gross_amount_byn?: string; cost: Cost; digest: string; posting: { lines: { side: string; account: string; amount: string; quantity: string | null; dimensions: Record<string, string> }[] } } | { kind: "quantity_only_receipt"; cost: Cost; digest: string; posting: null; receipt: { source_layer?: SourceLayer; source_layers?: SourceLayer[]; zero_byn: true } };
export function AccountingInventoryIssue({ org, date, policyId, inventoryMethod = "specific", accounts, onBusyChange, onPosted, onDate, onEntry, sale = false }: { org: string; date: string; policyId?: number; inventoryMethod?: "specific" | "fifo" | "weighted_average"; accounts: Account[]; onBusyChange: (busy: boolean) => void; onPosted: () => void; onDate: (value: string) => void; onEntry?: (id: number) => void; sale?: boolean }) {
  const [form, setForm] = useState({ source: "", source_version: 1, document_date: date, operation_date: date, account: "", warehouse: "", sku: "", lot: "", quantity: "", expense_account: "", expense_dimensions: {} as Record<string, string>, explanation: "" });
  const [prepared, setPrepared] = useState<{ key: string; body: Record<string, unknown>; calculation: Calculation } | null>(null);
  const [saleForm, setSaleForm] = useState({ net_amount: "", vat_rate: "", vat_basis: "", buyer_account: "", revenue_account: "", vat_revenue_account: "", vat_payable_account: "", buyer_dimensions: {} as Record<string, string>, revenue_dimensions: {} as Record<string, string>, vat_dimensions: {} as Record<string, string> });
  const [busy, setBusy] = useState(false), [error, setError] = useState(""), [notice, setNotice] = useState("");
  const mounted = useRef(true);
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; }; }, []);
  const key = `${org}/${date}/${policyId}/${sale}`;
  const current = prepared?.key === key ? prepared : null;
  const quantitySources = current?.calculation.kind === "quantity_only_receipt" ? current.calculation.receipt.source_layers ?? (current.calculation.receipt.source_layer ? [current.calculation.receipt.source_layer] : []) : [];
  function change(patch: Partial<typeof form>) { setForm((previous) => ({ ...previous, ...patch })); setPrepared(null); setError(""); setNotice(""); }
  function changeSale(patch: Partial<typeof saleForm>) { setSaleForm((previous) => ({ ...previous, ...patch })); setPrepared(null); setError(""); setNotice(""); }
  function changeSaleAccount(field: "buyer_account" | "revenue_account" | "vat_revenue_account" | "vat_payable_account", value: string) {
    changeSale(filteredSale({ ...saleForm, [field]: value }));
  }
  function filteredSale(next: typeof saleForm) {
    const required = (code: string) => accounts.find((a) => a.code === code)?.required_dimensions ?? [];
    const keep = (values: Record<string, string>, keys: string[]) => Object.fromEntries(Object.entries(values).filter(([key]) => keys.includes(key)));
    return { ...next,
      buyer_dimensions: keep(next.buyer_dimensions, ["counterparty", "contract", "settlement_document", ...required(next.buyer_account)]),
      revenue_dimensions: keep(next.revenue_dimensions, required(next.revenue_account)),
      vat_dimensions: keep(next.vat_dimensions, [...required(next.vat_revenue_account), ...required(next.vat_payable_account)]),
    };
  }
  async function execute(confirm: boolean) {
    if (busy || !org || !policyId || (confirm && !current)) return;
    const body = confirm ? { ...current!.body, basis_digest: current!.calculation.cost.basis_digest, digest: current!.calculation.digest } : { ...form, expense_dimensions: Object.fromEntries(Object.entries(form.expense_dimensions).filter(([dimension]) => accounts.find((a) => a.code === form.expense_account)?.required_dimensions.includes(dimension))), ...(sale ? { ...filteredSale(saleForm), net_amount: saleForm.net_amount.trim().replace(",", "."), vat_rate: saleForm.vat_rate.trim().replace(",", ".") } : {}), quantity: form.quantity.trim().replace(",", "."), posting_date: date, policy_id: policyId };
    setBusy(true); onBusyChange(true); setError(""); setNotice("");
    if (!confirm) setPrepared(null);
    try {
      const response = await fetch(`/api/accounting/organizations/${org}/${sale ? "sales" : "inventory/issues"}/${confirm ? "confirm" : "posting-preview"}`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
      const result = await response.json();
      if (!mounted.current) return;
      if (!response.ok) throw new Error(typeof result.detail === "string" ? result.detail : "Проверьте поля документа и учётную политику.");
      if (confirm) { setPrepared(null); setNotice(result.kind === "quantity_only_receipt" ? `Запись списания № ${result.receipt_id} зарегистрирована.` : sale ? `Продажа № ${result.id} проведена.` : `Бухгалтерское списание № ${result.id} проведено.`); onPosted(); }
      else setPrepared({ key, body, calculation: result });
    } catch (e) { if (mounted.current) setError(e instanceof Error ? e.message : "Не удалось выполнить запрос."); }
    finally { if (mounted.current) setBusy(false); onBusyChange(false); }
  }
  const belongs = (code: string, root: string) => code === root || code.startsWith(`${root}.`);
  const inventory = accounts.filter((account) => account.category === "asset" && !account.cash && account.quantity_tracking && (sale ? belongs(account.code, "41") || belongs(account.code, "43") : /^(10|41|43)(\.|$)/.test(account.code)));
  const expense = accounts.filter((account) => account.category === "expense" && !account.cash && !account.quantity_tracking && (!sale || belongs(account.code, "90.4")));
  return <section aria-label={sale ? "Бухгалтерская продажа товаров" : "Бухгалтерское списание запасов"} className="space-y-4 rounded-xl border border-line bg-surface p-4">
    <h2 className="font-semibold">{sale ? "Продажа товаров: выручка, НДС и себестоимость" : "Бухгалтерское списание партии"}</h2>
    <p>{sale ? `Бухгалтерский документ продажи в BYN по методу ${inventoryMethod === "specific" ? "индивидуальной оценки" : inventoryMethod === "fifo" ? "ФИФО" : "средневзвешенной стоимости"}. Основание и ставку НДС указывает бухгалтер. Физическая отгрузка оформляется отдельно.` : `Расчёт себестоимости в BYN по методу ${inventoryMethod === "specific" ? "индивидуальной оценки" : inventoryMethod === "fifo" ? "ФИФО" : "средневзвешенной стоимости"}. Для ФИФО и средней стоимости партия может быть пустой: расчёт использует явные слои выбранного склада и SKU. Физическое движение склада оформляется отдельно.`}</p>
    {!policyId && <p role="alert">Нет действующей учётной политики на дату отражения.</p>}
    <fieldset disabled={busy || !org} className="grid gap-3 md:grid-cols-2">
      {([['source', 'Идентификатор основания'], ['warehouse', 'Склад партии'], ['sku', 'Номенклатура партии'], ['lot', inventoryMethod === "specific" ? 'Партия' : 'Партия (необязательно)'], ['quantity', 'Количество списания'], ['explanation', 'Содержание списания']] as const).map(([field, label]) => <label key={field}>{sale && field === "explanation" ? "Содержание продажи" : label}<Input value={form[field]} onChange={(e) => change({ [field]: e.target.value })} /></label>)}
      <label>Версия основания<Input type="number" min="1" step="1" value={form.source_version} onChange={(e) => change({ source_version: Number(e.target.value) })} /></label>
      <label>{sale ? "Дата отражения продажи" : "Дата отражения списания"}<Input type="date" value={date} onChange={(e) => { setPrepared(null); onDate(e.target.value); }} /></label>
      <label>{sale ? "Дата документа продажи" : "Дата документа списания"}<Input type="date" value={form.document_date} onChange={(e) => change({ document_date: e.target.value })} /></label>
      <label>Дата хозяйственной операции<Input type="date" value={form.operation_date} onChange={(e) => change({ operation_date: e.target.value })} /></label>
      <label>Счёт запасов<Select aria-label="Счёт запасов" value={form.account} onChange={(e) => change({ account: e.target.value })}><option value="">Выберите счёт</option>{inventory.map((a) => <option key={a.code} value={a.code}>{a.code} · {a.title}</option>)}</Select></label>
      <label>Счёт расходов<Select aria-label="Счёт расходов" value={form.expense_account} onChange={(e) => change({ expense_account: e.target.value, expense_dimensions: {} })}><option value="">Выберите счёт</option>{expense.map((a) => <option key={a.code} value={a.code}>{a.code} · {a.title}</option>)}</Select></label>
      {accounts.find((a) => a.code === form.expense_account)?.required_dimensions.map((dimension) => <label key={dimension}>Аналитика расходов: {dimensionNames[dimension] ?? dimension}<Input value={form.expense_dimensions[dimension] ?? ""} onChange={(e) => change({ expense_dimensions: { ...form.expense_dimensions, [dimension]: e.target.value } })} /></label>)}
      {sale && <>
        {([["net_amount", "Стоимость продажи без НДС, BYN"], ["vat_rate", "Ставка НДС, %"], ["vat_basis", "Основание применения НДС"]] as const).map(([field, label]) => <label key={field}>{label}<Input value={saleForm[field]} onChange={(e) => changeSale({ [field]: e.target.value })} /></label>)}
        {([["buyer_account", "Счёт покупателя", "62", "asset"], ["revenue_account", "Счёт выручки", "90.1", "income"], ["vat_revenue_account", "Счёт НДС из выручки", "90.2", "income"], ["vat_payable_account", "Счёт расчётов по НДС", "68", "liability"]] as const).map(([field, label, root, category]) => <label key={field}>{label}<Select aria-label={label} value={saleForm[field]} onChange={(e) => changeSaleAccount(field, e.target.value)}><option value="">Выберите счёт</option>{accounts.filter((a) => belongs(a.code, root) && a.category === category && !a.cash && !a.quantity_tracking).map((a) => <option key={a.code} value={a.code}>{a.code} · {a.title}</option>)}</Select></label>)}
        {([["buyer_dimensions", "Покупатель", ["counterparty", "contract", "settlement_document", ...(accounts.find((a) => a.code === saleForm.buyer_account)?.required_dimensions ?? [])]], ["revenue_dimensions", "Выручка", accounts.find((a) => a.code === saleForm.revenue_account)?.required_dimensions ?? []], ["vat_dimensions", "НДС", [...(accounts.find((a) => a.code === saleForm.vat_revenue_account)?.required_dimensions ?? []), ...(accounts.find((a) => a.code === saleForm.vat_payable_account)?.required_dimensions ?? [])]]] as const).map(([field, label, dimensions]) => [...new Set(dimensions)].filter((d) => d !== "vat_rate" && d !== "vat_basis").map((dimension) => <label key={`${field}/${dimension}`}>{label}: {dimensionNames[dimension] ?? dimension}<Input value={saleForm[field][dimension] ?? ""} onChange={(e) => changeSale({ [field]: { ...saleForm[field], [dimension]: e.target.value } })} /></label>))}
      </>}
    </fieldset>
    <p>Дата отражения: {date}.</p>
    <Button disabled={busy || !org || !policyId} onClick={() => void execute(false)}>{sale ? "Рассчитать продажу" : "Рассчитать списание"}</Button>
    {busy && <p role="status">{sale ? "Обработка продажи…" : "Обработка списания…"}</p>}{error && <p role="alert">{error}</p>}{notice && <p role="status">{notice}</p>}
    {current && <div className="space-y-2 rounded border border-accent p-3">
      {sale && current.calculation.kind !== "quantity_only_receipt" && <p>Без НДС: {current.calculation.net_amount_byn} BYN · НДС: {current.calculation.vat_amount_byn} BYN · К оплате: {current.calculation.gross_amount_byn} BYN</p>}
      <p>Метод: {current.calculation.cost.method === "fifo" ? "ФИФО" : current.calculation.cost.method === "weighted_average" ? "Средняя стоимость" : "Индивидуальная оценка"}. Остаток до списания: {current.calculation.cost.book_quantity} · {current.calculation.cost.book_value_byn} BYN</p>
      {current.calculation.kind === "quantity_only_receipt" ? <><p role="status">Себестоимость 0.00 BYN: проводка не создаётся. Количество {current.calculation.cost.issue_quantity ?? String(current.body.quantity)} отражается квитанцией.</p><ul aria-label="Источники списания" className="space-y-1 break-words">{quantitySources.map(layer => <li key={`${layer.entry_id}:${layer.line_id}`}>Источник количества: операция № {layer.entry_id}, строка № {layer.line_id} · Количество {layer.quantity}.</li>)}</ul></> : current.calculation.posting.lines.map((line, index) => <p key={index}>{line.side === "debit" ? "Дт" : "Кт"} {line.account} · {line.amount} BYN{line.quantity ? ` · Количество ${line.quantity}` : ""} · {JSON.stringify(line.dimensions)}</p>)}
      {current.calculation.cost.inventory_layers?.length ? <details open><summary>Слои списания запасов</summary>{current.calculation.cost.inventory_layers.map((layer, index) => <p key={`${layer.lot}:${index}`} className="break-words">Партия {layer.lot || "—"} · Количество {layer.quantity} · Себестоимость {layer.amount_byn} BYN · {Object.entries(layer.dimensions).map(([key, value]) => `${dimensionNames[key] ?? key}: ${value}`).join(" · ")}</p>)}</details> : null}
      <p>Остаток после: {current.calculation.cost.remaining_quantity} · {current.calculation.cost.remaining_value_byn} BYN</p>
      <p>Оснований расчёта: {current.calculation.cost.evidence.length}. Итоговая себестоимость требует проверки полноты затрат.</p>
      <details><summary>Основания расчёта</summary>{current.calculation.cost.evidence.map((row, index) => <p key={row.zero_value_disposal ? `receipt:${row.receipt_id}` : `entry:${row.line_id ?? index}`} className="break-words">{row.zero_value_disposal ? <>Запись списания № {row.receipt_id} · {row.source}</> : <button type="button" className="text-accent underline" disabled={busy || !onEntry} onClick={() => row.entry_id != null && onEntry?.(row.entry_id)}>Операция № {row.entry_id} · {row.source}</button>} · версия {row.source_version} · {row.amount_byn} BYN · количество {row.quantity}</p>)}</details>
      <Button disabled={busy} onClick={() => void execute(true)}>{sale ? "Подтвердить продажу" : "Подтвердить списание"}</Button>
    </div>}
  </section>;
}
