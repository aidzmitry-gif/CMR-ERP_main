"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState, type FormEvent } from "react";
import { fetchContactsResult, localToNaiveUtc } from "@/lib/api";
import { loadDirectory, type ClientRow } from "@/lib/crm-directory";
import type { Lead } from "@/lib/types";
import { loadLeadsClient, type LeadsLoadState } from "./leads-load";

const input = "w-full min-w-0 max-w-full rounded border border-line bg-surface px-3 py-2 text-ink";
const button = "rounded border border-line px-3 py-2 disabled:opacity-50";
type Contact = { id: number; full_name: string };
type Sku = { id: number; code: string; title: string };
type Row = { sku_id: number; qty: string; price: string };

function readRows(value: unknown): Row[] {
  if (!Array.isArray(value)) throw new Error("Некорректный ответ позиций.");
  return value.map((row: unknown) => {
    if (!row || typeof row !== "object") throw new Error("Некорректная позиция.");
    const r = row as Record<string, unknown>;
    const numeric = (v: unknown) => (typeof v === "number" || typeof v === "string" && v.trim() !== "") && Number.isFinite(Number(v));
    if (typeof r.sku_id !== "number" || !Number.isSafeInteger(r.sku_id) || r.sku_id <= 0 || !numeric(r.qty) || Number(r.qty) <= 0
      || r.price !== null && (!numeric(r.price) || Number(r.price) < 0)) throw new Error("Некорректная позиция.");
    return { sku_id: r.sku_id, qty: String(r.qty), price: r.price === null ? "" : String(r.price) };
  });
}

async function request(url: string, body?: unknown, method = "POST") {
  const response = await fetch(url, body === undefined && method === "GET" ? { cache: "no-store" } : {
    method, headers: { "Content-Type": "application/json" }, body: body === undefined ? undefined : JSON.stringify(body),
  });
  const data = await response.json();
  if (!response.ok) {
    const failure = new Error(typeof data?.detail === "string" ? data.detail : "Не удалось выполнить действие. Проверьте данные и повторите.");
    Object.assign(failure, { status: response.status }); throw failure;
  }
  return data;
}

export function OwnLeadsWorkspace({ initialLeads, initialLoadState = "ok" }: {
  initialLeads: Lead[]; initialLoadState?: LeadsLoadState;
}) {
  const [leads, setLeads] = useState(initialLeads);
  const [error, setError] = useState(initialLoadState === "ok" ? "" : "Не удалось загрузить лиды.");
  const [selected, setSelected] = useState<number | null>(null);
  const [creating, setCreating] = useState(false);
  const generation = useRef(0);
  useEffect(() => () => { generation.current++; }, []);
  async function refresh() {
    const current = ++generation.current;
    const result = await loadLeadsClient();
    if (current !== generation.current) return;
    if (result.state !== "ok") { setError("Не удалось обновить лиды. Сохранённые данные оставлены на экране."); return; }
    setLeads(result.leads); setError("");
  }
  const lead = leads.find((row) => row.id === selected);
  return <main className="min-w-0 flex-1 space-y-4 overflow-auto p-3 text-ink [overflow-wrap:anywhere] sm:p-6">
    <div className="flex flex-wrap items-center gap-3"><h1 className="text-xl font-semibold">Мои лиды</h1>
      <button className={button} onClick={() => setCreating(true)}>Новый лид</button>
      <button className={button} onClick={() => void refresh()}>Обновить</button></div>
    {error && <p role="alert">{error}</p>}
    {creating && <CreateOwnLead onCreated={(id) => { setCreating(false); setSelected(id); void refresh(); }} onCancel={() => setCreating(false)} />}
    {!leads.length && !error && <p>Лидов пока нет. Выберите CRM-клиента, чтобы создать первый.</p>}
    <div className="grid min-w-0 gap-4 lg:grid-cols-2"><div className="min-w-0 space-y-2">
      {leads.map((row) => <button key={row.id} className={`${button} block w-full text-left`} onClick={() => setSelected(row.id)}>
        <strong>{row.company || row.name}</strong><span className="ml-3">{row.status}</span><p>{row.product || row.message}</p>
      </button>)}
    </div>{lead && <OwnLeadEditor key={lead.id} lead={lead} onUpdated={() => void refresh()} />}</div>
  </main>;
}

