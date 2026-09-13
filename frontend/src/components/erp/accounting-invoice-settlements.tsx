"use client";

import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";

import { AccountingInvoiceMoneyReconciliation } from "./accounting-invoice-money-reconciliation";

import { Button } from "@/components/ui/button";
import { Input, Select } from "@/components/ui/input";

type Settlement = {
  id: number; direction: "receipt" | "refund"; amount: string;
  bank_entry_id: number; refund_of: number | null; evidence: string;
  snapshot: {
    bank: { entry_id: number; digest: string; amount: string; direction: string; operation_date: string; statement_reference: string; settlement_dimensions: Record<string, string>; currency: string };
    invoice: { version: number; content_sha256: string; number: string; amount: string; currency: string };
  };
};
type Register = { received: string; refunded: string; net_received: string; cancellation_authorized: boolean; reconciliation_required: boolean; items: Settlement[] };
type Allocation = { source_key: string; bank_entry_id: number; amount: string; refund_of: number | null; evidence: string };
type Invoice = { id: number; number: string; version: number; deal_id: number; amount: string; status: string; currency: string | null; counterparty: string | null; issued_at: string | null; valid_until: string | null; superseded_by_id: number | null; available_for_settlement: boolean; unavailable_reason: string | null };

function positiveId(value: string) { return /^[1-9]\d*$/.test(value) && Number.isSafeInteger(Number(value)); }
function exactAmount(value: string) { return /^(0|[1-9]\d{0,17})(\.\d{1,2})?$/.test(value) && /[1-9]/.test(value); }

async function request<T>(path: string, body?: Allocation): Promise<T> {
  const response = await fetch(path, { method: body ? "POST" : "GET", cache: "no-store", headers: body ? { "Content-Type": "application/json" } : undefined, body: body ? JSON.stringify(body) : undefined });
  const data: unknown = await response.json().catch(() => null);
  if (!response.ok) {
    const messages: Record<number, string> = { 403: "Недостаточно прав. Подтверждение выполняет главный бухгалтер.", 404: "Счёт или банковская проводка не найдены в выбранном юрлице.", 409: "Требуется сверка: конфликт распределения или исправленная банковская проводка.", 422: "Проверьте сумму, идентификаторы и основание." };
    const detail = data && typeof data === "object" && "detail" in data ? data.detail : null;
    throw Object.assign(new Error(`${response.status}: ${messages[response.status] || "Не удалось получить подтверждение сервера."}${typeof detail === "string" ? ` ${detail}` : ""}`), { status: response.status });
  }
  if (!data || typeof data !== "object") throw new Error("Сервер вернул некорректный ответ. Обновите регистр.");
  return data as T;
}

/** The parent supplies its selected organization; no default company or invoice inference. */
export function AccountingInvoiceSettlements({ org, onBusyChange }: { org: string; onBusyChange?: (busy: boolean) => void }) {
  return <InvoiceSelection key={org} org={org} onBusyChange={onBusyChange} />;
}

function InvoiceSelection({ org, onBusyChange }: { org: string; onBusyChange?: (busy: boolean) => void }) {
  const [locked, setLocked] = useState(false);
  const lock = useCallback((value: boolean) => { setLocked(value); onBusyChange?.(value); }, [onBusyChange]);
  const [document, setDocument] = useState("");
  const [selected, setSelected] = useState("");
  const [query, setQuery] = useState("");
  const [search, setSearch] = useState<{ query: string; revision: number } | null>(null);
  return <section className="space-y-4 rounded-xl border border-line bg-surface p-4">
    <h2 className="font-semibold">Подтверждённые оплаты и возвраты счетов</h2>
    <p className="text-sm text-muted">Юрлицо: {org || "не выбрано"}. Найдите выпущенный счёт по номеру или откройте его по точному ID.</p>
    <fieldset disabled={locked} className="space-y-3">
    <div className="flex flex-wrap items-end gap-3">
      <label>Точный ID счёта<Input aria-label="ID счёта" inputMode="numeric" value={document} disabled={!positiveId(org)} onChange={(e) => { if (!locked) { setDocument(e.target.value); setSelected(""); } }} /></label>
      <Button disabled={!positiveId(org) || !positiveId(document)} onClick={() => setSelected(document)}>Открыть расчёты счёта</Button>
    </div>
    <div className="flex flex-wrap items-end gap-3">
      <label>Поиск по номеру счёта<Input aria-label="Номер счёта для поиска" maxLength={64} value={query} disabled={!positiveId(org)} onChange={(e) => { setQuery(e.target.value); setSearch(null); }} /></label>
      <Button variant="secondary" disabled={!positiveId(org)} onClick={() => setSearch({ query, revision: (search?.revision || 0) + 1 })}>Найти счета</Button>
    </div>
    {search && <InvoiceSearch key={`${search.query}/${search.revision}`} org={org} query={search.query} onSelect={(id) => { setDocument(String(id)); setSelected(String(id)); }} />}
    </fieldset>
    {selected && <InvoiceRegister key={`${org}/${selected}`} org={org} document={selected} onBusyChange={lock} />}
  </section>;
}

