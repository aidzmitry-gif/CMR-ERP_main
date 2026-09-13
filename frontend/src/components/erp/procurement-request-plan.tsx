"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { Input, Select } from "@/components/ui/input";

type Organization = { id: number; name: string; unp: string };
type Identity = { organization_id: number; principal: string; can_manage: boolean };
type Source = { id: number; number: string; supplier: string; item?: string; stage?: string; status?: string; quantity?: string; planned_amount?: string; due_date?: string | null };
type Page = { organization_id: number; items: Source[]; next_after_id: number | null };
type Command = { request_key: string; document: { supplier: string; item: string; qty: number; amount: string; due_date: string | null }; ownership_evidence: string };
type Receipt = { organization_id: number; request_key: string; request_id: number; ownership_id: number; number: string; stage: "need" };
type Journal = { version: 1; org: number; principal: string; nonce: string; state: "pending" | "done"; body: string; receipt?: Receipt };
const stages = ["need", "sourcing", "nego", "analysis", "approval"];
const titles: Record<string, string> = { need: "Потребность", sourcing: "Поиск поставщика", nego: "Переговоры", analysis: "Анализ", approval: "Согласовано", po: "Связана с заказом", supply: "Поставка", qc: "Приёмка", done: "Завершено" };
const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;
const money = /^(?:0|[1-9][0-9]{0,11})\.[0-9]{2}$/;
const message = (e: unknown) => e instanceof Error ? e.message : "Не удалось проверить результат";
const prefix = (org: number) => `/api/procurement/organizations/${org}`;
const journalKey = (org: number, principal: string) => `procurement-request:v1:${org}:${encodeURIComponent(principal)}`;

async function api<T>(url: string, options?: RequestInit): Promise<T> {
  const response = await fetch(url, { cache: "no-store", ...options });
  if (!response.ok) {
    const detail = await response.text();
    throw new Error(`Ошибка ${response.status}: ${detail}`);
  }
  return response.json() as Promise<T>;
}
function validCommand(command: Command) {
  const d = command.document;
  return uuid.test(command.request_key) && !!d && typeof d.supplier === "string" && !!d.supplier.trim() && d.supplier.length <= 255 &&
    typeof d.item === "string" && !!d.item.trim() && d.item.length <= 255 && Number.isInteger(d.qty) && d.qty > 0 && d.qty <= 2147483647 &&
    typeof d.amount === "string" && money.test(d.amount) && (d.due_date === null || (typeof d.due_date === "string" && /^\d{4}-\d{2}-\d{2}$/.test(d.due_date) && !isNaN(Date.parse(d.due_date)) && new Date(d.due_date).toISOString().slice(0, 10) === d.due_date)) &&
    typeof command.ownership_evidence === "string" && !!command.ownership_evidence.trim() && command.ownership_evidence.length <= 1000 &&
    Object.keys(command).sort().join() === "document,ownership_evidence,request_key" && Object.keys(d).sort().join() === "amount,due_date,item,qty,supplier";
}
function readJournal(org: number, principal: string): { raw: string | null; value: Journal | null } {
  const raw = sessionStorage.getItem(journalKey(org, principal));
  if (raw === null) return { raw, value: null };
  const value = JSON.parse(raw) as Journal;
  if (value.version !== 1 || value.org !== org || value.principal !== principal || !uuid.test(value.nonce) || !["pending", "done"].includes(value.state) || !validCommand(JSON.parse(value.body)) || (value.state === "done" && !validReceipt(value.receipt, org, JSON.parse(value.body).request_key))) {
    throw new Error("Журнал восстановления повреждён. Новая отправка запрещена.");
  }
  return { raw, value };
}
function validReceipt(receipt: Receipt | undefined, org: number, key: string) {
  return !!receipt && receipt.organization_id === org && receipt.request_key === key && Number.isInteger(receipt.request_id) && receipt.request_id > 0 && Number.isInteger(receipt.ownership_id) && receipt.ownership_id > 0 && receipt.stage === "need" && typeof receipt.number === "string" && !!receipt.number;
}
// sessionStorage is isolated per browser tab. Synchronous compare/write/readback
// has no await gap; async completions must still match the exact mounted scope.
function persist(org: number, principal: string, expected: string | null, value: Journal) {
  const key = journalKey(org, principal);
  if (sessionStorage.getItem(key) !== expected) throw new Error("Журнал изменён. Обновите план перед отправкой.");
  const raw = JSON.stringify(value);
  sessionStorage.setItem(key, raw);
  if (sessionStorage.getItem(key) !== raw) throw new Error("Не удалось подтвердить сохранение запроса. Отправка запрещена.");
  return raw;
}

