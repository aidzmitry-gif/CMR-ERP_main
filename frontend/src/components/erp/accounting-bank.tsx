"use client";

import { useEffect, useLayoutEffect, useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import { Input, Select } from "@/components/ui/input";

type Account = { code: string; title: string; cash: boolean; category: string; required_dimensions: string[] };
type Preview = { lines: { account: string; title: string; side: string; amount: string }[] };
const labels: Record<string, string> = { counterparty: "Контрагент", contract: "Договор", settlement_document: "Документ расчётов", department: "Подразделение", employee: "Сотрудник", warehouse: "Склад", sku: "Номенклатура", lot: "Партия", order: "Заказ", asset: "Основное средство", owner: "Владелец", serial: "Серийный номер" };
export function AccountingBank({ org, accounts, policyId, date, onDate, onPosted }: {
  org: string; accounts: Account[]; policyId?: number; date: string;
  onDate: (date: string) => void; onPosted: () => void;
}) {
  const [form, setForm] = useState({ source: "", source_version: 1, statement_reference: "", document_date: date, operation_date: date, direction: "receipt", bank_account: "", settlement_account: "", amount: "", cash_activity: "", explanation: "", bank_dimensions: {} as Record<string, string>, settlement_dimensions: {} as Record<string, string> });
  const [preview, setPreview] = useState<Preview | null>(null);
  const [prepared, setPrepared] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const mounted = useRef(true);
  const onPostedRef = useRef(onPosted);
  useLayoutEffect(() => { onPostedRef.current = onPosted; }, [onPosted]);
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; }; }, []);
  function change(patch: Partial<typeof form>) { setForm({ ...form, ...patch }); setPreview(null); setPrepared(null); setNotice(""); }
  async function execute(confirm: boolean) {
    if (!policyId) { setError("Сначала утвердите учётную политику на дату отражения."); return; }
    const body = confirm ? prepared : { ...form, posting_date: date, policy_id: policyId };
    if (!body) return;
    setBusy(true); setError("");
    try {
      const response = await fetch(`/api/accounting/organizations/${org}/bank/${confirm ? "confirm" : "preview"}`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
      const data = await response.json();
      if (!mounted.current) return;
      if (!response.ok) throw new Error(typeof data.detail === "string" ? data.detail : "Проверьте обязательные поля банковского документа.");
      if (confirm) { setPreview(null); setPrepared(null); setNotice(`Банковская операция № ${data.id} проведена.`); onPostedRef.current(); }
      else { setPrepared(body); setPreview(data as Preview); }
    } catch (e) { setError((e as Error).message); }
    finally { setBusy(false); }
  }
  return <section className="space-y-4 rounded-xl border border-line bg-surface p-4">
    <h2 className="font-semibold">Банковские расчёты в BYN</h2><p className="text-sm text-muted">Поступление или списание по выписке. Выберите счёт расчётов; оплата сама по себе не признаёт доход или расход. Валютные операции и переводы между денежными счетами требуют отдельных правил.</p>
    {error && <p role="alert" className="text-red-700">{error}</p>}{notice && <p role="status" className="text-money">{notice}</p>}
    <fieldset disabled={busy} className="space-y-4"><div className="grid gap-3 md:grid-cols-3">
      <label>Операция в источнике<Input aria-label="Банковский источник" value={form.source} onChange={(e) => change({ source: e.target.value })} placeholder="Устойчивый идентификатор строки" /></label>
      <label>Выписка и строка<Input aria-label="Банковская выписка" value={form.statement_reference} onChange={(e) => change({ statement_reference: e.target.value })} /></label>
      <label>Направление<Select aria-label="Направление платежа" value={form.direction} onChange={(e) => change({ direction: e.target.value })}><option value="receipt">Поступление</option><option value="payment">Списание</option></Select></label>
      <label>Дата документа<Input type="date" value={form.document_date} onChange={(e) => change({ document_date: e.target.value })} /></label>
      <label>Дата операции по выписке<Input type="date" value={form.operation_date} onChange={(e) => change({ operation_date: e.target.value })} /></label>
      <label>Дата отражения<Input type="date" value={date} onChange={(e) => { setPreview(null); setPrepared(null); onDate(e.target.value); }} /></label>
      <label>Денежный счёт<Select aria-label="Банковский счёт" value={form.bank_account} onChange={(e) => change({ bank_account: e.target.value, bank_dimensions: {} })}><option value="">Выберите счёт</option>{accounts.filter((a) => a.cash).map((a) => <option key={a.code} value={a.code}>{a.code} · {a.title}</option>)}</Select></label>
      <label>Счёт расчётов<Select aria-label="Счёт расчётов" value={form.settlement_account} onChange={(e) => change({ settlement_account: e.target.value, settlement_dimensions: {} })}><option value="">Выберите счёт</option>{accounts.filter((a) => !a.cash && ["asset", "liability"].includes(a.category)).map((a) => <option key={a.code} value={a.code}>{a.code} · {a.title}</option>)}</Select></label>
      <label>Сумма BYN<Input aria-label="Банковская сумма" inputMode="decimal" value={form.amount} onChange={(e) => change({ amount: e.target.value })} /></label>
      <label>Вид денежного потока<Select aria-label="Поток платежа" value={form.cash_activity} onChange={(e) => change({ cash_activity: e.target.value })}><option value="">Выберите вид</option><option value="operating">Текущая деятельность</option><option value="investing">Инвестиционная</option><option value="financing">Финансовая</option></Select></label>
      <label className="md:col-span-2">Назначение<Input aria-label="Назначение платежа" value={form.explanation} onChange={(e) => change({ explanation: e.target.value })} /></label>
    </div>
    {([ ["bank_account", "bank_dimensions"], ["settlement_account", "settlement_dimensions"] ] as const).map(([accountField, dimensionField]) => <div key={accountField} className="grid gap-3 md:grid-cols-3">{accounts.find((a) => a.code === form[accountField])?.required_dimensions.map((key) => <label key={key}>{labels[key] || key}<Input value={form[dimensionField][key] || ""} onChange={(e) => change({ [dimensionField]: { ...form[dimensionField], [key]: e.target.value } })} /></label>)}</div>)}
    <Button disabled={!org || !form.source || !form.statement_reference || !form.bank_account || !form.settlement_account || !form.amount || !form.cash_activity || !form.explanation} onClick={() => void execute(false)}>Рассчитать банковские проводки</Button>
    {preview && <div className="space-y-2 rounded-xl border border-accent p-3">{preview.lines.map((line, i) => <p key={i}>{line.side === "debit" ? "Дт" : "Кт"} {line.account} · {line.title} — {line.amount} BYN</p>)}<Button onClick={() => void execute(true)}>Подтвердить банковскую операцию</Button></div>}
    </fieldset>
  </section>;
}