function InvoiceSearch({ org, query, onSelect }: { org: string; query: string; onSelect: (id: number) => void }) {
  const [rows, setRows] = useState<Invoice[]>([]);
  const [next, setNext] = useState<number | null>(null);
  const [busy, setBusy] = useState(true);
  const [error, setError] = useState("");
  const [loaded, setLoaded] = useState(false);
  const mounted = useRef(false);
  const generation = useRef(0);
  const fetching = useRef(false);
  useLayoutEffect(() => { mounted.current = true; return () => { mounted.current = false; generation.current += 1; fetching.current = false; }; }, []);
  const load = useCallback((after = 0) => {
    if (fetching.current) return;
    fetching.current = true;
    const token = ++generation.current;
    return request<{ items: Invoice[]; next_after_id: number | null }>(`/api/sales/organizations/${org}/invoices?${new URLSearchParams({ q: query, after_id: String(after), limit: "50" })}`).then((result) => {
      if (!Array.isArray(result.items)) throw new Error("Некорректный список счетов.");
      if (mounted.current && generation.current === token) { setRows((current) => after ? [...current, ...result.items] : result.items); setNext(result.next_after_id); setLoaded(true); }
    }).catch((e: Error) => { if (mounted.current && generation.current === token) setError(e.message); })
      .finally(() => { if (mounted.current && generation.current === token) { fetching.current = false; setBusy(false); } });
  }, [org, query]);
  function nextPage(after: number) { setBusy(true); setError(""); void load(after); }
  useEffect(() => { void load(); }, [load]);
  return <div className="space-y-2">
    {busy && <p role="status">Поиск счетов…</p>}
    {error && <p role="alert" className="text-red-700">{error}</p>}
    {loaded && !rows.length && !error && <p>Счета по запросу не найдены.</p>}
    {rows.map((row) => <article key={row.id} className="space-y-1 rounded-xl border border-line p-3 text-sm">
      <h3 className="font-semibold">{row.number || "Без номера"} · ID {row.id} · версия {row.version}</h3>
      <p>{row.counterparty || "Контрагент не указан"} · {row.amount} {row.currency || "Валюта не указана"} · статус {row.status}</p>
      <p>Сделка ID {row.deal_id} · Выпущен: {row.issued_at || "нет"} · Действует до: {row.valid_until || "не указано"}</p>
      {row.superseded_by_id !== null && <p>Заменён документом ID {row.superseded_by_id}</p>}
      {!row.available_for_settlement && <p className="text-muted">{row.unavailable_reason || "Распределение недоступно"}</p>}
      <Button variant="secondary" disabled={!row.available_for_settlement || busy || !!error} onClick={() => onSelect(row.id)}>Выбрать счёт ID {row.id}</Button>
    </article>)}
    {error ? <Button variant="secondary" disabled={busy} onClick={() => nextPage(next || 0)}>Повторить поиск</Button> : next !== null && <Button variant="secondary" disabled={busy} onClick={() => nextPage(next)}>Ещё счета</Button>}
  </div>;
}

