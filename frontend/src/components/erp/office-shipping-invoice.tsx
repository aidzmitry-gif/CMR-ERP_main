"use client";

import { useEffect, useRef, useState } from "react";

import { searchAccountingBuyers, type AccountingBuyer } from "@/lib/accounting-buyers";
import { organizations } from "@/lib/expense-control-api";
import {
  associationCommand, previewAssociation, searchShippingInvoices,
  type AssociationPreview, type ConfirmCommand, type InvoiceChoice, type ShippingContext,
} from "@/lib/office-shipping-api";

const input = "mt-1 w-full min-w-0 rounded-lg border border-line bg-surface px-3 py-2 text-sm text-ink outline-none focus:border-accent";
const secondary = "shrink-0 rounded-lg border border-line px-3 py-2 text-sm text-ink disabled:opacity-50";
type Organization = { id: number; name: string; unp: string };

export function OfficeShippingInvoice({ context, disabled, onConfirm }: { context: ShippingContext; disabled: boolean; onConfirm: (body: ConfirmCommand) => void }) {
  const [books, setBooks] = useState<Organization[]>([]);
  const [organization, setOrganization] = useState("");
  const [buyerQuery, setBuyerQuery] = useState("");
  const [buyers, setBuyers] = useState<AccountingBuyer[] | null>(null);
  const [buyer, setBuyer] = useState<AccountingBuyer | null>(null);
  const [invoiceQuery, setInvoiceQuery] = useState("");
  const [invoices, setInvoices] = useState<InvoiceChoice[] | null>(null);
  const [selected, setSelected] = useState<InvoiceChoice | null>(null);
  const [explanation, setExplanation] = useState("");
  const [review, setReview] = useState<{ body: ConfirmCommand; preview: AssociationPreview } | null>(null);
  const [checked, setChecked] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [loadingBooks, setLoadingBooks] = useState(true);
  const generation = useRef(0);
  useEffect(() => {
    let alive = true;
    void organizations().then(v => { if (alive) setBooks(v); }).catch(e => { if (alive) setError(e instanceof Error ? e.message : "Не удалось загрузить юрлица."); }).finally(() => { if (alive) setLoadingBooks(false); });
    return () => { alive = false; generation.current += 1; };
  }, []);
  function invalidate() { generation.current += 1; setReview(null); setChecked(false); setError(""); setBusy(false); }
  function changeOrganization(value: string) { invalidate(); setOrganization(value); setBuyers(null); setBuyer(null); setInvoices(null); setSelected(null); setBuyerQuery(""); setInvoiceQuery(""); }
  async function searchBuyers(e: React.FormEvent) {
    e.preventDefault(); invalidate(); const current = generation.current; setBusy(true); setBuyers(null); setBuyer(null); setInvoices(null); setSelected(null);
    try { const result = await searchAccountingBuyers(organization, buyerQuery); if (generation.current === current) setBuyers(result); }
    catch (e) { if (generation.current === current) setError(e instanceof Error ? e.message : "Не удалось найти покупателей."); }
    finally { if (generation.current === current) setBusy(false); }
  }
  async function searchInvoices(e: React.FormEvent) {
    e.preventDefault(); if (!buyer) return; invalidate(); const current = generation.current; setBusy(true); setInvoices(null); setSelected(null);
    try { const result = await searchShippingInvoices(Number(organization), buyer.id, invoiceQuery); if (generation.current === current) setInvoices(result); }
    catch (e) { if (generation.current === current) setError(e instanceof Error ? e.message : "Не удалось найти счета."); }
    finally { if (generation.current === current) setBusy(false); }
  }
  async function preview() {
    if (!selected || !buyer || disabled || busy) return;
    invalidate(); const current = generation.current; setBusy(true);
    try {
      const body = await associationCommand(context, selected.exact_invoice, explanation);
      const result = await previewAssociation(context.source_snapshot.document_id, body);
      if (generation.current === current) setReview({ body, preview: result });
    } catch (e) { if (generation.current === current) setError(e instanceof Error ? e.message : "Не удалось сверить счёт."); }
    finally { if (generation.current === current) setBusy(false); }
  }
  const book = books.find(v => String(v.id) === organization);
  return <div className="space-y-4">
    <p className="text-sm leading-6 text-muted">Выберите юрлицо, покупателя и действующий счёт. Для подтверждения нужны назначение проверяющего, полномочия главного бухгалтера этой книги и доступ к сделке.</p>
    <fieldset disabled={disabled} className="min-w-0 space-y-4">
      <label className="block text-xs font-medium text-muted">Юридическое лицо<select value={organization} onChange={e => changeOrganization(e.target.value)} disabled={loadingBooks} className={input}><option value="">{loadingBooks ? "Загрузка юрлиц…" : "Выберите юрлицо"}</option>{books.map(v => <option key={v.id} value={v.id}>{v.name} · УНП {v.unp}</option>)}</select></label>
      {!loadingBooks && books.length === 0 && !error && <p className="text-sm text-muted">Нет доступных бухгалтерских книг. Передайте заявку уполномоченному сотруднику.</p>}
      {organization && <form onSubmit={searchBuyers} className="space-y-2"><label className="block text-xs font-medium text-muted">Покупатель по имени или УНП<input required value={buyerQuery} onChange={e => { invalidate(); setBuyerQuery(e.target.value); setBuyers(null); setBuyer(null); setInvoices(null); setSelected(null); }} maxLength={255} className={input} /></label><button type="submit" disabled={busy || !buyerQuery.trim()} className={secondary}>Найти покупателя</button></form>}
      {buyers && <div className="space-y-2">{buyers.length === 0 ? <p className="text-sm text-muted">Покупатели не найдены. Проверьте имя или УНП.</p> : <label className="block text-xs font-medium text-muted">Точный покупатель<select value={buyer?.id ?? ""} onChange={e => { invalidate(); setBuyer(buyers.find(v => v.id === Number(e.target.value)) ?? null); setInvoices(null); setSelected(null); setInvoiceQuery(""); }} className={input}><option value="">Выберите запись справочника</option>{buyers.map(v => <option key={v.id} value={v.id}>{v.name} · УНП {v.unp || "не указан"} · #{v.id}</option>)}</select></label>}</div>}
      {buyer && <form onSubmit={searchInvoices} className="space-y-2"><label className="block text-xs font-medium text-muted">Номер счёта или ID<input required value={invoiceQuery} onChange={e => { invalidate(); setInvoiceQuery(e.target.value); setInvoices(null); setSelected(null); }} maxLength={255} className={input} /></label><button type="submit" disabled={busy || !invoiceQuery.trim()} className={secondary}>Найти счёт</button></form>}
      {invoices && <div className="space-y-2">{invoices.length === 0 ? <p className="text-sm text-muted">Действующие счета этого покупателя не найдены. Проверьте юрлицо, покупателя и номер.</p> : <label className="block text-xs font-medium text-muted">Счёт покупателя<select value={selected?.exact_invoice.document_id ?? ""} onChange={e => { invalidate(); setSelected(invoices.find(v => v.exact_invoice.document_id === Number(e.target.value)) ?? null); }} className={input}><option value="">Выберите точную версию счёта</option>{invoices.map(v => <option key={v.exact_invoice.document_id} value={v.exact_invoice.document_id}>{v.number} · версия {v.exact_invoice.expected_version} · #{v.exact_invoice.document_id}</option>)}</select></label>}</div>}
      {selected && <><label className="block text-xs font-medium text-muted">Основание связи заявки со счётом *<textarea required value={explanation} maxLength={1000} rows={3} onChange={e => { invalidate(); setExplanation(e.target.value); }} placeholder="Укажите документальное основание: какие условия и документы сверены" className={input} /></label><button type="button" onClick={() => void preview()} disabled={busy || !explanation.trim()} className={secondary}>Сверить счёт и условия</button></>}
      {busy && <p role="status" className="text-sm text-muted">Сверка данных…</p>}
      {error && <p role="alert" className="rounded-lg bg-amber-50 p-3 text-sm text-amber-900">{error}</p>}
      {review && selected && buyer && book && <div className="space-y-4 rounded-xl border border-accent/20 bg-accent-soft p-4"><h4 className="font-semibold text-ink">Проверьте перед подтверждением</h4><dl className="space-y-3 text-sm"><div><dt className="text-xs text-muted">Юрлицо</dt><dd className="break-words text-ink">{book.name} · УНП {book.unp}</dd></div><div><dt className="text-xs text-muted">Покупатель</dt><dd className="break-words text-ink">{buyer.name} · УНП {buyer.unp || "не указан"} · #{buyer.id}</dd></div><div><dt className="text-xs text-muted">Счёт</dt><dd className="break-words text-ink">{selected.number} · версия {selected.exact_invoice.expected_version} · #{selected.exact_invoice.document_id}</dd></div><div><dt className="text-xs text-muted">Сделка</dt><dd className="text-ink">#{review.preview.verified_invoice.deal_id}</dd></div><div><dt className="text-xs text-muted">Основание</dt><dd className="whitespace-pre-wrap break-words text-ink">{review.body.evidence_refs.explanation}</dd></div></dl><details className="text-xs text-muted"><summary className="cursor-pointer">Хэш точной версии счёта</summary><p className="mt-2 break-all">{selected.exact_invoice.expected_content_sha256}</p></details><label className="flex items-start gap-2 text-sm text-ink"><input type="checkbox" checked={checked} onChange={e => setChecked(e.target.checked)} className="mt-1 shrink-0" /><span>Счёт, покупатель и сохранённые условия заявки сверены. Подтверждаю эту связь.</span></label><button type="button" disabled={!checked || disabled || busy} onClick={() => onConfirm(review.body)} className="rounded-lg bg-accent px-4 py-2.5 text-sm font-semibold text-white disabled:opacity-50">Подтвердить связь со счётом</button><p className="text-xs leading-5 text-muted">Подтверждение создаёт связь внутри ERP и сохраняет отдельный ключ операции. Внешняя отправка перевозчику не выполняется.</p></div>}
    </fieldset>
  </div>;
}