export function ProcurementRequestPlan() {
  const [organizations, setOrganizations] = useState<Organization[]>([]);
  const [org, setOrg] = useState("");
  const [error, setError] = useState("");
  useEffect(() => {
    let live = true;
    api<Organization[]>("/api/procurement/receipt-organizations").then(v => { if (live) setOrganizations(v); }).catch(e => { if (live) setError(message(e)); });
    return () => { live = false; };
  }, []);
  return <section className="space-y-4 p-6"><h1 className="text-xl font-semibold">План закупок</h1>
    <p>Создание и изменение плана доступны главному бухгалтеру выбранного юрлица с доступом к закупкам.</p>
    <p>Свяжите заявку с существующим заказом своего юрлица или создайте заказ из согласованной заявки в разделе заказов поставщикам.</p>
    <Link href="/erp/procurement/ownership" className="text-accent underline">Указать юрлицо старых документов и проверить связи</Link>
    {error && <p role="alert">{error}</p>}
    <Select aria-label="Юрлицо плана закупок" value={org} onChange={e => setOrg(e.target.value)}><option value="">Выберите юрлицо</option>{organizations.map(o => <option key={o.id} value={o.id}>{o.name} · {o.unp}</option>)}</Select>
    {org && <CompanyPlan key={org} org={Number(org)} />}
  </section>;
}

