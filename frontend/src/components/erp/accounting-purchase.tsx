"use client";

import { useEffect, useLayoutEffect, useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import { Input, Select } from "@/components/ui/input";

type Account = { code: string; title: string; category: string; cash: boolean; quantity_tracking: boolean };
type Preview = { lines: { account: string; title: string; side: string; amount: string }[] };
const blankItem = () => ({ account: "", sku: "", lot: "", quantity: "", net_amount: "", vat_rate: "", vat_amount: "", vat_basis: "" });
export function AccountingPurchase({ org, accounts, policyId, date, onDate, onPosted }: {
  org: string; accounts: Account[]; policyId?: number; date: string; onDate: (date: string) => void; onPosted: () => void;
}) {
  const [form, setForm] = useState({ source: "", source_version: "1", invoice_reference: "", counterparty: "", contract: "", warehouse: "", settlement_account: "", vat_account: "", explanation: "", document_date: date, operation_date: date });
  const [items, setItems] = useState([blankItem()]);
  const [preview, setPreview] = useState<{ context: string; body: string; result: Preview } | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const mounted = useRef(true), generation = useRef(0), onPostedRef = useRef(onPosted);
  const context = `${org}/${date}/${policyId}`;
  useLayoutEffect(() => { generation.current += 1; }, [context]);
  useLayoutEffect(() => { onPostedRef.current = onPosted; }, [onPosted]);
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; generation.current += 1; }; }, []);
  function invalidate() { generation.current += 1; setPreview(null); setNotice(""); }
  function change(patch: Partial<typeof form>) { invalidate(); setForm({ ...form, ...patch }); }
  function changeItem(index: number, patch: Partial<ReturnType<typeof blankItem>>) { invalidate(); setItems(items.map((item, i) => i === index ? { ...item, ...patch } : item)); }
  async function execute(confirm: boolean) {
    if (!policyId) { setError("Сначала утвердите учётную политику на дату отражения."); return; }
    if (confirm && (!preview || preview.context !== context)) return;
    const body = confirm ? preview!.body : JSON.stringify({ ...form, source_version: Number(form.source_version), vat_account: form.vat_account === "none" ? null : form.vat_account, posting_date: date, policy_id: policyId, items });
    const token = generation.current;
    setBusy(true); setError("");
    try {
      const response = await fetch(`/api/accounting/organizations/${org}/purchases/${confirm ? "confirm" : "preview"}`, { method: "POST", headers: { "Content-Type": "application/json" }, body });
      const data = await response.json();
      if (!mounted.current) return;
      if (token !== generation.current) {
        // A successful write still invalidates the current book's list even if
        // its date filter changed while the transaction was committing.
        if (confirm && response.ok) onPostedRef.current();
        return;
      }
      if (!response.ok) throw new Error(typeof data.detail === "string" ? data.detail : "Проверьте реквизиты, количество и суммы НДС по позициям.");
      if (confirm) { setPreview(null); setNotice(`Поступление № ${data.id} проведено.`); onPostedRef.current(); }
      else setPreview({ context, body, result: data });
    } catch (e) { if (mounted.current && token === generation.current) setError((e as Error).message); }
    finally { if (mounted.current) setBusy(false); }
  }
  const accountOptions = (roots: string[]) => accounts.filter((a) => roots.includes(a.code.split(".")[0]) && !a.cash).map((a) => <option key={a.code} value={a.code}>{a.code} · {a.title}</option>);
  return <section className="space-y-4 rounded-xl border border-line bg-surface p-4">
    <h2 className="font-semibold">Поступление товаров и материалов в BYN</h2>
    <p className="text-sm text-muted">Собственные запасы по накладной. Укажите идентификаторы поставщика, договора, склада, номенклатуры и партии. Входной НДС отражается отдельно; право на вычет проверяется отдельно. Движение склада этим документом пока не создаётся.</p>
    {error && <p role="alert" className="text-red-700">{error}</p>}{notice && <p role="status" className="text-money">{notice}</p>}
    <fieldset disabled={busy} className="space-y-4"><div className="grid gap-3 md:grid-cols-3">
      {([["source", "Источник поступления"], ["source_version", "Версия накладной"], ["invoice_reference", "Накладная"], ["counterparty", "Поставщик"], ["contract", "Договор поставки"], ["warehouse", "Склад поступления"]] as const).map(([key, label]) => <label key={key}>{label}<Input value={form[key]} onChange={(e) => change({ [key]: e.target.value })} /></label>)}
      <label>Дата накладной<Input type="date" value={form.document_date} onChange={(e) => change({ document_date: e.target.value })} /></label>
      <label>Дата получения<Input type="date" value={form.operation_date} onChange={(e) => change({ operation_date: e.target.value })} /></label>
      <label>Дата отражения поступления<Input type="date" value={date} onChange={(e) => { invalidate(); onDate(e.target.value); }} /></label>
      <label>Счёт поставщика<Select aria-label="Счёт поставщика" value={form.settlement_account} onChange={(e) => change({ settlement_account: e.target.value })}><option value="">Выберите счёт</option>{accountOptions(["60"])}</Select></label>
      <label>Счёт входного НДС<Select aria-label="Счёт входного НДС" value={form.vat_account} onChange={(e) => change({ vat_account: e.target.value })}><option value="">Выберите вариант</option><option value="none">Без суммы НДС по всей накладной</option>{accountOptions(["18"])}</Select></label>
      <label>Содержание поступления<Input value={form.explanation} onChange={(e) => change({ explanation: e.target.value })} /></label>
    </div>
    {items.map((item, index) => <fieldset key={index} className="rounded-lg border border-line p-3"><legend className="px-2 font-medium">Позиция {index + 1}</legend><div className="grid gap-3 md:grid-cols-4">
      <label>Счёт запасов<Select aria-label={`Счёт запасов ${index + 1}`} value={item.account} onChange={(e) => changeItem(index, { account: e.target.value })}><option value="">Выберите счёт</option>{accounts.filter((a) => ["10", "41"].includes(a.code.split(".")[0]) && a.category === "asset" && !a.cash && a.quantity_tracking).map((a) => <option key={a.code} value={a.code}>{a.code} · {a.title}</option>)}</Select></label>
      {([["sku", "Номенклатура"], ["lot", "Партия"], ["quantity", "Количество"], ["net_amount", "Стоимость без НДС"], ["vat_rate", "Ставка НДС %"], ["vat_amount", "Сумма НДС"], ["vat_basis", "Основание НДС"]] as const).map(([key, label]) => <label key={key}>{label}<Input aria-label={`${label} ${index + 1}`} value={item[key]} onChange={(e) => changeItem(index, { [key]: e.target.value })} /></label>)}
    </div><Button variant="secondary" disabled={items.length === 1} onClick={() => { invalidate(); setItems(items.filter((_, i) => i !== index)); }}>Удалить позицию {index + 1}</Button></fieldset>)}
    <div className="flex flex-wrap gap-2"><Button variant="secondary" disabled={items.length >= 300} onClick={() => { invalidate(); setItems([...items, blankItem()]); }}>Добавить позицию</Button><Button disabled={!org || !form.source || !form.vat_account} onClick={() => void execute(false)}>Рассчитать поступление</Button></div>
    {preview?.context === context && <div className="space-y-2 rounded-lg border border-accent p-3">{preview.result.lines.map((line, i) => <p key={i}>{line.side === "debit" ? "Дт" : "Кт"} {line.account} · {line.title} — {line.amount} BYN</p>)}<Button onClick={() => void execute(true)}>Подтвердить поступление</Button></div>}
    </fieldset>
  </section>;
}
