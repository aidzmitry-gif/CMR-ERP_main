"use client";
import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { Input, Select } from "@/components/ui/input";
import { fetchProcurementSkus, type ProcurementSkuOptions } from "@/lib/procurement-machine";

type Org = { id: number; name: string; unp: string };
type Identity = { organization_id: number; principal: string; can_manage: boolean };
type Source = { id: number; number: string; supplier: string; stage?: string; status?: string };
type Page = { organization_id: number; items: Source[]; next_after_id: number | null };
type Line = { sku_code: string; qty: string; goods_value_byn: string; weight: string; volume: string; sku_id?: number; sku_title?: string; sku_unit?: string };
type Document = { supplier: string; eta_date: string | null; freight_byn: string; lines: Line[] };
type RequestSnapshot = { request_id: number; ownership_id: number; number: string; supplier: string; supplier_id: number | null; item: string; qty: string; amount: string; due_date: string | null; stage: "approval" };
type Basis = { organization_id: number; snapshot: RequestSnapshot; basis_hash: string };
type Command = { request_key: string; document: Document; ownership_evidence: string; request_basis: { request_id: number; expected_stage: "approval"; expected_hash: string; link_evidence: string } | null };
type Outcome = { organization_id: number; request_key: string; principal: string; outcome: "created" | "rejected"; code?: string; no_business_write?: boolean; order_id?: number; ownership_id?: number; number?: string; status?: string; lines?: (Line & { id: number })[]; supplier?: string; eta_date?: string | null; freight_byn?: string; request_id?: number | null; request_ownership_id?: number | null; link_id?: number | null; request_snapshot?: RequestSnapshot | null };
type Journal = { version: 1; org: number; principal: string; nonce: string; body: string; mode: "create" | "reconcile"; state: "pending" | "settled"; result?: Outcome };
type Detail = { organization_id: number; id: number; number: string; supplier: string; status: string; eta_date: string | null; freight_byn: string; lines: (Line & { id: number })[]; next_after_line_id: number | null };
const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;
const hash = /^[0-9a-f]{64}$/;
const codes: Record<string, string> = { request_basis_changed: "Заявка изменилась. Проверьте её заново.", request_basis_unavailable: "Заявка недоступна в выбранном юрлице.", request_already_linked: "Заявка уже связана с заказом.", command_abandoned: "Неисполненная попытка закрыта. Поздний запрос не создаст заказ.", sku_catalog_changed: "Номенклатура изменилась. Выберите товар из справочника заново." };
const blankLine = (): Line => ({ sku_code: "", qty: "1.00", goods_value_byn: "0.00", weight: "0.000", volume: "0.0000" });
const url = (org: number) => `/api/procurement/organizations/${org}`;
const storageKey = (org: number, principal: string) => `procurement-order:v1:${org}:${encodeURIComponent(principal)}`;
const errorText = (e: unknown) => e instanceof Error ? e.message : "Не удалось проверить результат";
// Explicit Python str.strip whitespace; JS trim additionally removes U+FEFF.
const trim = (s: string) => s.replace(/^[\u0009-\u000d\u001c-\u0020\u0085\u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000]+|[\u0009-\u000d\u001c-\u0020\u0085\u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000]+$/g, "");
const textValid = (s: string, max: number) => typeof s === "string" && !!s && s === trim(s) && [...s].length <= max && !s.includes("\0");
const decimal = (s: string, scale: number, positive = false) => typeof s === "string" && new RegExp(`^(?:0|[1-9][0-9]{0,${13 - scale}})\\.[0-9]{${scale}}$`).test(s) && (!positive || /[1-9]/.test(s));
function validCommand(c: Command) {
  if (!c || !exactKeys(c, ["request_key", "document", "ownership_evidence", "request_basis"])) return false;
  const d = c.document, b = c.request_basis;
  return uuid.test(c.request_key) && !!d && exactKeys(d, ["supplier", "eta_date", "freight_byn", "lines"]) && textValid(d.supplier, 255) && decimal(d.freight_byn, 2) && textValid(c.ownership_evidence, 1000) &&
    (d.eta_date === null || (typeof d.eta_date === "string" && /^[0-9]{4}-[0-9]{2}-[0-9]{2}$/.test(d.eta_date) && !d.eta_date.startsWith("0000") && !isNaN(Date.parse(d.eta_date)) && new Date(d.eta_date).toISOString().slice(0, 10) === d.eta_date)) &&
    Array.isArray(d.lines) && d.lines.length > 0 && d.lines.length <= 200 && new Set(d.lines.map(x => x.sku_code)).size === d.lines.length &&
    d.lines.every(x => !!x && (exactKeys(x, ["sku_code", "qty", "goods_value_byn", "weight", "volume"]) || exactKeys(x, ["sku_code", "qty", "goods_value_byn", "weight", "volume", "sku_id", "sku_title", "sku_unit"])) &&
      textValid(x.sku_code, 64) && (!("sku_id" in x) || (positiveId(x.sku_id) && textValid(x.sku_title ?? "", 255) && textValid(x.sku_unit ?? "", 16))) &&
      decimal(x.qty, 2, true) && decimal(x.goods_value_byn, 2) && decimal(x.weight, 3) && decimal(x.volume, 4)) &&
    (b === null || (!!b && exactKeys(b, ["request_id", "expected_stage", "expected_hash", "link_evidence"]) && Number.isInteger(b.request_id) && b.request_id > 0 && b.request_id <= 2147483647 && b.expected_stage === "approval" && hash.test(b.expected_hash) && textValid(b.link_evidence, 1000)));
}
const exactKeys = (value: object, keys: string[]) => Object.keys(value).sort().join() === [...keys].sort().join();
const positiveId = (value: unknown) => typeof value === "number" && Number.isInteger(value) && value > 0 && value <= 2147483647;
const storedText = (value: unknown, max: number) => typeof value === "string" && [...value].length <= max && !value.includes("\0");
function validSnapshot(snapshot: RequestSnapshot | null | undefined, requestId: number, ownershipId: number) {
  return !!snapshot && exactKeys(snapshot, ["request_id", "ownership_id", "number", "supplier", "supplier_id", "item", "qty", "amount", "due_date", "stage"]) &&
    snapshot.request_id === requestId && snapshot.ownership_id === ownershipId && snapshot.stage === "approval" &&
    storedText(snapshot.number, 64) && storedText(snapshot.supplier, 255) && storedText(snapshot.item, 255) &&
    (snapshot.supplier_id === null || (Number.isInteger(snapshot.supplier_id) && snapshot.supplier_id >= -2147483648 && snapshot.supplier_id <= 2147483647)) &&
    typeof snapshot.qty === "string" && /^(?:0|-?[1-9][0-9]*)$/.test(snapshot.qty) && Number(snapshot.qty) >= -2147483648 && Number(snapshot.qty) <= 2147483647 &&
    typeof snapshot.amount === "string" && /^-?(?:0|[1-9][0-9]{0,11})\.[0-9]{2}$/.test(snapshot.amount) &&
    (snapshot.due_date === null || storedText(snapshot.due_date, 32));
}
async function snapshotHash(snapshot: RequestSnapshot) {
  // A closed, flat snapshot of strings, integer IDs and nulls. JSON.stringify
  // matches Python ensure_ascii=False for these scalar types; sort ASCII keys.
  const canonical = "{" + Object.keys(snapshot).sort().map(key => JSON.stringify(key) + ":" + JSON.stringify(snapshot[key as keyof RequestSnapshot])).join(",") + "}";
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(canonical));
  return Array.from(new Uint8Array(digest), byte => byte.toString(16).padStart(2, "0")).join("");
}
async function validOutcome(o: Outcome | undefined, org: number, principal: string, command: Command) {
  if (!o || o.organization_id !== org || o.principal !== principal || o.request_key !== command.request_key) return false;
  if (o.outcome === "rejected") return o.no_business_write === true && Object.hasOwn(codes, o.code ?? "") && exactKeys(o, ["code", "no_business_write", "organization_id", "outcome", "principal", "request_key"]);
  if (o.outcome !== "created" || !exactKeys(o, ["organization_id", "request_key", "principal", "outcome", "order_id", "ownership_id", "number", "status", "supplier", "eta_date", "freight_byn", "lines", "request_id", "request_ownership_id", "link_id", "request_snapshot"]) ||
      !positiveId(o.order_id) || !positiveId(o.ownership_id) || !textValid(o.number ?? "", 64) || o.status !== "draft" ||
      o.supplier !== command.document.supplier || o.eta_date !== command.document.eta_date || o.freight_byn !== command.document.freight_byn ||
      !Array.isArray(o.lines) || o.lines.length !== command.document.lines.length || new Set(o.lines.map(x => x?.id)).size !== o.lines.length ||
      !o.lines.every((line, i) => !!line && exactKeys(line, ["id", "sku_code", "qty", "goods_value_byn", "weight", "volume"]) && positiveId(line.id) &&
        Object.entries(command.document.lines[i]).filter(([key]) => !["sku_id", "sku_title", "sku_unit"].includes(key)).every(([key, value]) => line[key as keyof Line] === value))) return false;
  const basis = command.request_basis;
  if (basis === null) return o.request_id === null && o.request_ownership_id === null && o.link_id === null && o.request_snapshot === null;
  if (o.request_id !== basis.request_id || !positiveId(o.request_ownership_id) || o.request_ownership_id === o.ownership_id || !positiveId(o.link_id) || !validSnapshot(o.request_snapshot, basis.request_id, o.request_ownership_id!)) return false;
  return await snapshotHash(o.request_snapshot!) === basis.expected_hash;
}
async function read(org: number, principal: string) {
  const key = storageKey(org, principal), raw = sessionStorage.getItem(key);
  if (raw === null) return { raw, value: null };
  const j = JSON.parse(raw) as Journal;
  if (j.version !== 1 || j.org !== org || j.principal !== principal || !uuid.test(j.nonce) || !["create", "reconcile"].includes(j.mode) || !["pending", "settled"].includes(j.state) || !validCommand(JSON.parse(j.body)) || (j.state === "settled" && !(await validOutcome(j.result, org, principal, JSON.parse(j.body))))) throw new Error("Журнал заказа повреждён. Новая отправка запрещена.");
  if (sessionStorage.getItem(key) !== raw) throw new Error("Журнал изменён. Обновите страницу.");
  return { raw, value: j };
}
function write(org: number, principal: string, expected: string | null, value: Journal) {
  const key = storageKey(org, principal);
  if (sessionStorage.getItem(key) !== expected) throw new Error("Журнал изменён. Обновите страницу.");
  const raw = JSON.stringify(value); sessionStorage.setItem(key, raw);
  if (sessionStorage.getItem(key) !== raw) throw new Error("Сохранение запроса не подтверждено. Отправка запрещена.");
  return raw;
}
async function get<T>(path: string): Promise<T> {
  const r = await fetch(path, { cache: "no-store" });
  if (!r.ok) throw new Error(`Ошибка ${r.status}: ${await r.text()}`);
  return r.json();
}