function CompanyPlan({ org }: { org: number }) {
  const [identity, setIdentity] = useState<Identity | null>(null);
  const [journal, setJournal] = useState<Journal | null>(null);
  const [storageBlocked, setStorageBlocked] = useState(false);
  const [requests, setRequests] = useState<Source[]>([]);
  const [orders, setOrders] = useState<Source[]>([]);
  const [requestNext, setRequestNext] = useState<number | null>(null);
  const [orderNext, setOrderNext] = useState<number | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [form, setForm] = useState({ supplier: "", item: "", qty: "1", amount: "0.00", due_date: "", evidence: "" });
  const [selectedRequest, setSelectedRequest] = useState("");
  const [selectedOrder, setSelectedOrder] = useState("");
  const [linkEvidence, setLinkEvidence] = useState("");
  const generation = useRef(0);
  const lock = useRef(false);
  const journalRaw = useRef<string | null>(null);
  const active = (token: number) => generation.current === token;
  async function currentIdentity() {
    const v = await api<Identity>(`${prefix(org)}/request-plan-context`);
    if (v.organization_id !== org || !v.principal || typeof v.can_manage !== "boolean") throw new Error("Пользователь и юрлицо не подтверждены");
    return v;
  }
  async function page(kind: "request" | "order", after = 0) {
    const v = await api<Page>(`${prefix(org)}/owned-sources?kind=${kind}&after_id=${after}`);
    if (v.organization_id !== org || !Array.isArray(v.items) || (v.next_after_id !== null && (!Number.isInteger(v.next_after_id) || v.next_after_id <= after))) throw new Error("Некорректная страница документов");
    return v;
  }
  async function refresh(token: number) {
    const [r, o] = await Promise.all([page("request"), page("order")]);
    if (!active(token)) return;
    setRequests(r.items); setRequestNext(r.next_after_id); setOrders(o.items); setOrderNext(o.next_after_id);
    setSelectedRequest(""); setSelectedOrder("");
  }
  useEffect(() => {
    const token = ++generation.current;
    void (async () => {
      try {
        const v = await currentIdentity();
        if (!active(token)) return;
        setIdentity(v);
        try { const j = readJournal(org, v.principal); journalRaw.current = j.raw; setJournal(j.value); }
        catch (e) { setStorageBlocked(true); setError(message(e)); }
        await refresh(token);
      } catch (e) { if (active(token)) setError(message(e)); }
    })();
    // This ref is an operation counter, not a DOM node; cleanup must invalidate its latest value.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    return () => { generation.current++; };
    // The keyed component owns a fixed organization and a fresh generation.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  async function run(action: (token: number) => Promise<void>) {
    if (lock.current) return;
    lock.current = true; setBusy(true); setError(""); setNotice("");
    const token = ++generation.current;
    try { await action(token); } catch (e) { if (active(token)) setError(message(e)); }
    finally { lock.current = false; if (active(token)) setBusy(false); }
  }
  async function verifyPrincipal(token: number) {
    const current = await currentIdentity();
    if (!active(token)) return false;
    if (!identity || current.principal !== identity.principal || !current.can_manage) throw new Error("Учётная запись или права изменились. Вернитесь в план под исходной учётной записью.");
    return true;
  }
  function create(retry: boolean) {
    void run(async token => {
      if (!identity || storageBlocked || !identity.can_manage) return;
      if (!(await verifyPrincipal(token))) return;
      const saved = readJournal(org, identity.principal);
      if (saved.raw !== journalRaw.current) throw new Error("Журнал изменён. Обновите план перед отправкой.");
      let attempt = saved.value;
      if (retry) {
        if (!attempt || attempt.state !== "pending") throw new Error("Сохранённый запрос не найден");
      } else {
        if (attempt?.state === "pending") throw new Error("Сначала проверьте результат сохранённого запроса");
        const command: Command = { request_key: crypto.randomUUID(), document: { supplier: form.supplier.trim(), item: form.item.trim(), qty: Number(form.qty), amount: form.amount.trim(), due_date: form.due_date || null }, ownership_evidence: form.evidence.trim() };
        if (!validCommand(command)) throw new Error("Проверьте поля: количество — целое от 1 до 2147483647; сумма — от 0.00 до 999999999999.99, ровно два знака после точки; дата — календарная.");
        attempt = { version: 1, org, principal: identity.principal, nonce: crypto.randomUUID(), state: "pending", body: JSON.stringify(command) };
      }
      const raw = persist(org, identity.principal, saved.raw, attempt);
      journalRaw.current = raw; setJournal(attempt);
      const receipt = await api<Receipt>(`${prefix(org)}/requests`, { method: "POST", headers: { "Content-Type": "application/json", "X-Expected-Principal": identity.principal }, body: attempt.body });
      if (!active(token)) return;
      if (!(await verifyPrincipal(token))) return;
      if (!validReceipt(receipt, org, (JSON.parse(attempt.body) as Command).request_key)) throw new Error("Ответ создания не подтверждён. Повторите сохранённый запрос.");
      const done: Journal = { ...attempt, state: "done", receipt };
      journalRaw.current = persist(org, identity.principal, raw, done); setJournal(done);
      setForm({ supplier: "", item: "", qty: "1", amount: "0.00", due_date: "", evidence: "" });
      setNotice(`Создание подтверждено: ${receipt.number}.`);
      // The receipt is historical. Read current rows instead of replacing their stage.
      await refresh(token);
    });
  }
  async function mutate(path: string, method: string, body: object, token: number) {
    if (!(await verifyPrincipal(token))) return;
    await api(`${prefix(org)}${path}`, { method, headers: { "Content-Type": "application/json", "X-Expected-Principal": identity!.principal }, body: JSON.stringify(body) });
    if (active(token)) { await refresh(token); if (active(token)) setNotice("План обновлён."); }
  }
  function more(kind: "request" | "order", after: number) {
    void run(async token => {
      const p = await page(kind, after);
      if (!active(token)) return;
      if (kind === "request") { setRequests(rows => [...rows, ...p.items.filter(i => !rows.some(r => r.id === i.id))]); setRequestNext(p.next_after_id); }
      else { setOrders(rows => [...rows, ...p.items.filter(i => !rows.some(r => r.id === i.id))]); setOrderNext(p.next_after_id); }
    });
  }
  const pending = journal?.state === "pending";
  return <div className="space-y-4">
    {!identity && !error && <p role="status">Проверка доступа…</p>}{error && <p role="alert">{error}</p>}{notice && <p role="status">{notice}</p>}
    {identity && !identity.can_manage && <p>Доступен просмотр. Для изменения нужен главный бухгалтер этого юрлица с доступом к закупкам.</p>}
    {pending && <div className="rounded border border-amber-400 p-3"><p>Сохранён запрос создания. При неизвестном результате повторяется тот же запрос; новый ключ не создаётся.</p><p>Позиция: {(JSON.parse(journal.body) as Command).document.item}</p><Button disabled={busy || storageBlocked || !identity?.can_manage} onClick={() => create(true)}>Повторить сохранённый запрос</Button></div>}
    <fieldset disabled={busy || !identity?.can_manage || storageBlocked || pending} className="space-y-2 rounded border border-line p-3"><legend>Новая заявка</legend>
      {(["supplier", "item", "qty", "amount", "due_date", "evidence"] as const).map(key => <label className="block" key={key}>{({ supplier: "Поставщик", item: "Позиция", qty: "Количество", amount: "Плановая сумма (валюта не задана)", due_date: "Плановая дата", evidence: "Основание выбора юрлица" })[key]}<Input type={key === "due_date" ? "date" : "text"} value={form[key]} onChange={e => setForm(f => ({ ...f, [key]: e.target.value }))} /></label>)}
      <Button onClick={() => create(false)}>Создать заявку</Button>
    </fieldset>
    <Button disabled={busy || !identity} variant="secondary" onClick={() => void run(refresh)}>Обновить документы</Button>
    <h2 className="font-semibold">Заявки выбранного юрлица</h2>
    {requests.map(row => <article key={row.id} className="space-y-2 rounded border border-line p-3"><h3>{row.number} · {row.item}</h3><p>{row.supplier} · {row.quantity} шт. · {row.planned_amount} (валюта не задана) · {row.due_date || "Дата не задана"}</p><p>Стадия: {titles[row.stage ?? ""] ?? row.stage}</p>
      {row.stage === "approval" && <Link className="text-accent underline" href={`/erp/procurement/orders?org=${org}&request=${row.id}`}>Создать заказ из {row.number}</Link>}
      {stages.includes(row.stage ?? "") && row.stage !== "approval" && <Button disabled={busy || !identity?.can_manage} onClick={() => void run(token => mutate(`/requests/${row.id}/stage`, "PATCH", { expected_stage: row.stage, stage: stages[stages.indexOf(row.stage!) + 1] }, token))}>Далее: {titles[stages[stages.indexOf(row.stage!) + 1]]} · {row.number}</Button>}
    </article>)}
    {identity && !requests.length && <p>На загруженной странице заявок нет.</p>}
    {requestNext !== null && <Button disabled={busy} onClick={() => more("request", requestNext)}>Ещё заявки</Button>}
    <fieldset disabled={busy || !identity?.can_manage} className="space-y-2 rounded border border-line p-3"><legend>Связь с существующим заказом</legend>
      <Select aria-label="Согласованная заявка" value={selectedRequest} onChange={e => setSelectedRequest(e.target.value)}><option value="">Выберите заявку</option>{requests.filter(r => r.stage === "approval").map(r => <option key={r.id} value={r.id}>{r.number}</option>)}</Select>
      <Select aria-label="Заказ своего юрлица" value={selectedOrder} onChange={e => setSelectedOrder(e.target.value)}><option value="">Выберите заказ</option>{orders.filter(o => o.status !== "cancelled").map(o => <option key={o.id} value={o.id}>{o.number} · {o.supplier}</option>)}</Select>
      <label className="block">Основание связи<Input value={linkEvidence} onChange={e => setLinkEvidence(e.target.value)} maxLength={1000} /></label>
      <Button disabled={!selectedRequest || !selectedOrder || !linkEvidence.trim()} onClick={() => void run(token => mutate(`/requests/${selectedRequest}/order-link`, "POST", { expected_stage: "approval", order_id: Number(selectedOrder), evidence: linkEvidence.trim() }, token))}>Связать заявку с заказом</Button>
    </fieldset>
    {orderNext !== null && <Button disabled={busy} onClick={() => more("order", orderNext)}>Ещё заказы</Button>}
  </div>;
}