function CreateOwnLead({ onCreated, onCancel }: { onCreated: (id: number) => void; onCancel: () => void }) {
  const [query, setQuery] = useState(""); const [offset, setOffset] = useState(0);
  const [clients, setClients] = useState<ClientRow[]>([]); const [total, setTotal] = useState(0);
  const [clientId, setClientId] = useState(""); const [contactId, setContactId] = useState("");
  const [contacts, setContacts] = useState<Contact[] | null>(null);
  const [message, setMessage] = useState(""); const [error, setError] = useState("");
  const [busy, setBusy] = useState(false); const [pending, setPending] = useState(false);
  const [retry, setRetry] = useState(0);
  const snapshot = useRef<object | null>(null); const inFlight = useRef(false); const alive = useRef(true);
  useEffect(() => { alive.current = true; return () => { alive.current = false; }; }, []);
  useEffect(() => {
    const controller = new AbortController();
    void loadDirectory("clients", query, offset, controller.signal).then((result) => {
      if (controller.signal.aborted) return;
      if (result.status !== "ok") { setClients([]); setError("Не удалось загрузить клиентов."); return; }
      setClients((result.rows as ClientRow[]).filter((row) => row.source === "crm")); setTotal(result.total); setError("");
    });
    return () => controller.abort();
  }, [query, offset, retry]);
  useEffect(() => {
    const controller = new AbortController();
    if (clientId) void (async () => {
      try {
        const result = await fetchContactsResult({ clientId: Number(clientId) });
        if (result.status !== "ok") throw new Error();
        if (!controller.signal.aborted) { setContacts(result.data); setError(""); }
      } catch { if (!controller.signal.aborted) setError("Не удалось загрузить контакты клиента."); }
    })();
    return () => controller.abort();
  }, [clientId, retry]);
  function selectClient(value: string) { setClientId(value); setContacts(null); setContactId(""); }
  async function submit(event: FormEvent) {
    event.preventDefault(); if (inFlight.current || !clientId || contacts === null) return;
    inFlight.current = true; setBusy(true); setPending(true); setError("");
    snapshot.current ??= { source: "phone", crm_client_id: Number(clientId), crm_contact_id: contactId ? Number(contactId) : null,
      message, request_key: crypto.randomUUID() };
    try {
      const result = await request("/api/leads", snapshot.current);
      if (!Number.isSafeInteger(result?.id) || result.id <= 0) throw new Error("Не удалось подтвердить создание. Повторите тот же запрос.");
      if (alive.current) onCreated(result.id);
    } catch (failure) {
      if (alive.current) {
        setError(failure instanceof Error ? failure.message : "Ошибка создания.");
        if (failure && typeof failure === "object" && "status" in failure && [401, 403, 404, 409, 422].includes(Number(failure.status))) {
          snapshot.current = null; setPending(false);
        }
      }
    }
    finally { inFlight.current = false; if (alive.current) setBusy(false); }
  }
  return <form onSubmit={submit} className="min-w-0 space-y-3 rounded border border-line p-4">
    <h2 className="font-semibold">Лид из CRM-клиента</h2>
    <fieldset disabled={pending || busy} className="flex min-w-0 flex-wrap gap-3 [&>label]:min-w-0 [&>label]:max-w-full">
      <label>Поиск клиента <input className={input} value={query} onChange={(e) => { setQuery(e.target.value); setOffset(0); selectClient(""); }} /></label>
      <label>CRM-клиент <select aria-label="CRM-клиент" className={input} value={clientId} onChange={(e) => selectClient(e.target.value)} required>
        <option value="">Выберите клиента</option>{clients.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}</select></label>
      <button type="button" className={button} disabled={!offset} onClick={() => { setOffset(offset - 50); selectClient(""); }}>Предыдущие клиенты</button>
      <button type="button" className={button} disabled={offset + 50 >= total} onClick={() => { setOffset(offset + 50); selectClient(""); }}>Следующие клиенты</button>
      <label>Контакт <select className={input} value={contactId} disabled={contacts === null} onChange={(e) => setContactId(e.target.value)}>
        <option value="">Без контакта</option>{contacts?.map((c) => <option key={c.id} value={c.id}>{c.full_name}</option>)}</select></label>
      <label>Обращение <textarea className={input} maxLength={4000} value={message} onChange={(e) => setMessage(e.target.value)} /></label>
    </fieldset>
    {error && <p role="alert">{error}</p>}
    <button className={button} disabled={busy || !clientId || contacts === null}>{pending ? "Повторить создание" : "Создать лид"}</button>
    {!pending && <><button type="button" className={button} onClick={() => { setContacts(null); setContactId(""); setRetry(retry + 1); }}>Повторить загрузку</button>
      <button type="button" className={button} onClick={onCancel}>Отмена</button></>}
    {pending && <p>Данные запроса сохранены для безопасного повтора. После подтверждения лид появится в списке.</p>}
  </form>;
}