function InvoiceRegister({ org, document, onBusyChange }: { org: string; document: string; onBusyChange: (busy: boolean) => void }) {
  const path = `/api/sales/organizations/${org}/invoices/${document}/settlements`;
  const [register, setRegister] = useState<Register | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [loadError, setLoadError] = useState("");
  const [postError, setPostError] = useState("");
  const [notice, setNotice] = useState("");
  const [form, setForm] = useState({ source_key: "", bank_entry_id: "", amount: "", direction: "receipt", refund_of: "", evidence: "" });
  const [prepared, setPrepared] = useState<Allocation | null>(null);
  const [reconciliationBusy, setReconciliationBusy] = useState(false);
  const [moneyRevision, setMoneyRevision] = useState(0);
  const mutationOwner = useRef<"allocation" | "reconciliation" | null>(null);
  const acquireReconciliation = useCallback(() => {
    if (mutationOwner.current && mutationOwner.current !== "reconciliation") return false;
    mutationOwner.current = "reconciliation"; return true;
  }, []);
  const releaseReconciliation = useCallback(() => { if (mutationOwner.current === "reconciliation") mutationOwner.current = null; }, []);
  const allocationUnresolved = busy || (!!prepared && !notice);
  const unresolved = allocationUnresolved || reconciliationBusy;
  useLayoutEffect(() => { onBusyChange(unresolved); return () => onBusyChange(false); }, [unresolved, onBusyChange]);
  const mounted = useRef(false);
  const posting = useRef(false);
  const generation = useRef(0);
  useLayoutEffect(() => { mounted.current = true; return () => { mounted.current = false; generation.current += 1; }; }, []);

  const load = useCallback(() => {
    const token = ++generation.current;
    return request<Register>(path).then((data) => {
      if (!Array.isArray(data.items) || ![data.received, data.refunded, data.net_received].every((value) => typeof value === "string" && /^-?\d+(\.\d+)?$/.test(value))) throw new Error("Некорректный регистр: итоги не получены.");
      if (mounted.current && token === generation.current) setRegister(data);
    }).catch((e: Error) => { if (mounted.current && token === generation.current) setLoadError(e.message); })
      .finally(() => { if (mounted.current && token === generation.current) setLoading(false); });
  }, [path]);
  function refresh() { setLoading(true); setLoadError(""); setRegister(null); return load(); }
  useEffect(() => { void load(); }, [load]);

  async function post() {
    if (posting.current || notice || !register || loading || mutationOwner.current === "reconciliation") return;
    mutationOwner.current = "allocation";
    const body = prepared || { source_key: form.source_key.trim(), bank_entry_id: Number(form.bank_entry_id), amount: form.amount, refund_of: form.direction === "refund" ? Number(form.refund_of) : null, evidence: form.evidence.trim() };
    posting.current = true; setBusy(true); setPostError(""); setPrepared(body);
    try {
      const result = await request<{ id: number; direction: string; amount: string }>(path, body);
      if (!positiveId(String(result.id))) throw new Error("Ответ подтверждения не распознан. Повторите с тем же ключом.");
      if (!mounted.current) return;
      setNotice(`Распределение № ${result.id} подтверждено.`);
      mutationOwner.current = null;
      setMoneyRevision((n) => n + 1);
      await refresh();
    } catch (e) {
      if (mounted.current) {
        setPostError((e as Error).message);
        // An explicit first-attempt rejection allows editing. A retry rejection
        // cannot establish whether an earlier uncertain attempt committed.
        if (!prepared && [403, 404, 409, 422].includes((e as Error & { status?: number }).status || 0)) { setPrepared(null); mutationOwner.current = null; }
      }
    }
    finally { posting.current = false; if (mounted.current) setBusy(false); }
  }
  function reset() {
    setPrepared(null); setNotice(""); setPostError("");
    setForm({ source_key: "", bank_entry_id: "", amount: "", direction: "receipt", refund_of: "", evidence: "" });
  }
  const receipts = register?.items.filter((row) => row.direction === "receipt") || [];
  const valid = positiveId(form.bank_entry_id) && exactAmount(form.amount) && !!form.source_key.trim() && !!form.evidence.trim() && (form.direction === "receipt" || receipts.some((row) => String(row.id) === form.refund_of));
  return <div className="space-y-4">
    <p className="font-semibold">Счёт ID {document} · юрлицо {org}</p>
    <Button variant="secondary" disabled={loading || unresolved} onClick={() => void refresh()}>Обновить расчёты</Button>
    {loading && <p role="status">Загрузка расчётов…</p>}
    {loadError && <p role="alert" className="text-red-700">{loadError} Итоги недоступны.</p>}
    {postError && <p role="alert" className="text-red-700">{postError}</p>}
    {notice && <p role="status" className="text-money">{notice}</p>}
    <p className="text-sm text-muted">Отмена счёта недоступна. Даже нулевой остаток требует сверки истории оплат и отгрузок.</p>
    {register && <>
      <div aria-label="Итоги расчётов" className="grid gap-3 md:grid-cols-3">{[["Получено", register.received], ["Возвращено", register.refunded], ["Получено за вычетом возвратов", register.net_received]].map(([label, value]) => <section key={label} className="rounded-xl border border-line p-3"><h3 className="text-sm text-muted">{label}</h3><p className="font-semibold tabular-nums">{value} BYN</p></section>)}</div>
      {!register.items.length && <p className="text-sm text-muted">Подтверждённых распределений в этом регистре нет. Исторические оплаты требуют отдельной сверки.</p>}
      {register.items.map((row) => <article key={row.id} className="space-y-1 rounded-xl border border-line p-3 text-sm">
        <h3 className="font-semibold">{row.direction === "receipt" ? "Поступление" : "Возврат"} № {row.id} · {row.amount} BYN</h3>
        <p>Банковская проводка № {row.bank_entry_id} · {row.snapshot.bank.operation_date} · {row.snapshot.bank.amount} {row.snapshot.bank.currency}</p>
        <p>Выписка: {row.snapshot.bank.statement_reference}</p>
        {row.refund_of !== null && <p>Исходное поступление № {row.refund_of}</p>}
        <p className="break-words">Основание: {row.evidence}</p>
        <p>Счёт {row.snapshot.invoice.number} · версия {row.snapshot.invoice.version} · {row.snapshot.invoice.amount} {row.snapshot.invoice.currency}</p>
        <details><summary className="cursor-pointer text-accent">Сохранённые реквизиты основания</summary><p className="break-all">SHA-256 счёта: {row.snapshot.invoice.content_sha256}</p><p className="break-all">Хеш банковской проводки: {row.snapshot.bank.digest}</p><p className="break-words">Аналитика расчётов: {Object.entries(row.snapshot.bank.settlement_dimensions).map(([key, value]) => `${key}: ${value}`).join(" · ")}</p></details>
      </article>)}
      <h3 className="font-semibold">Распределение главного бухгалтера</h3>
      <p className="text-sm text-muted">Укажите ID уже проведённой банковской операции. Её документ расчётов должен быть sales:document:{document}. Для возврата выберите подтверждённое поступление этого счёта.</p>
      <fieldset disabled={busy || reconciliationBusy || !!prepared || !!notice} className="grid gap-3 md:grid-cols-2">
        <label>Вид распределения<Select aria-label="Вид распределения" value={form.direction} onChange={(e) => setForm({ ...form, direction: e.target.value, refund_of: "" })}><option value="receipt">Поступление</option><option value="refund">Возврат</option></Select></label>
        <label>ID банковской проводки<Input aria-label="ID банковской проводки" inputMode="numeric" value={form.bank_entry_id} onChange={(e) => setForm({ ...form, bank_entry_id: e.target.value })} /></label>
        <label>Сумма BYN<Input aria-label="Сумма распределения" inputMode="decimal" placeholder="123.45" value={form.amount} onChange={(e) => setForm({ ...form, amount: e.target.value })} /><span className="text-xs text-muted">Положительная сумма, точка и не более двух знаков после неё.</span></label>
        {form.direction === "refund" && <label>Исходное поступление<Select aria-label="Исходное поступление" value={form.refund_of} onChange={(e) => setForm({ ...form, refund_of: e.target.value })}><option value="">Выберите поступление</option>{receipts.map((row) => <option key={row.id} value={row.id}>№ {row.id} · {row.amount} BYN · проводка {row.bank_entry_id} · {row.snapshot.bank.statement_reference}</option>)}</Select></label>}
        <label>Ключ распределения<Input aria-label="Ключ распределения" maxLength={160} value={form.source_key} onChange={(e) => setForm({ ...form, source_key: e.target.value })} /></label>
        <label className="md:col-span-2">Первичное основание<Input aria-label="Первичное основание" maxLength={1000} value={form.evidence} onChange={(e) => setForm({ ...form, evidence: e.target.value })} /></label>
      </fieldset>
      <p className="text-xs text-muted">Ключ должен быть уникальным в юрлице для этого распределения. Сохраните его: повтор с тем же ключом и фактами не создаёт дубль. После отправки поля зафиксированы для точного повтора.</p>
      <div className="flex flex-wrap gap-2">
        <Button disabled={busy || reconciliationBusy || loading || !!notice || !valid} onClick={() => void post()}>{busy ? "Подтверждение…" : prepared ? "Повторить с тем же ключом" : "Подтвердить распределение"}</Button>
        {(notice || prepared) && <Button variant="secondary" disabled={unresolved} onClick={reset}>Новое распределение</Button>}
      </div>
      {prepared && !notice && <p className="text-sm text-muted">При обрыве связи сначала повторите этот запрос с тем же ключом. Перед новым распределением проверьте результат предыдущего в регистре.</p>}
    </>}
    <AccountingInvoiceMoneyReconciliation org={org} document={document} disabled={allocationUnresolved}
      revision={moneyRevision} acquire={acquireReconciliation} release={releaseReconciliation} onBusyChange={setReconciliationBusy} />
  </div>;
}