export function ProcurementOrderCreate({ suggestedOrg, suggestedRequest }: { suggestedOrg?: string; suggestedRequest?: string }) {
  const [orgs, setOrgs] = useState<Org[]>([]), [org, setOrg] = useState(""), [error, setError] = useState("");
  useEffect(() => { let live = true; get<Org[]>("/api/procurement/receipt-organizations").then(x => { if (live) setOrgs(x); }).catch(e => { if (live) setError(errorText(e)); }); return () => { live = false; }; }, []);
  return <section className="space-y-4 p-6"><h1 className="text-xl font-semibold">Заказы поставщикам</h1><p>Создайте черновик с позициями в выбранном юрлице. Изменения доступны главному бухгалтеру с доступом к закупкам.</p>
    {suggestedOrg && suggestedRequest && <p>Переход из плана: юрлицо {suggestedOrg}, заявка {suggestedRequest}. Подтвердите выбор в форме.</p>}
    <Link href="/erp/procurement/ownership" className="text-accent underline">Указать юрлицо старых заказов</Link>
    {error && <p role="alert">{error}</p>}<Select aria-label="Юрлицо заказа" value={org} onChange={e => setOrg(e.target.value)}><option value="">Выберите юрлицо</option>{orgs.map(o => <option value={o.id} key={o.id}>{o.name} · {o.unp}</option>)}</Select>
    {org && <OrderWorkspace key={org} org={Number(org)} />}
  </section>;
}

