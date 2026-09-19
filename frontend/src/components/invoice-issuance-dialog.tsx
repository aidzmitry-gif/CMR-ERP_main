"use client";

import { useEffect, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import { InvoiceDealPreparation } from "./invoice-deal-preparation";
import { fetchRegisterOrganizations, type RegisterOrganization } from "@/lib/document-register-api";
import { allocationError, clearPending, exact, invoiceItems, InvoiceError, issueInvoice, loadPending, prepareCommand, previewInvoice, savePending, units,
  type Allocation, type InvoiceInput, type InvoiceItem, type InvoicePreview, type InvoiceResult, type PendingInvoice } from "@/lib/invoice-issuance-api";

const field = "block w-full rounded border border-line bg-surface p-2 text-ink";
const requisiteLabels: Record<string, string> = {
  address: "Адрес", legal_address: "Юридический адрес", postal_address: "Почтовый адрес",
  bank: "Банк", bank_name: "Банк", account: "Расчётный счёт", bank_account: "Расчётный счёт",
  bik: "БИК", bank_bic: "БИК", iban: "IBAN", unp: "УНП", director: "Руководитель",
  phone: "Телефон", email: "Электронная почта", registry_status: "Статус в реестре",
};
const requisiteLabel = (key: string) => requisiteLabels[key] ?? key.replaceAll("_", " ");
function requisiteText(value: unknown): string {
  if (value == null || value === "") return "Не указано";
  if (Array.isArray(value)) return value.map(requisiteText).join("; ");
  if (typeof value === "object") return Object.entries(value).map(([key, item]) => `${requisiteLabel(key)}: ${requisiteText(item)}`).join("; ");
  if (typeof value === "boolean") return value ? "Да" : "Нет";
  return String(value);
}
type Props = { dealId: string; documentId?: number; initialMode?: "stock" | "on_order"; onClose: (result: InvoiceResult | null) => void };

export function InvoiceIssuanceDialog({ dealId, documentId, initialMode = "stock", onClose }: Props) {
  return <InvoiceDialogForScope key={`${dealId}:${documentId ?? "new"}`} dealId={dealId} documentId={documentId} initialMode={initialMode} onClose={onClose} />;
}

function InvoiceDialogForScope({ dealId, documentId, initialMode = "stock", onClose }: Props) {
  const [organizations, setOrganizations] = useState<RegisterOrganization[]>([]);
  const [items, setItems] = useState<InvoiceItem[]>([]);
  const [org, setOrg] = useState("");
  const [preparedOrg, setPreparedOrg] = useState("");
  const [mode, setMode] = useState<"stock" | "on_order">(initialMode);
  const [currency, setCurrency] = useState("");
  const [documentDate, setDocumentDate] = useState("");
  const [validUntil, setValidUntil] = useState("");
  const [pricing, setPricing] = useState<Record<number, { price: string; rate: string }>>({});
  const [pricingEvidence, setPricingEvidence] = useState("");
  const [evidence, setEvidence] = useState("");
  const [confirmed, setConfirmed] = useState(false);
  const [preview, setPreview] = useState<InvoicePreview | null>(null);
  const [allocations, setAllocations] = useState<Allocation[]>([]);
  const [pending, setPending] = useState<PendingInvoice | null>(null);
  const [completed, setCompleted] = useState<InvoiceResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [loaded, setLoaded] = useState(false);
  const [error, setError] = useState("");
  const [attempt, setAttempt] = useState(0);
  const generation = useRef(0);
  const submitting = useRef(false);
  const capturedInput = useRef<InvoiceInput | null>(null);
  const root = useRef<HTMLDivElement>(null);

  useEffect(() => {
    let active = true;
    Promise.all([fetchRegisterOrganizations(), invoiceItems(dealId)]).then(([orgs, lines]) => {
      if (!active) return;
      const saved = loadPending(dealId);
      if (saved && !orgs.some(o => o.id === saved.command.organization_id)) throw new InvoiceError("Нет доступа к юрлицу сохранённого запроса.", 403);
      setOrganizations(orgs); setItems(lines); setPending(saved); setLoaded(true); setError("");
    }).catch(e => { if (active) { setLoaded(false); setError(e instanceof Error ? e.message : "Ошибка загрузки"); } });
    root.current?.focus();
    return () => { active = false; generation.current += 1; };
  }, [dealId, attempt]);

  function invalidate() {
    generation.current += 1; capturedInput.current = null; setPreview(null); setAllocations([]); setConfirmed(false); setError("");
  }
  function input(): InvoiceInput {
    if (!organizations.some(o => o.id === Number(org))) throw new InvoiceError("Выберите юрлицо.");
    if (preparedOrg !== org) throw new InvoiceError("Подтвердите организацию и покупателя сделки.");
    if (!/^[A-Z]{3}$/.test(currency)) throw new InvoiceError("Укажите код валюты из трёх заглавных букв.");
    const date = (v: string) => /^\d{4}-\d{2}-\d{2}$/.test(v) && !Number.isNaN(Date.parse(v)) && new Date(v).toISOString().slice(0, 10) === v;
    if (!date(documentDate) || !date(validUntil) || validUntil < documentDate) throw new InvoiceError("Укажите даты; срок действия не может быть раньше даты счёта.");
    if (!pricingEvidence.trim()) throw new InvoiceError("Укажите основание цен и ставок.");
    return { reserve_mode: mode, organization_id: Number(org), currency, document_date: documentDate, valid_until: validUntil, pricing_evidence: pricingEvidence.trim(), pricing: items.map(item => {
      const values = pricing[item.id] ?? { price: "", rate: "" };
      const rate = exact(values.rate);
      if (units(rate) > 10000n) throw new InvoiceError("Ставка должна быть от 0 до 100%. Применимость подтвердите отдельно.");
      return { item_id: item.id, unit_price_net: exact(values.price), vat_rate: rate };
    }) };
  }
  async function review() {
    const ticket = ++generation.current;
    setBusy(true); setError(""); setPreview(null); capturedInput.current = null; setConfirmed(false);
    try {
      const values = input();
      const result = await previewInvoice(dealId, values, documentId);
      if (ticket !== generation.current) return;
      capturedInput.current = values; setPreview(result);
      setAllocations(mode === "on_order" ? [] : result.lines.map(line => ({ line_no: line.line_no, warehouse: "", qty: line.qty })));
    } catch (e) { if (ticket === generation.current) setError(e instanceof Error ? e.message : "Ошибка просмотра"); }
    finally { setBusy(false); }
  }
  async function submit() {
    if (submitting.current) return;
    submitting.current = true; setBusy(true); setError("");
    let sent = pending;
    const replayingUnknown = Boolean(pending);
    try {
      if (!sent) {
        if (!preview || !capturedInput.current || !confirmed) throw new InvoiceError("Получите просмотр и явно подтвердите выбранный режим выпуска.");
        sent = prepareCommand(dealId, documentId, capturedInput.current, preview, allocations, evidence);
        savePending(sent); setPending(sent);
      }
      const result = await issueInvoice(sent);
      clearPending(dealId);
      setPending(null); setCompleted(result);
    } catch (e) {
      const failure = e instanceof InvoiceError ? e : new InvoiceError("Результат запроса неизвестен. Повторите исходный запрос.", undefined, true);
      // A definite rejection of a first attempt did not issue anything. A retry
      // after uncertainty retains its original key even if a later attempt fails.
      if (sent && !replayingUnknown && failure.status && failure.status < 500 && !failure.uncertain) {
        clearPending(dealId); setPending(null); invalidate();
      }
      setError(failure.message);
    } finally { submitting.current = false; setBusy(false); }
  }
  function trap(event: React.KeyboardEvent<HTMLDivElement>) {
    event.stopPropagation();
    if (event.key === "Escape") { event.preventDefault(); if (!busy) onClose(completed); }
    if (event.key !== "Tab") return;
    const controls = [...(root.current?.querySelectorAll<HTMLElement>('button:not(:disabled),input:not(:disabled),select:not(:disabled),textarea:not(:disabled),a[href]') ?? [])];
    const first = controls[0], last = controls.at(-1);
    if (!first) { event.preventDefault(); return; }
    if (event.shiftKey && (document.activeElement === first || document.activeElement === root.current)) { event.preventDefault(); last?.focus(); }
    else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
  }
  const allocationProblem = preview ? allocationError(preview, allocations) : null;
  return <div className="fixed inset-0 z-[300] flex items-center justify-center bg-black/50 p-3" onPointerDown={e => e.stopPropagation()} onKeyDown={trap}>
    <div ref={root} tabIndex={-1} role="dialog" aria-modal="true" aria-labelledby="invoice-issuance-title" className="max-h-[94vh] w-full max-w-5xl min-w-0 overflow-y-auto rounded-xl bg-surface p-5 text-ink shadow-xl">
      <div className="flex flex-wrap items-center justify-between gap-3"><h2 id="invoice-issuance-title" className="text-lg font-semibold">Выпуск счёта · сделка #{dealId}{documentId ? ` · черновик #${documentId}` : ""}</h2><button disabled={busy} onClick={() => onClose(completed)} className="rounded border border-line p-2">Закрыть</button></div>
      <p className="my-3 text-sm text-muted">Товарный счёт: согласованные цены и ставки, реквизиты из подтверждённых источников и выбранный режим поставки. Счета только на услуги и замена выпущенного счёта пока недоступны.</p>
      {error && <p role="alert" className="my-3 text-sm text-red-600">{error}</p>}
      {!loaded && <button disabled={busy} onClick={() => setAttempt(n => n + 1)} className="rounded border border-line p-2">Повторить загрузку</button>}
      {completed && <section role="status" className="space-y-3 rounded border border-emerald-600 p-3"><h3 className="font-semibold">Счёт {completed.document.number} выпущен; {completed.document.reserve_mode === "on_order" ? "под заказ — товар не зарезервирован" : "резерв подтверждён"}</h3><p>{completed.replayed ? "Подтверждён результат исходного запроса." : "Оригинал сохранён."}</p><a className="mr-4 underline" href={`/api/sales/documents/${completed.document.id}/render`} target="_blank" rel="noreferrer" onClick={() => onClose(completed)}>Открыть оригинал</a><button onClick={() => onClose(completed)}>Готово</button></section>}
      {loaded && !completed && pending && <section className="space-y-3 rounded border border-amber-500 p-3">
        <h3 className="font-semibold">Сохранён исходный запрос; результат требует подтверждения</h3>
        <p>Юрлицо #{pending.command.organization_id} · {pending.command.currency} · дата {pending.command.document_date} · до {pending.command.valid_until}. {pending.documentId ? `Черновик #${pending.documentId}` : "Первый выпуск"}.</p>
        <p>{pending.command.reserve_mode === "on_order" ? "Под заказ — без резерва" : "Со склада — с резервом"}</p><p className="break-all text-xs">Ключ: {pending.command.request_key}</p>
        <ul className="text-sm">{pending.command.pricing.map(p => <li key={p.item_id}>Позиция #{p.item_id}: нетто {p.unit_price_net} {pending.command.currency}, НДС {p.vat_rate}%</li>)}{pending.command.allocations.map((a, i) => <li key={`allocation-${i}`}>Строка {a.line_no}: {a.warehouse} · {a.qty}</li>)}</ul>
        <p>Основание цен и ставок: {pending.command.pricing_evidence}. Журнал: {pending.command.evidence}.</p>
        <p>Повтор использует тот же endpoint и полный состав запроса. Данные не редактируются и позиции повторно не добавляются. Закрытие окна сохраняет запрос в этой вкладке.</p>
        <button disabled={busy} onClick={() => void submit()} className="rounded bg-accent px-4 py-2 text-white">{busy ? "Проверяем результат…" : "Повторить исходный запрос"}</button>
      </section>}
      {loaded && !completed && !pending && items.length === 0 && <p role="status">В сделке нет товарных строк. Выпуск счёта только на услуги пока не поддерживается.</p>}
      {loaded && !completed && !pending && items.length > 0 && <>
        <label className="block">Юрлицо<select aria-label="Юрлицо" disabled={busy} className={field} value={org} onChange={e => { setOrg(e.target.value); setPreparedOrg(""); invalidate(); }}><option value="">Выберите юрлицо</option>{organizations.map(o => <option key={o.id} value={o.id}>{o.name} · {o.unp} · #{o.id}</option>)}</select></label>
        {org && <InvoiceDealPreparation org={org} dealId={dealId}
          onSelectOrg={value => { setOrg(value); setPreparedOrg(""); invalidate(); }}
          onReady={ready => { setPreparedOrg(ready ? org : ""); if (!ready) invalidate(); }} />}
        <fieldset disabled={busy} className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <label>Режим выпуска<select aria-label="Режим выпуска" className={field} value={mode} onChange={e => { setMode(e.target.value as "stock" | "on_order"); invalidate(); }}><option value="stock">Со склада — с резервом</option><option value="on_order">Под заказ — без резерва</option></select></label>
          <label>Валюта<input aria-label="Валюта" className={field} maxLength={3} placeholder="Код валюты" value={currency} onChange={e => { setCurrency(e.target.value.toUpperCase()); invalidate(); }} /></label>
          <label>Дата счёта<input aria-label="Дата счёта" type="date" className={field} value={documentDate} onChange={e => { setDocumentDate(e.target.value); invalidate(); }} /></label>
          <label>Действителен до<input aria-label="Действителен до" type="date" className={field} value={validUntil} onChange={e => { setValidUntil(e.target.value); invalidate(); }} /></label>
          <div className="min-w-0 overflow-x-auto sm:col-span-2 lg:col-span-4"><table className="w-full text-sm"><thead><tr><th>Товар / строка</th><th>Количество</th><th>Цена нетто</th><th>Ставка НДС %</th></tr></thead><tbody>{items.map(item => <tr key={item.id}>
            <td>{item.name} · {item.sku_code} · #{item.id}</td><td>{item.qty}</td>
            <td><input aria-label={`Цена строки ${item.id}`} inputMode="decimal" className={field} value={pricing[item.id]?.price ?? ""} onChange={e => { setPricing(p => ({ ...p, [item.id]: { price: e.target.value, rate: p[item.id]?.rate ?? "" } })); invalidate(); }} /></td>
            <td><input aria-label={`Ставка строки ${item.id}`} inputMode="decimal" className={field} value={pricing[item.id]?.rate ?? ""} onChange={e => { setPricing(p => ({ ...p, [item.id]: { price: p[item.id]?.price ?? "", rate: e.target.value } })); invalidate(); }} /></td>
          </tr>)}</tbody></table></div>
          <label className="sm:col-span-2 lg:col-span-4">Основание цен и ставок<textarea aria-label="Основание цен и ставок" maxLength={1000} className={field} value={pricingEvidence} onChange={e => { setPricingEvidence(e.target.value); invalidate(); }} /></label>
          <button disabled={!org || preparedOrg !== org} onClick={() => void review()} className="rounded border border-line p-2">{busy ? "Загрузка…" : "Получить предпросмотр"}</button>
        </fieldset>
        {preview && <section className="mt-4 space-y-3 border-t border-line pt-4">
          <h3 className="font-semibold">Проверьте реквизиты и суммы</h3>
          <p>Продавец: {preview.seller.name} · УНП {preview.seller.unp} · {preview.seller.address}. Банк {preview.seller.bank} · БИК {preview.seller.bik} · счёт {preview.seller.account}. Профиль #{preview.seller_profile.profile_id}, версия {preview.seller_profile.revision}.</p>
          <p>Покупатель: {preview.buyer.name} · УНП {preview.buyer.unp} · #{preview.buyer.counterparty_id}, версия {preview.buyer.revision}.</p>
          <dl className="grid gap-1 text-sm" aria-label="Реквизиты покупателя">{Object.entries(preview.buyer.requisites).map(([key, value]) => <div key={key} className="grid gap-1 sm:grid-cols-[12rem_1fr]"><dt className="text-muted">{requisiteLabel(key)}</dt><dd className="min-w-0 break-words">{requisiteText(value)}</dd></div>)}</dl>
          <div className="overflow-x-auto"><table className="w-full text-sm"><thead><tr><th>Строка</th><th>Нетто</th><th>НДС</th><th>Всего</th></tr></thead><tbody>{preview.lines.map(line => <tr key={line.line_no}><td>{line.line_no} · {line.name}</td><td>{line.net}</td><td>{line.tax} ({line.vat_rate}%)</td><td>{line.total} {line.currency}</td></tr>)}</tbody></table></div>
          <p className="font-semibold">Всего: {preview.amount} {preview.currency}</p>
          {mode === "on_order" ? <fieldset disabled={busy} className="space-y-3"><p>Под заказ — товар не зарезервирован. Отгрузка потребует отдельного подтверждённого резерва.</p><label className="block"><input type="checkbox" checked={confirmed} onChange={e => setConfirmed(e.target.checked)} /> Подтверждаю выпуск без резерва и проверенные данные счёта</label><button disabled={!confirmed || busy} onClick={() => void submit()} className="rounded bg-accent px-4 py-2 text-white disabled:opacity-50">Выпустить счёт под заказ</button></fieldset> : <>
          <p className="text-sm">Доступность наблюдалась по физическому журналу WMS. Это не обещание наличия: сервер повторно проверит остаток при выпуске. Неизвестный остаток не считается нулём.</p>
          <fieldset disabled={busy} className="space-y-2">{allocations.map((a, i) => {
            const line = preview.lines.find(l => l.line_no === a.line_no)!;
            const options = preview.availability!.rows.filter(r => r.sku_code === line.sku_code);
            return <div key={i} className="flex flex-wrap items-end gap-2"><span>Строка {a.line_no} · {line.sku_code}</span>
              <label className="min-w-0 flex-1">Склад<select aria-label={`Склад распределения ${i + 1}`} className={field} value={a.warehouse} onChange={e => { setAllocations(rows => rows.map((r, n) => n === i ? { ...r, warehouse: e.target.value } : r)); setConfirmed(false); }}><option value="">Выберите склад</option>{options.map(r => <option key={r.warehouse} value={r.warehouse} disabled={r.free === null || r.physical === null}>{r.warehouse} · свободно {r.free ?? "неизвестно"} · физически {r.physical ?? "неизвестно"} · резерв {r.reserved}</option>)}</select></label>
              <label>Количество<input aria-label={`Количество распределения ${i + 1}`} inputMode="decimal" className={field} value={a.qty} onChange={e => { setAllocations(rows => rows.map((r, n) => n === i ? { ...r, qty: e.target.value } : r)); setConfirmed(false); }} /></label>
              <button className="rounded border border-line p-2" onClick={() => { setAllocations(rows => [...rows, { line_no: a.line_no, warehouse: "", qty: "" }]); setConfirmed(false); }}>Разделить строку {a.line_no}</button>
              <button className="rounded border border-line p-2" onClick={() => { setAllocations(rows => rows.filter((_, n) => n !== i)); setConfirmed(false); }}>Убрать распределение {i + 1}</button>
            </div>;
          })}
            {preview.lines.filter(l => !allocations.some(a => a.line_no === l.line_no)).map(line => <button key={line.line_no} onClick={() => setAllocations(rows => [...rows, { line_no: line.line_no, warehouse: "", qty: line.qty }])}>Добавить распределение строки {line.line_no}</button>)}
            <label className="block">Основание полноты физического журнала<textarea aria-label="Основание полноты физического журнала" className={field} maxLength={1000} value={evidence} onChange={e => { setEvidence(e.target.value); setConfirmed(false); }} /></label>
            <label className="block"><input type="checkbox" checked={confirmed} onChange={e => setConfirmed(e.target.checked)} /> Подтверждаю полноту физического журнала для выбранных складов и проверенные данные счёта</label>
            {allocationProblem && <p role="status" className="text-amber-700">{allocationProblem}</p>}
            <button disabled={busy || !confirmed || Boolean(allocationProblem) || !evidence.trim()} onClick={() => void submit()} className="rounded bg-accent px-4 py-2 text-white disabled:opacity-50">Выпустить счёт и зарезервировать</button>
          </fieldset></>}
        </section>}
      </>}
    </div>
  </div>;
}

let active: { key: string; promise: Promise<InvoiceResult | null> } | null = null;
export function openInvoiceIssuance(dealId: string, documentId?: number, initialMode: "stock" | "on_order" = "stock"): Promise<InvoiceResult | null> {
  const key = `${dealId}:${documentId ?? "new"}:${initialMode}`;
  if (active) return active.key === key ? active.promise : Promise.reject(new InvoiceError("Завершите открытый диалог выпуска другой сделки."));
  const host = document.createElement("div"); document.body.appendChild(host);
  const root = createRoot(host), priorFocus = document.activeElement, overflow = document.body.style.overflow;
  document.body.style.overflow = "hidden";
  const promise = new Promise<InvoiceResult | null>(resolve => {
    root.render(<InvoiceIssuanceDialog dealId={dealId} documentId={documentId} initialMode={initialMode} onClose={result => {
      queueMicrotask(() => { root.unmount(); host.remove(); document.body.style.overflow = overflow; if (priorFocus instanceof HTMLElement) priorFocus.focus(); active = null; resolve(result); });
    }} />);
  });
  active = { key, promise }; return promise;
}
