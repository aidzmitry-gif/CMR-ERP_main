"use client";

import { Check, FileCheck2, RefreshCw, Truck } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { OfficeShippingInvoice } from "@/components/erp/office-shipping-invoice";
import { OfficeWarehouseProgress } from "@/components/erp/office-warehouse-progress";
import {
  clearPending, confirmAssociation, decimalInput, fetchOfficeCarriers, fetchShippingContext,
  OfficeShippingError, pendingMatches, prepareShipping, readPending, resolveIntake, savePending, validIntent,
  type CarrierChoice, type ConfirmCommand, type OfficeDocument, type PendingCommand,
  type ShippingContext, type ShippingIntent,
} from "@/lib/office-shipping-api";

const input = "mt-1 w-full min-w-0 rounded-lg border border-line bg-surface px-3 py-2 text-sm text-ink outline-none focus:border-accent disabled:bg-sunken";
const button = "inline-flex items-center justify-center gap-2 rounded-lg bg-accent px-4 py-2.5 text-sm font-semibold text-white disabled:cursor-not-allowed disabled:opacity-50";
const stateLabels: Record<ShippingContext["logistics"]["state"], string> = {
  not_prepared: "Заявка не подготовлена", not_received: "Ожидание приёма логистикой", pending: "Ожидание обработки",
  withdrawn: "Заявка отозвана", resolved: "Исполнение создано", source_changed: "Исходный документ изменён", unavailable: "Сервис логистики недоступен",
};
const shipmentLabels: Record<string, string> = { planned: "Запланирована", in_transit: "В пути", delivered: "Доставлена", cancelled: "Отменена" };
const fields: { key: keyof Omit<ShippingIntent, "mode">; label: string; max: number; type?: string; required?: boolean }[] = [
  { key: "customer", label: "Заказчик", max: 255, required: true }, { key: "cargo", label: "Груз", max: 255, required: true },
  { key: "weight_kg", label: "Вес, кг", max: 14, required: true }, { key: "declared_value_byn", label: "Объявленная стоимость, BYN", max: 16, required: true },
  { key: "route_from", label: "Пункт отправления", max: 128, required: true }, { key: "route_to", label: "Пункт назначения", max: 128, required: true },
  { key: "address", label: "Адрес доставки", max: 255, required: true }, { key: "zone_code", label: "Код зоны (если применим)", max: 8 },
  { key: "pickup_date", label: "Желаемая дата забора", max: 10, type: "date", required: true }, { key: "contact", label: "Контакт для забора", max: 255, required: true },
];
function initialIntent(context: ShippingContext): ShippingIntent {
  const s = context.source_snapshot;
  return { mode: "spot", customer: s.company, cargo: s.title, weight_kg: "", declared_value_byn: "", route_from: "", route_to: s.region,
    address: s.address, zone_code: "", carrier_code: "", carrier_name: "", pickup_date: "", contact: "", comment: "" };
}
function IntentSummary({ intent }: { intent: ShippingIntent }) {
  const values = [["Заказчик", intent.customer], ["Груз", intent.cargo], ["Вес", `${intent.weight_kg} кг`], ["Объявленная стоимость", `${intent.declared_value_byn} BYN`],
    ["Маршрут", `${intent.route_from || "Не указан"} → ${intent.route_to || "Не указан"}`], ["Адрес", intent.address], ["Дата забора", intent.pickup_date],
    ["Контакт", intent.contact], ["Режим", intent.mode === "spot" ? "Разовая доставка" : "Подбор по запросу предложений"], ["Перевозчик в заявке", intent.carrier_name],
    ["Код перевозчика", intent.carrier_code], ["Код зоны", intent.zone_code], ["Комментарий", intent.comment]];
  return <dl className="grid min-w-0 gap-x-6 gap-y-3 text-sm sm:grid-cols-2">{values.map(([label, value]) => <div key={label} className="min-w-0"><dt className="text-xs text-muted">{label}</dt><dd className="mt-0.5 whitespace-pre-wrap break-words text-ink">{value || "Не указано"}</dd></div>)}</dl>;
}
function PreparationForm({ context, disabled, submit }: { context: ShippingContext; disabled: boolean; submit: (intent: ShippingIntent) => void }) {
  const [intent, setIntent] = useState(() => initialIntent(context));
  const [carriers, setCarriers] = useState<CarrierChoice[]>([]);
  const [catalogError, setCatalogError] = useState("");
  const [error, setError] = useState("");
  const [reviewed, setReviewed] = useState(false);
  useEffect(() => {
    const controller = new AbortController(); let alive = true;
    void fetchOfficeCarriers(controller.signal).then(v => { if (alive) setCarriers(v); }).catch(() => { if (alive && !controller.signal.aborted) setCatalogError("Справочник перевозчиков недоступен. Укажите проверенные код и название вручную."); });
    return () => { alive = false; controller.abort(); };
  }, []);
  function change(key: keyof ShippingIntent, value: string) { setReviewed(false); setIntent(v => ({ ...v, [key]: value })); }
  function send(e: React.FormEvent) {
    e.preventDefault(); setError("");
    const weight = decimalInput(intent.weight_kg), declared = decimalInput(intent.declared_value_byn);
    const value = { ...intent, weight_kg: weight ?? "", declared_value_byn: declared ?? "" };
    if (!reviewed || !validIntent(value) || Number(value.weight_kg) <= 0 || fields.some(f => f.required && !value[f.key].trim())
      || value.mode === "spot" && (!value.carrier_name.trim() || !value.carrier_code.trim())) {
      setError("Заполните обязательные поля, проверьте вес и стоимость (до двух знаков после запятой) и подтвердите условия."); return;
    }
    submit(value);
  }
  return <form onSubmit={send} className="space-y-4">
    <p className="text-sm leading-6 text-muted">Компания, груз и адрес предложены из документа. Проверьте их; вес и объявленную стоимость укажите по подтверждённым данным.</p>
    <fieldset disabled={disabled} className="space-y-4">
      <label className="block text-xs font-medium text-muted">Способ организации<select value={intent.mode} onChange={e => { const mode = e.target.value as ShippingIntent["mode"]; setReviewed(false); setIntent(v => ({ ...v, mode, carrier_code: "", carrier_name: "" })); }} className={input}><option value="spot">Разовая доставка</option><option value="contract">Запрос предложений перевозчиков</option></select></label>
      <div className="grid min-w-0 gap-4 sm:grid-cols-2">{fields.map(f => <label key={f.key} className="min-w-0 text-xs font-medium text-muted">{f.label}{f.required ? " *" : ""}<input required={f.required} type={f.type || "text"} inputMode={f.key === "weight_kg" || f.key === "declared_value_byn" ? "decimal" : undefined} maxLength={f.max} value={intent[f.key]} onChange={e => change(f.key, e.target.value)} className={input} /></label>)}</div>
      {intent.mode === "spot" && <div className="space-y-3 rounded-lg bg-sunken p-4">
        <label className="block text-xs font-medium text-muted">Перевозчик из справочника<select value={carriers.find(c => c.id === intent.carrier_code && c.name === intent.carrier_name)?.id ?? ""} onChange={e => { const carrier = carriers.find(c => c.id === e.target.value); setReviewed(false); setIntent(v => ({ ...v, carrier_code: carrier?.id ?? "", carrier_name: carrier?.name ?? "" })); }} className={input}><option value="">Выберите или укажите вручную</option>{carriers.map(c => <option key={c.id} value={c.id}>{c.name}{c.heavy ? " · тяжёлые грузы" : ""}</option>)}</select></label>
        <p className="text-xs leading-5 text-muted">Справочник содержит названия и коды. Наличие машины, тариф и возможность перевозки нужно согласовать отдельно.</p>
        {catalogError && <p role="status" className="text-xs text-amber-800">{catalogError}</p>}
        <div className="grid gap-3 sm:grid-cols-2"><label className="text-xs text-muted">Код перевозчика *<input required maxLength={32} value={intent.carrier_code} onChange={e => change("carrier_code", e.target.value)} className={input} /></label><label className="text-xs text-muted">Название перевозчика *<input required maxLength={128} value={intent.carrier_name} onChange={e => change("carrier_name", e.target.value)} className={input} /></label></div>
      </div>}
      <label className="block text-xs font-medium text-muted">Комментарий<textarea maxLength={2000} rows={3} value={intent.comment} onChange={e => change("comment", e.target.value)} className={input} /></label>
      <label className="flex items-start gap-2 text-sm text-ink"><input type="checkbox" checked={reviewed} onChange={e => setReviewed(e.target.checked)} className="mt-1 shrink-0" /><span>Я сверил условия. После подготовки заявка сохраняется без изменения её состава.</span></label>
      {error && <p role="alert" className="text-sm text-red-700">{error}</p>}
      <button type="submit" disabled={!reviewed || disabled} className={button}><FileCheck2 size={16} /> Подготовить заявку</button>
    </fieldset>
    <p className="text-xs leading-5 text-muted">Подготовка сохраняет заявку в ERP. Бронирование перевозчика и передача груза подтверждаются отдельно.</p>
  </form>;
}