export function OwnLeadEditor(props: { lead: Lead; onUpdated: () => void }) {
  return <LeadEditorBody key={props.lead.id} {...props} />;
}

function LeadEditorBody({ lead, onUpdated }: { lead: Lead; onUpdated: () => void }) {
  const [rows, setRows] = useState<Row[] | null>(null); const [skus, setSkus] = useState<Sku[]>([]);
  const [skuId, setSkuId] = useState(""); const [error, setError] = useState(""); const [busy, setBusy] = useState(false);
  const [note, setNote] = useState(lead.nextStepNote || ""); const [date, setDate] = useState("");
  const [savedRows, setSavedRows] = useState("");
  const [retry, setRetry] = useState(0); const alive = useRef(true); const inFlight = useRef(false);
  useEffect(() => { alive.current = true; return () => { alive.current = false; }; }, []);
  useEffect(() => {
    let current = true;
    void Promise.all([request(`/api/leads/${lead.id}/items`, undefined, "GET"), request("/api/sales/skus?for_picker=1", undefined, "GET")])
      .then(([items, catalog]) => {
        if (!current) return;
        if (!Array.isArray(items) || !Array.isArray(catalog)) throw new Error("Некорректный ответ каталога.");
        const loaded = readRows(items);
        setRows(loaded); setSavedRows(JSON.stringify(loaded));
        setSkus(catalog); setError("");
      }).catch(() => { if (current) setError("Не удалось загрузить позиции. Повторите загрузку."); });
    return () => { current = false; };
  }, [lead.id, retry]);
  async function act(suffix: string, body?: unknown, method = "POST") {
    if (inFlight.current) return; inFlight.current = true; setBusy(true); setError("");
    try {
      const result = await request(`/api/leads/${lead.id}/${suffix}`, body, method);
      if (alive.current) {
        if (suffix === "items") { const saved = readRows(result); setRows(saved); setSavedRows(JSON.stringify(saved)); }
        onUpdated();
      }
    }
    catch (failure) {
      if (alive.current) {
        setError(failure instanceof Error ? failure.message : "Ошибка действия.");
        const status = failure && typeof failure === "object" && "status" in failure ? Number(failure.status) : undefined;
        if (suffix === "route" && (status === undefined || status === 409 || status >= 500)) onUpdated();
      }
    }
    finally { inFlight.current = false; if (alive.current) setBusy(false); }
  }
  const dirty = rows !== null && JSON.stringify(rows) !== savedRows;
  const terminal = lead.status === "converted" || lead.status === "rejected";
  const validRows = rows !== null && rows.every((r) => r.price.trim() !== "" && Number.isFinite(Number(r.price)) && Number(r.price) >= 0 && Number.isFinite(Number(r.qty)) && Number(r.qty) > 0);
  return <section className="min-w-0 space-y-3 rounded border border-line p-4 [overflow-wrap:anywhere]">
    <h2 className="font-semibold">Лид #{lead.id} — {lead.company}</h2>
    <p>{lead.status} · {lead.assignedTo || "Ещё не распределён"}</p>
    <Link href={`/crm/leads/${lead.id}`}>Открыть карточку лида</Link>
    {lead.crmClientId && <Link className="ml-3" href={`/crm/clients/${lead.crmClientId}`}>Клиент и контакты</Link>}
    {error && <p role="alert">{error}</p>}
    <button className={button} disabled={busy} onClick={() => { setRows(null); setRetry(retry + 1); }}>Обновить позиции</button>
    <fieldset disabled={busy || terminal || rows === null} className="min-w-0 space-y-2 [&_label]:block [&_label]:min-w-0 [&_label]:max-w-full">
      <label>Товар <select className={input} value={skuId} onChange={(e) => setSkuId(e.target.value)}><option value="">Выберите товар</option>
        {skus.map((sku) => <option key={sku.id} value={sku.id}>{sku.code} — {sku.title}</option>)}</select></label>
      <button className={button} disabled={!skuId} onClick={() => setRows([...(rows || []), { sku_id: Number(skuId), qty: "1", price: "" }])}>Добавить позицию</button>
      {rows?.map((row, index) => <div key={index} className="flex flex-wrap gap-2">
        <span>{skus.find((s) => s.id === row.sku_id)?.code || row.sku_id}</span>
        <label>Количество {index + 1}<input className={input} type="number" step="0.01" min="0.01" value={row.qty} onChange={(e) => setRows(rows.map((r, i) => i === index ? { ...r, qty: e.target.value } : r))} /></label>
        <label>Цена {index + 1}<input className={input} type="number" step="0.01" min="0" value={row.price} onChange={(e) => setRows(rows.map((r, i) => i === index ? { ...r, price: e.target.value } : r))} /></label>
        <button className={button} onClick={() => setRows(rows.filter((_, i) => i !== index))}>Удалить позицию {index + 1}</button>
      </div>)}
      <button className={button} disabled={!validRows} onClick={() => void act("items", rows?.map((r) => ({ sku_id: r.sku_id, qty: Number(r.qty), price: Number(r.price) })), "PUT")}>Сохранить позиции</button>
      {lead.status === "new" && <button className={button} onClick={() => void act("qualify")}>Квалифицировать</button>}
      {lead.status === "qualified" && <div className="space-y-2"><label>Следующий шаг <input className={input} maxLength={128} value={note} onChange={(e) => setNote(e.target.value)} /></label>
        <label>Срок <input className={input} type="datetime-local" value={date} onChange={(e) => setDate(e.target.value)} /></label>
        <button className={button} disabled={!note.trim() || !date} onClick={() => void act("route", { owner_id: lead.ownerId, next_step_note: note, next_step_at: localToNaiveUtc(date) })}>Назначить себе</button></div>}
      {lead.status === "routed" && <button className={button} disabled={dirty || !validRows} onClick={() => void act("convert")}>Конвертировать в сделку</button>}
    </fieldset>
    {dirty && <p>Сохраните позиции перед конвертацией.</p>}
    {lead.dealId ? <Link className={button} href={`/crm/deals/${lead.dealId}`}>Открыть сделку</Link> : lead.status === "converted" && <p>Конвертация принята. <button className={button} onClick={onUpdated}>Проверить создание сделки</button></p>}
  </section>;
}

export function OwnLeadDetail({ lead }: { lead: Lead }) {
  const router = useRouter();
  return <OwnLeadEditor key={lead.id} lead={lead} onUpdated={() => router.refresh()} />;
}