function OrderWorkspace({ org }: { org: number }) {
  const [identity, setIdentity] = useState<Identity | null>(null), [journal, setJournal] = useState<Journal | null>(null);
  const [blocked, setBlocked] = useState(false), [busy, setBusy] = useState(false), [error, setError] = useState(""), [reviewing, setReviewing] = useState(false);
  const [orders, setOrders] = useState<Source[]>([]), [requests, setRequests] = useState<Source[]>([]), [orderNext, setOrderNext] = useState<number | null>(null), [requestNext, setRequestNext] = useState<number | null>(null);
  const [mode, setMode] = useState(""), [requestId, setRequestId] = useState(""), [basis, setBasis] = useState<Basis | null>(null);
  const [supplier, setSupplier] = useState(""), [eta, setEta] = useState(""), [freight, setFreight] = useState("0.00"), [evidence, setEvidence] = useState(""), [linkEvidence, setLinkEvidence] = useState("");
  const [lines, setLines] = useState<Line[]>([blankLine()]), [detail, setDetail] = useState<Detail | null>(null);
  const [skuSearch, setSkuSearch] = useState(""), [skuOptions, setSkuOptions] = useState<ProcurementSkuOptions | null>(null), [skuError, setSkuError] = useState("");
  const generation = useRef(0), lock = useRef(false), stored = useRef<string | null>(null);
  const active = (token: number) => generation.current === token;
  useEffect(() => {
    let live = true;
    const timer = window.setTimeout(() => {
      void fetchProcurementSkus(org, skuSearch).then(value => { if (live) { setSkuOptions(value); setSkuError(""); } })
        .catch(cause => { if (live) { setSkuOptions(null); setSkuError(errorText(cause)); } });
    }, 200);
    return () => { live = false; window.clearTimeout(timer); };
  }, [org, skuSearch]);
  async function who() { const v = await get<Identity>(`${url(org)}/request-plan-context`); if (v.organization_id !== org || !v.principal || typeof v.can_manage !== "boolean") throw new Error("Не удалось подтвердить пользователя"); return v; }
  async function sameUser(token: number) { const v = await who(); if (!active(token)) return false; if (!identity || v.principal !== identity.principal || !v.can_manage) throw new Error("Пользователь или права изменились. Войдите под исходной учётной записью."); return true; }
  async function page(kind: "request" | "order", after = 0) {
    const p = await get<Page>(`${url(org)}/owned-sources?kind=${kind}&after_id=${after}`);
    if (p.organization_id !== org || !Array.isArray(p.items) || (p.next_after_id !== null && (!Number.isInteger(p.next_after_id) || p.next_after_id <= after))) throw new Error("Некорректная страница документов"); return p;
  }
  async function reload(token: number) { const [a, b] = await Promise.all([page("order"), page("request")]); if (active(token)) { setOrders(a.items); setOrderNext(a.next_after_id); setRequests(b.items); setRequestNext(b.next_after_id); } }
  useEffect(() => {
    const token = ++generation.current;
    void (async () => {
      try {
        const v = await who(); if (!active(token)) return;
        let j: Awaited<ReturnType<typeof read>> | undefined;
        try { j = await read(org, v.principal); }
        catch (e) { if (active(token)) { setBlocked(true); setError(errorText(e)); } }
        if (!active(token)) return;
        const current = await who(); if (!active(token)) return;
        if (current.principal !== v.principal) throw new Error("Пользователь изменился. Обновите страницу.");
        if (j) {
          if (sessionStorage.getItem(storageKey(org, current.principal)) !== j.raw) throw new Error("Журнал изменён. Обновите страницу.");
          stored.current = j.raw; setJournal(j.value);
        }
        setIdentity(current); await reload(token);
      } catch (e) { if (active(token)) setError(errorText(e)); }
    })();
    // Operation counter, not a DOM ref: invalidate every outstanding callback.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    return () => { generation.current++; };
    // The keyed mount owns one organization.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  async function run(action: (token: number) => Promise<void>) { if (lock.current) return; lock.current = true; setBusy(true); setError(""); const token = ++generation.current; try { await action(token); } catch (e) { if (active(token)) setError(errorText(e)); } finally { lock.current = false; if (active(token)) setBusy(false); } }
  async function loadDetail(id: number, token: number, after = 0) {
    const v = await get<Detail>(`${url(org)}/orders/${id}?after_line_id=${after}`);
    if (!active(token)) return;
    if (v.organization_id !== org || v.id !== id || !Array.isArray(v.lines) || (v.next_after_line_id !== null && (!Number.isInteger(v.next_after_line_id) || v.next_after_line_id <= after))) throw new Error("Некорректный состав заказа");
    setDetail(old => after && old?.id === id ? { ...v, lines: [...old.lines, ...v.lines.filter(x => !old.lines.some(y => y.id === x.id))] } : v);
  }
  function more(kind: "order" | "request", after: number) { void run(async token => { const p = await page(kind, after); if (!active(token)) return; if (kind === "order") { setOrders(a => [...a, ...p.items.filter(x => !a.some(y => y.id === x.id))]); setOrderNext(p.next_after_id); } else { setRequests(a => [...a, ...p.items.filter(x => !a.some(y => y.id === x.id))]); setRequestNext(p.next_after_id); } }); }
  function reviewBasis() { void run(async token => { setBasis(null); const b = await get<Basis>(`${url(org)}/requests/${requestId}/order-basis`); if (!active(token)) return; if (b.organization_id !== org || b.snapshot.request_id !== Number(requestId) || b.snapshot.stage !== "approval" || !hash.test(b.basis_hash)) throw new Error("Основание заявки не подтверждено"); setBasis(b); }); }
  function dispatch(action: "new" | "retry" | "reconcile") {
    void run(async token => {
      if (!identity || blocked || !(await sameUser(token))) return;
      const saved = await read(org, identity.principal);
      if (!active(token) || !(await sameUser(token))) return;
      if (saved.raw !== stored.current) throw new Error("Журнал изменён. Обновите страницу.");
      let attempt = saved.value;
      if (action === "new") {
        if (attempt?.state === "pending" || (attempt?.result?.outcome === "rejected" && !reviewing)) throw new Error("Сначала проверьте сохранённый результат");
        if (!mode || (mode === "request" && (!basis || basis.snapshot.request_id !== Number(requestId)))) throw new Error("Выберите основание заказа и проверьте заявку");
        if (lines.some(line => !positiveId(line.sku_id) || !line.sku_title || !line.sku_unit)) throw new Error("Выберите номенклатуру из справочника для каждой позиции.");
        const c: Command = { request_key: crypto.randomUUID(), document: { supplier: trim(supplier), eta_date: eta || null, freight_byn: trim(freight), lines: lines.map(x => ({ sku_code: x.sku_code, sku_id: x.sku_id, sku_title: x.sku_title, sku_unit: x.sku_unit, qty: trim(x.qty), goods_value_byn: trim(x.goods_value_byn), weight: trim(x.weight), volume: trim(x.volume) })) }, ownership_evidence: trim(evidence), request_basis: mode === "request" ? { request_id: Number(requestId), expected_stage: "approval", expected_hash: basis!.basis_hash, link_evidence: trim(linkEvidence) } : null };
        if (!validCommand(c)) throw new Error("Проверьте поля и точность: количество и суммы — 2 знака, вес — 3, объём — 4. SKU должны быть непустыми и разными.");
        attempt = { version: 1, org, principal: identity.principal, nonce: crypto.randomUUID(), body: JSON.stringify(c), mode: "create", state: "pending" };
      } else {
        if (!attempt || attempt.state !== "pending") throw new Error("Нет ожидающей попытки");
        if (action === "reconcile") attempt = { ...attempt, mode: "reconcile" };
      }
      const raw = write(org, identity.principal, saved.raw, attempt); stored.current = raw; setJournal(attempt);
      const r = await fetch(`${url(org)}${attempt.mode === "reconcile" ? "/order-commands/reconcile" : "/orders"}`, { method: "POST", cache: "no-store", headers: { "Content-Type": "application/json", "X-Expected-Principal": identity.principal }, body: attempt.body });
      const result = await r.json() as Outcome;
      if (!active(token)) return;
      const verified = ((r.status === 201 && result?.outcome === "created") || (r.status === 409 && result?.outcome === "rejected")) && await validOutcome(result, org, identity.principal, JSON.parse(attempt.body));
      if (!active(token)) return;
      if (!verified) throw new Error(`Исход не подтверждён (HTTP ${r.status}). Сохранённый ключ остаётся заблокирован.`);
      if (!(await sameUser(token))) return;
      const settled: Journal = { ...attempt, state: "settled", result };
      stored.current = write(org, identity.principal, raw, settled); setJournal(settled); setReviewing(false);
      if (result.outcome === "created") { setSupplier(""); setEvidence(""); setLines([blankLine()]); setMode(""); setBasis(null); await reload(token); if (active(token)) await loadDetail(result.order_id!, token); }
    });
  }
  function revise() {
    void run(async token => {
      if (!identity || blocked) return;
      const saved = await read(org, identity.principal);
      if (!active(token) || !(await sameUser(token))) return;
      if (sessionStorage.getItem(storageKey(org, identity.principal)) !== saved.raw || saved.raw !== stored.current || saved.value?.state !== "settled" || saved.value.result?.outcome !== "rejected") throw new Error("Отказ не подтверждён");
      const c = JSON.parse(saved.value.body) as Command;
      if (saved.value.result.code === "sku_catalog_changed") {
        const current = await fetchProcurementSkus(org, skuSearch);
        if (!active(token)) return;
        setSkuOptions(current); setSkuError("");
      }
      setSupplier(c.document.supplier); setEta(c.document.eta_date ?? ""); setFreight(c.document.freight_byn);
      setLines(c.document.lines.map(line => saved.value?.result?.code === "sku_catalog_changed"
        ? { sku_code: line.sku_code, qty: line.qty, goods_value_byn: line.goods_value_byn, weight: line.weight, volume: line.volume }
        : line)); setEvidence(c.ownership_evidence);
      setMode(c.request_basis ? "request" : "standalone"); setRequestId(c.request_basis ? String(c.request_basis.request_id) : ""); setLinkEvidence(c.request_basis?.link_evidence ?? ""); setBasis(null); setReviewing(true);
    });
  }
  const pending = journal?.state === "pending", outcome = journal?.state === "settled" ? journal.result : undefined;
  const formDisabled = busy || blocked || !identity?.can_manage || pending || (outcome?.outcome === "rejected" && !reviewing);
  return <div className="space-y-4">{error && <p role="alert">{error}</p>}{identity && !identity.can_manage && <p>Доступен просмотр. Создание и изменение требуют прав главного бухгалтера.</p>}
    {pending && <div className="space-y-2 rounded border border-amber-400 p-3"><p>Исход сохранённой попытки пока не подтверждён. Новый заказ с другим ключом запрещён.</p><Button disabled={busy || blocked || !identity?.can_manage} onClick={() => dispatch("retry")}>Повторить сохранённую попытку</Button><Button disabled={busy || blocked || !identity?.can_manage} variant="secondary" onClick={() => dispatch("reconcile")}>Проверить результат и закрыть неисполненную попытку</Button></div>}
    {outcome?.outcome === "created" && <p role="status">Создан заказ {outcome.number}. Ниже показано текущее состояние.</p>}
    {outcome?.outcome === "rejected" && <div className="space-y-2 rounded border border-line p-3"><p role="status">Подтверждён отказ без создания заказа. {codes[outcome.code!]}</p>{!reviewing && <Button disabled={busy || blocked || !identity?.can_manage} onClick={revise}>Исправить заказ и заново проверить заявку</Button>}</div>}
    <fieldset disabled={formDisabled} className="space-y-3 rounded border border-line p-4"><legend>Новый заказ</legend>
      <Select aria-label="Основание заказа" value={mode} onChange={e => { setMode(e.target.value); setBasis(null); }}><option value="">Выберите основание</option><option value="standalone">Самостоятельный заказ</option><option value="request">Из согласованной заявки</option></Select>
      {mode === "request" && <div className="space-y-2"><Select aria-label="Согласованная заявка для заказа" value={requestId} onChange={e => { setRequestId(e.target.value); setBasis(null); }}><option value="">Выберите заявку</option>{requests.filter(x => x.stage === "approval").map(x => <option key={x.id} value={x.id}>{x.number} · {x.supplier}</option>)}</Select><Button disabled={!requestId} onClick={reviewBasis}>Проверить заявку</Button>{basis && <p>Проверена заявка {basis.snapshot.request_id}: {basis.snapshot.item}, {basis.snapshot.qty}. Плановая сумма {basis.snapshot.amount}, валюта не задана. Стоимость заказа в BYN укажите отдельно.</p>}<label className="block">Основание связи с заявкой<Input value={linkEvidence} onChange={e => setLinkEvidence(e.target.value)} /></label></div>}
      <label className="block">Поставщик заказа<Input value={supplier} onChange={e => setSupplier(e.target.value)} /></label><label className="block">Ожидаемая дата<Input type="date" value={eta} onChange={e => setEta(e.target.value)} /></label><label className="block">Фрахт, BYN<Input value={freight} onChange={e => setFreight(e.target.value)} /></label><label className="block">Основание выбора юрлица заказа<Input value={evidence} onChange={e => setEvidence(e.target.value)} /></label>
      <label className="block">Поиск номенклатуры<Input value={skuSearch} onChange={e => setSkuSearch(e.target.value)} /></label>
      {skuOptions?.truncated && <p>Показаны первые 50 товаров. Уточните поиск.</p>}{skuError && <p role="alert">Справочник недоступен: {skuError}</p>}
      {lines.map((line, index) => <div className="grid gap-2 rounded border border-line p-3 md:grid-cols-5" key={index}>
        <label>Номенклатура из справочника {index + 1}<Select value={line.sku_id ?? ""} onChange={e => {
          const selected = skuOptions?.items.find(item => String(item.id) === e.target.value);
          setLines(current => current.map((item, i) => i === index ? {
            sku_code: selected?.code ?? "", sku_id: selected?.id, sku_title: selected?.title,
            sku_unit: selected?.unit, qty: item.qty, goods_value_byn: item.goods_value_byn,
            weight: item.weight, volume: item.volume,
          } : item));
        }}><option value="">Выберите товар</option>
          {line.sku_id && !skuOptions?.items.some(item => item.id === line.sku_id) && <option value={line.sku_id}>{line.sku_code} · {line.sku_title} · {line.sku_unit}</option>}
          {skuOptions?.items.map(item => <option value={item.id} key={item.id}>{item.code} · {item.title} · {item.unit}</option>)}
        </Select></label>
        {(["qty", "goods_value_byn", "weight", "volume"] as const).map(field => <label key={field}>{({ qty: "Количество", goods_value_byn: "Стоимость товара, BYN", weight: "Вес, кг", volume: "Объём, м³" })[field]} {index + 1}<Input value={line[field]} onChange={e => setLines(a => a.map((x, i) => i === index ? { ...x, [field]: e.target.value } : x))} /></label>)}
        <Button disabled={lines.length === 1} variant="secondary" onClick={() => setLines(a => a.filter((_, i) => i !== index))}>Удалить позицию {index + 1}</Button>
      </div>)}
      <Button disabled={lines.length >= 200} variant="secondary" onClick={() => setLines(a => [...a, blankLine()])}>Добавить позицию</Button><Button onClick={() => dispatch("new")}>Создать заказ</Button>
    </fieldset>
    {requestNext !== null && <Button disabled={busy} onClick={() => more("request", requestNext)}>Ещё заявки для заказа</Button>}
    <div className="space-y-2"><h2 className="font-semibold">Заказы выбранного юрлица</h2><Button disabled={busy || !identity} variant="secondary" onClick={() => void run(reload)}>Обновить заказы</Button>{orders.map(o => <div key={o.id}><Button disabled={busy} variant="secondary" onClick={() => void run(token => loadDetail(o.id, token))}>Открыть {o.number}</Button> · {o.supplier} · {o.status}</div>)}{identity && !orders.length && <p>На загруженной странице заказов нет.</p>}{orderNext !== null && <Button disabled={busy} onClick={() => more("order", orderNext)}>Ещё заказы</Button>}</div>
    {detail && <article aria-label="Состав заказа" className="space-y-2 rounded border border-line p-4"><h2>{detail.number} · {detail.supplier}</h2><Link className="underline" href={`/erp/procurement/orders/${detail.id}?org=${detail.organization_id}`}>Открыть редактор заказа</Link><p>Статус: {detail.status}. Фрахт: {detail.freight_byn} BYN. Дата: {detail.eta_date ?? "не задана"}.</p>{detail.lines.map(x => <p key={x.id}>{x.sku_code} · {x.qty} · {x.goods_value_byn} BYN · {x.weight} кг · {x.volume} м³</p>)}{detail.next_after_line_id !== null && <Button disabled={busy} onClick={() => void run(token => loadDetail(detail.id, token, detail.next_after_line_id!))}>Ещё позиции заказа</Button>}</article>}
  </div>;
}