export function OfficeShippingWorkspace({ document, onReconciled }: { document: OfficeDocument; onReconciled?: () => void }) {
  const [snapshot, setContext] = useState<ShippingContext | null>(null);
  const context = snapshot?.source_snapshot.document_id === document.id ? snapshot : null;
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState("");
  const [operationError, setOperationError] = useState("");
  const [storageError, setStorageError] = useState("");
  const [notice, setNotice] = useState("");
  const [pending, setPending] = useState<PendingCommand | null>(null);
  const [revision, setRevision] = useState(0);
  const [busy, setBusy] = useState(false);
  const lock = useRef(false), alive = useRef(true);
  useEffect(() => { alive.current = true; return () => { alive.current = false; }; }, []);
  useEffect(() => {
    const controller = new AbortController(); let current = true;
    void fetchShippingContext(document.id, controller.signal).then(value => {
      if (!current) return;
      try {
        const saved = readPending(value.principal, document.id);
        if (saved && pendingMatches(saved, value)) { clearPending(saved); setNotice("Результат подтверждён сохранёнными данными сервера."); setOperationError(""); setPending(null); }
        else { setPending(saved); if (!saved) setNotice(""); }
      } catch (e) { setStorageError(e instanceof Error ? e.message : "Не удалось прочитать сохранённую команду."); }
      setContext(value); setLoading(false);
    }).catch(e => { if (current && !controller.signal.aborted) { setLoadError(e instanceof Error ? e.message : "Не удалось загрузить заявку."); setLoading(false); } });
    return () => { current = false; controller.abort(); };
  }, [document.id, revision]);
  function refresh() {
    setLoading(true); setContext(null); setPending(null); setLoadError(""); setStorageError("");
    setRevision(v => v + 1);
  }
  async function execute(command: PendingCommand, retry = false) {
    if (lock.current || !context || storageError || command.principal !== context.principal) return;
    lock.current = true; setBusy(true); setOperationError(""); setNotice("");
    try {
      if (!retry) { savePending(command); setPending(command); }
      else if (JSON.stringify(readPending(command.principal, document.id)) !== JSON.stringify(command)) throw new OfficeShippingError("Сохранённая команда изменилась. Обновите сведения.");
      if (command.kind === "prepare") await prepareShipping(document.id, command.body);
      else await confirmAssociation(document.id, command.body);
    } catch (e) {
      // A rejected retry says nothing about the original UNKNOWN attempt.
      if (!retry && e instanceof OfficeShippingError && e.status && e.status >= 400 && e.status < 500 && !e.uncertain) {
        try { clearPending(command); if (alive.current) setPending(null); } catch { /* Retain for explicit reconciliation if storage changed. */ }
      }
      if (alive.current) setOperationError(e instanceof Error ? e.message : "Результат команды нужно проверить.");
    } finally { lock.current = false; if (alive.current) { setBusy(false); refresh(); } }
  }
  function prepare(intent: ShippingIntent) {
    if (!context || pending || !context.capabilities.can_request || context.request || context.document_stage !== "ready") return;
    void execute({ version: 1, kind: "prepare", principal: context.principal, document_id: document.id,
      body: { request_key: crypto.randomUUID(), expected_source_hash: context.source_sha256, expected_assignment_revision: context.assignment_revision, intent } });
  }
  function confirm(body: ConfirmCommand) {
    if (!context || pending || !context.capabilities.can_associate || context.association) return;
    void execute({ version: 1, kind: "confirm", principal: context.principal, document_id: document.id, body });
  }
  async function processIntake() {
    if (!context || lock.current || pending || storageError) return;
    lock.current = true; setBusy(true); setOperationError("");
    try { await resolveIntake(context); } catch (e) { if (alive.current) setOperationError(e instanceof Error ? e.message : "Результат обработки нужно проверить."); }
    finally { lock.current = false; if (alive.current) { setBusy(false); refresh(); } }
  }
  const retryAllowed = context && pending && context.principal === pending.principal && context.source_sha256 === pending.body.expected_source_hash
    && context.assignment_revision === pending.body.expected_assignment_revision && context.source_matches_request
    && (pending.kind === "prepare" ? context.capabilities.can_request && !context.request && context.document_stage === "ready"
      : context.capabilities.can_associate && !context.association && context.request?.envelope_id === pending.body.envelope_id);
  const otherCommand = context && pending && (pending.kind === "prepare" ? !!context.request : !!context.association) && !pendingMatches(pending, context);
  return <section className="min-w-0 space-y-4" aria-label={`Доставка ${document.number}`}>
    <header className="flex flex-wrap items-start justify-between gap-3 rounded-xl border border-line bg-surface p-5"><div className="min-w-0"><p className="text-xs font-semibold uppercase tracking-wider text-muted">Карточка доставки</p><h2 className="mt-1 break-words text-xl font-bold text-ink">{document.number || `Документ #${document.id}`}</h2><p className="mt-1 break-words text-sm text-muted">{document.company}</p></div><button type="button" onClick={refresh} disabled={busy} className="inline-flex items-center gap-2 rounded-lg border border-line px-3 py-2 text-xs text-ink disabled:opacity-50"><RefreshCw size={14} /> Проверить состояние</button></header>
    {loading && <p role="status" className="rounded-xl border border-line bg-surface p-5 text-sm text-muted">Сверка источника, назначения и сохранённой заявки…</p>}
    {loadError && <p role="alert" className="rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-800">{loadError}</p>}
    {operationError && <p role="alert" className="rounded-xl border border-amber-200 bg-amber-50 p-4 text-sm text-amber-900">{operationError}</p>}
    {notice && <p role="status" className="flex items-start gap-2 rounded-xl border border-emerald-200 bg-emerald-50 p-4 text-sm text-emerald-800"><Check size={17} className="mt-0.5 shrink-0" />{notice}</p>}
    {context && <>
      <ol className="grid grid-cols-3 gap-2 text-xs text-muted" aria-label="Этапы заявки">{[["1", "Подготовка", !!context.request], ["2", "Связь со счётом", !!context.association], ["3", "Исполнение", context.logistics.state === "resolved"]].map(([n, label, done]) => <li key={String(n)} className={`min-w-0 rounded-lg border p-3 ${done ? "border-emerald-200 bg-emerald-50 text-emerald-800" : "border-line bg-surface"}`}><span className="mb-1 block font-bold">{done ? "✓" : n}</span>{label}</li>)}</ol>
      {storageError && <p role="alert" className="rounded-lg bg-red-50 p-4 text-sm text-red-800">{storageError}</p>}
      {pending && <div className="space-y-3 rounded-xl border border-amber-200 bg-amber-50 p-4 text-sm text-amber-900"><p className="font-semibold">Сохранённая команда ожидает сверки</p><p>Новая команда не отправляется, пока результат предыдущей не подтверждён. Проверяйте состояние; повтор использует тот же ключ и состав.</p><p className="break-all text-xs">Ключ: {pending.body.request_key}</p>{retryAllowed && <button type="button" disabled={busy || !!storageError} onClick={() => void execute(pending, true)} className={button}>Повторить тот же запрос</button>}{otherCommand && <button type="button" disabled={busy} onClick={() => { try { clearPending(pending); setPending(null); setOperationError(""); } catch (e) { setStorageError(e instanceof Error ? e.message : "Ошибка сверки."); } }} className="rounded-lg border border-amber-300 px-3 py-2 text-xs">Закрыть ожидание: сервер сохранил другую команду</button>}</div>}
      {!context.source_matches_request && <p role="alert" className="rounded-xl border border-amber-200 bg-amber-50 p-4 text-sm text-amber-900">Документ изменился после подготовки заявки. Сохранённые условия показаны ниже. Новое исполнение заблокировано до сверки с руководителем.</p>}
      <section className="space-y-4 rounded-xl border border-line bg-surface p-5"><h3 className="font-semibold text-ink">1. Условия доставки</h3>
        {context.request ? <><div className="flex flex-wrap gap-x-5 gap-y-1 text-xs text-muted"><span>Заявка сохранена</span><span>Проверяющий: {context.request.actor}</span></div><IntentSummary intent={context.request.payload.intent} /></>
          : context.capabilities.can_request && context.document_stage === "ready" ? <PreparationForm context={context} disabled={busy || !!pending || !!storageError} submit={prepare} />
            : <p className="text-sm leading-6 text-muted">{!context.is_current_reviewer ? "Для подготовки нужен текущий назначенный проверяющий с правом создания заявки. Назначение выполняется на вкладке «Проверяющие»." : context.document_stage !== "ready" ? "Новая заявка доступна на этапе «Готов к подготовке». Сверьте этап документа в его воронке." : "Для подготовки заявки требуется соответствующее право. Обратитесь к руководителю."}</p>}
      </section>
      {context.request && <section className="space-y-4 rounded-xl border border-line bg-surface p-5"><h3 className="font-semibold text-ink">2. Связь с точным счётом</h3>
        {context.association ? <div className="space-y-2 text-sm text-ink"><p className="flex items-center gap-2 font-medium text-emerald-700"><FileCheck2 size={17} /> Связь подтверждена</p><p>Юрлицо #{context.association.exact_invoice.organization_id} · счёт #{context.association.exact_invoice.document_id} · версия {context.association.exact_invoice.expected_version}</p><details className="text-xs text-muted"><summary className="cursor-pointer">Реквизиты сверки</summary><p className="mt-2 break-all">SHA-256: {context.association.exact_invoice.expected_content_sha256}</p><p className="mt-2 break-all">Исполнение: {context.association.execution_id}</p></details>{!context.association.current_review_matches && <p className="rounded-lg bg-amber-50 p-3 text-amber-900">Назначение проверяющего изменилось. История доступна; новое исполнение требует актуальных полномочий и сверки.</p>}</div>
          : context.capabilities.can_associate && context.source_matches_request ? <OfficeShippingInvoice context={context} disabled={busy || !!pending || !!storageError} onConfirm={confirm} />
            : <p className="text-sm leading-6 text-muted">Связь подтверждает назначенный проверяющий с полномочиями главного бухгалтера выбранного юрлица и доступом к сделке. Передайте сохранённую заявку руководителю для назначения уполномоченного сотрудника.</p>}
      </section>}
      <section className="space-y-4 rounded-xl border border-line bg-surface p-5"><div className="flex items-center gap-2"><Truck size={17} className="text-accent-ink" /><h3 className="font-semibold text-ink">3. Исполнение и доставка</h3></div><p className="text-sm font-medium text-ink">{stateLabels[context.logistics.state]}</p>
        {context.logistics.pending_reason && <p className="break-words text-xs text-muted">{context.logistics.pending_reason === "persisted_source_required" ? "Для обработки заявки в логистике нужны подтверждённая связь со счётом и актуальные полномочия." : "Требуется сверка источника заявки в логистике."}</p>}
        {context.logistics.target?.kind === "rfq" && <p className="text-sm text-muted">Запрос предложений {context.logistics.target.number} · {context.logistics.target.status}. {context.logistics.shipment ? "Доставка по выбранному предложению:" : "Доставка появится после выбора предложения и оформления исполнения."}</p>}
        {context.logistics.shipment && <dl className="grid gap-3 text-sm sm:grid-cols-2">{[["Отгрузка", context.logistics.shipment.number], ["Состояние", shipmentLabels[context.logistics.shipment.status] || context.logistics.shipment.status], ["Перевозчик", context.logistics.shipment.carrier_name], ["Трекинг", context.logistics.shipment.tracking_no], ["Статус трекинга", context.logistics.shipment.tracking_status], ["Ожидаемая дата", context.logistics.shipment.eta]].map(([label, value]) => <div key={label} className="min-w-0"><dt className="text-xs text-muted">{label}</dt><dd className="mt-1 break-words text-ink">{value || "Нет подтверждённых данных"}</dd></div>)}</dl>}
        {context.logistics.state === "pending" && context.association?.current_review_matches && context.capabilities.can_associate && context.source_matches_request && <><button type="button" disabled={busy || !!pending || !!storageError} onClick={() => void processIntake()} className={button}>Обработать заявку в логистике</button><p className="text-xs leading-5 text-muted">Операция создаёт или использует внутреннее исполнение. Внешнее бронирование и фактическая передача груза выполняются отдельно.</p></>}
      </section>
      <OfficeWarehouseProgress key={`${context.principal}:${document.id}:${context.association?.association_id ?? "unassociated"}:${context.association?.exact_invoice.expected_content_sha256 ?? ""}`} context={context} disabled={busy || !!pending || !!storageError || !context.source_matches_request} onReconciled={() => { refresh(); onReconciled?.(); }} />
    </>}
  </section>;
}
