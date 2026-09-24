"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { Input, Select } from "@/components/ui/input";
import { fetchProcurementSuppliers, type ProcurementSupplierOption } from "@/lib/procurement-machine";
import { ProcurementReceiptPosting, type ReceiptAccount } from "./procurement-receipt-posting";

const item = () => ({ order_id: null as number | null, sku: "", unit: null as string | null, lot: "", quantity: "", net_amount: "", vat_amount: "", vat_rate: "", vat_basis: "" });
const blank = () => ({ currency: "BYN", invoice_reference: "", document_date: "", operation_date: "", supplier: "", supplier_id: null as number | null, supplier_unp: null as string | null, contract: "", warehouse: "", explanation: "", items: [item()] });
type Document = ReturnType<typeof blank>;
type Receipt = { id: number; version: number; status?: string; posting?: { entry_id: number; version: number } | null; revisions: { version: number; actor: string; created_at: string; document: Document }[] };
type OwnedOrder = { kind: string; source_id: number; snapshot: { number: string; supplier: string } };
const fields = [["invoice_reference", "Номер первичной накладной"], ["document_date", "Дата первичной накладной"], ["operation_date", "Дата поступления"], ["contract", "Договор накладной"], ["warehouse", "Склад накладной"], ["explanation", "Содержание накладной"]] as const;
const itemFields = [["sku", "Номенклатура"], ["unit", "Единица измерения"], ["lot", "Партия"], ["quantity", "Количество"], ["net_amount", "Стоимость без НДС"], ["vat_rate", "Ставка НДС %"], ["vat_amount", "Сумма НДС"], ["vat_basis", "Основание НДС"]] as const;
async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch(`/api/procurement${path}`, { cache: "no-store", ...options });
  const data = await response.json();
  if (!response.ok) throw new Error(response.status === 409 ? "Версия или ключ документа уже изменены. Обновите список и откройте актуальную накладную." : typeof data.detail === "string" ? data.detail : "Проверьте реквизиты, даты и суммы накладной.");
  return data;
}
export function ProcurementReceiptDrafts({ org, initialReceipt, accounts = [], policyId, date = "", onPosted }: { org: string; initialReceipt?: string; accounts?: ReceiptAccount[]; policyId?: number; date?: string; onPosted?: () => void }) {
  const [rows, setRows] = useState<Receipt[]>([]), [document, setDocument] = useState(blank);
  const [query, setQuery] = useState(""), [statusFilter, setStatusFilter] = useState("all");
  const [orders, setOrders] = useState<OwnedOrder[]>([]);
  const [orderError, setOrderError] = useState("");
  const [supplierSearch, setSupplierSearch] = useState("");
  const [supplierOptions, setSupplierOptions] = useState<ProcurementSupplierOption[]>([]);
  const [supplierError, setSupplierError] = useState("");
  const [selected, setSelected] = useState<Receipt | null>(null), [busy, setBusy] = useState(false);
  const [error, setError] = useState(""), [notice, setNotice] = useState(""), [reload, setReload] = useState(0);
  const [loadedKey, setLoadedKey] = useState("");
  const key = useRef<string | null>(null), active = useRef(true);
  const initialOpened = useRef(false);
  const [initialLoading, setInitialLoading] = useState(initialReceipt !== undefined);
  const path = `/organizations/${org}/receipt-documents`;
  const listKey = `${path}/${reload}`;
  const listLoaded = loadedKey === listKey;
  const dirty = selected && JSON.stringify(document) !== JSON.stringify(selected.revisions.at(-1)!.document);
  const search = query.trim().toLocaleLowerCase("ru");
  const visible = rows.filter((row) => {
    const source = row.revisions.at(-1)!.document;
    const status = row.posting ? "posted" : "draft";
    return (statusFilter === "all" || statusFilter === status)
      && (!search || [source.invoice_reference, source.supplier, source.document_date]
        .some((value) => value.toLocaleLowerCase("ru").includes(search)));
  });
  useEffect(() => { active.current = true; return () => { active.current = false; }; }, []);
  useEffect(() => {
    if (!supplierSearch.trim()) return;
    let current = true;
    const timer = window.setTimeout(() => {
      void fetchProcurementSuppliers(Number(org), supplierSearch.trim())
        .then((result) => { if (current) { setSupplierOptions(result.items); setSupplierError(""); } })
        .catch((cause: Error) => { if (current) { setSupplierOptions([]); setSupplierError(cause.message); } });
    }, 250);
    return () => { current = false; window.clearTimeout(timer); };
  }, [org, supplierSearch]);
  useEffect(() => {
    let current = true;
    void request<OwnedOrder[]>(`/organizations/${org}/purchase-ownership`).then((data) => {
      if (current) setOrders(data.filter((row) => row.kind === "order"));
    }).catch(() => { if (current) setOrderError("Не удалось загрузить подтверждённые заказы. Сохранённые связи накладной сохранены."); });
    return () => { current = false; };
  }, [org]);
  useEffect(() => {
    let current = true;
    void request<Receipt[]>(path).then((data) => { if (current) {
      setRows(data);
      setLoadedKey(listKey);
      if (initialReceipt !== undefined && !initialOpened.current) {
        initialOpened.current = true;
        setInitialLoading(false);
        const row = data.find(row => String(row.id) === initialReceipt);
        if (row) open(row);
        else setError("Накладная из ссылки не найдена в выбранном юрлице.");
      }
    } }).catch((e: Error) => { if (current) setError(e.message); });
    return () => { current = false; };
  }, [path, listKey, initialReceipt]);
  function open(row: Receipt | null) {
    setSelected(row); setDocument(row ? structuredClone(row.revisions.at(-1)!.document) : blank());
    key.current = null; setError(""); setNotice("");
  }
  async function save() {
    if (selected?.posting) return;
    if (!document.supplier_id || document.supplier_unp == null) {
      setError("Выберите поставщика накладной из справочника."); return;
    }
    key.current ??= crypto.randomUUID();
    setBusy(true); setError(""); setNotice("");
    try {
      const row = await request<Receipt>(selected ? `${path}/${selected.id}` : path, {
        method: selected ? "PUT" : "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify(selected ? { expected_version: selected.version, document } : { key: key.current, document }),
      });
      if (!active.current) return;
      setSelected(row); setDocument(structuredClone(row.revisions.at(-1)!.document));
      setRows((current) => [row, ...current.filter((item) => item.id !== row.id)]);
      setReload((value) => value + 1); setNotice(`Накладная № ${row.id}: сохранена версия ${row.version}.`);
    } catch (e) { if (active.current) setError((e as Error).message); }
    finally { if (active.current) setBusy(false); }
  }
  if (initialLoading) return <section className="space-y-3 rounded-xl border border-line bg-surface p-4"><p role="status">Загрузка накладной из ссылки…</p>{error && <><p role="alert">{error}</p><Button onClick={() => setReload(value => value + 1)}>Повторить загрузку накладной</Button></>}</section>;
  return <section className="space-y-4 rounded-xl border border-line bg-surface p-4">
    <h2 className="font-semibold">Реестр первичных накладных</h2>
    <p className="text-sm text-muted">Суммы в BYN по документу поставщика. Сохранение черновика не создаёт проводки и складские движения.</p>
    {error && <p role="alert">{error}</p>}{notice && <p role="status">{notice}</p>}
    {orderError && <p role="alert">{orderError}</p>}
    <fieldset disabled={busy} className="space-y-3">
      <div className="flex gap-2"><Button variant="secondary" onClick={() => open(null)}>Новая первичная накладная</Button><Button variant="secondary" onClick={() => setReload((v) => v + 1)}>Обновить реестр</Button></div>
      <div className="grid gap-3 md:grid-cols-2"><label>Поиск по номеру, поставщику или дате<Input aria-label="Поиск накладных" value={query} onChange={(e) => setQuery(e.target.value)} /></label><label>Статус накладной<Select aria-label="Статус накладной" value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)}><option value="all">Все</option><option value="draft">Черновики</option><option value="posted">Проведённые</option></Select></label></div>
      {!listLoaded && !error && <p role="status">Загрузка реестра накладных…</p>}
      {listLoaded && <p className="text-sm text-muted">Показано {visible.length} из {rows.length} накладных выбранного юрлица за все даты.</p>}
      {listLoaded && <ul className="divide-y divide-line">{visible.map((row) => {
        const source = row.revisions.at(-1)!.document;
        return <li key={row.id} className="flex flex-wrap items-center gap-2 py-2">
          <Button variant="secondary" onClick={() => open(row)}>{source.invoice_reference} · {source.document_date} · {source.supplier}</Button>
          <span className="text-sm">{row.posting ? "Проведена" : "Черновик"} · версия {row.version}</span>
          {row.posting && <Link className="text-sm text-accent underline" href={`/erp/procurement/receipts/posted/${row.posting.entry_id}?org=${org}`}>Открыть проведённую накладную</Link>}
        </li>;
      })}</ul>}
      {listLoaded && !visible.length && <p className="text-sm text-muted">Накладных по выбранному фильтру нет.</p>}
      {selected?.posting && <p role="status">Проведена · проводка № {selected.posting.entry_id}. Первичные данные доступны для просмотра.</p>}
      <fieldset disabled={Boolean(selected?.posting)} className="space-y-3">
      <div className="grid gap-3 md:grid-cols-3">{fields.map(([field, label]) => <label key={field}>{label}<Input type={field.endsWith("date") ? "date" : "text"} value={document[field]} onChange={(e) => setDocument({ ...document, [field]: e.target.value })} /></label>)}</div>
      <div className="grid gap-3 md:grid-cols-2"><label>Поиск поставщика<Input aria-label="Поиск поставщика накладной" maxLength={100} value={supplierSearch} onChange={(e) => { setSupplierSearch(e.target.value); setSupplierOptions([]); setSupplierError(""); setDocument((current) => ({ ...current, supplier: "", supplier_id: null, supplier_unp: null })); }} /></label><label>Поставщик накладной из справочника<Select aria-label="Поставщик накладной из справочника" value={document.supplier_id ?? ""} onChange={(e) => {
        const supplier = supplierOptions.find((option) => String(option.id) === e.target.value);
        setDocument({ ...document, supplier: supplier?.name ?? "", supplier_id: supplier?.id ?? null, supplier_unp: supplier?.unp ?? null });
      }}><option value="">Выберите поставщика</option>{document.supplier_id && !supplierOptions.some((option) => option.id === document.supplier_id) && <option value={document.supplier_id}>{document.supplier} · {document.supplier_unp || "без УНП"} (сохранённый)</option>}{supplierOptions.map((option) => <option key={option.id} value={option.id}>{option.name} · {option.unp || "без УНП"}</option>)}</Select></label></div>
      {supplierError && <p role="alert">Справочник поставщиков недоступен: {supplierError}</p>}{selected && !document.supplier_id && <p>У этой версии нет связи со справочником. Выберите поставщика перед исправлением или проведением.</p>}
      {document.items.map((row, index) => <fieldset key={index} className="rounded-lg border border-line p-3"><legend>Строка накладной {index + 1}</legend><label>Заказ поставщику<Select aria-label={`Заказ строки ${index + 1}`} value={row.order_id ?? ""} onChange={(e) => setDocument({ ...document, items: document.items.map((r, i) => i === index ? { ...r, order_id: e.target.value ? Number(e.target.value) : null } : r) })}><option value="">Без связи с заказом</option>{row.order_id && !orders.some((order) => order.source_id === row.order_id) && <option value={row.order_id}>Сохранённый заказ № {row.order_id}</option>}{orders.map((order) => <option key={order.source_id} value={order.source_id}>{order.snapshot.number || `№ ${order.source_id}`} · {order.snapshot.supplier}</option>)}</Select></label><div className="grid gap-3 md:grid-cols-4">{itemFields.map(([field, label]) => <label key={field}>{label}<Input aria-label={`${label} черновика ${index + 1}`} value={row[field] ?? ""} onChange={(e) => setDocument({ ...document, items: document.items.map((r, i) => i === index ? { ...r, [field]: field === "unit" ? e.target.value || null : e.target.value } : r) })} /></label>)}</div><Button variant="secondary" disabled={document.items.length === 1} onClick={() => setDocument({ ...document, items: document.items.filter((_, i) => i !== index) })}>Удалить строку {index + 1}</Button></fieldset>)}
      <div className="flex gap-2"><Button variant="secondary" disabled={document.items.length >= 300} onClick={() => setDocument({ ...document, items: [...document.items, item()] })}>Добавить строку накладной</Button><Button onClick={() => void save()}>{selected ? `Сохранить исправление версии ${selected.version}` : "Сохранить первичную накладную"}</Button></div>
      </fieldset>
    </fieldset>
    {selected && !selected.posting && (dirty ? <p>Сохраните изменения накладной перед расчётом проводок.</p> : !document.supplier_id ? <p>Сопоставьте поставщика со справочником перед проведением.</p> : <ProcurementReceiptPosting key={`${selected.id}/${selected.version}/${date}/${policyId}`} blocked={busy} org={org} receiptId={selected.id} version={selected.version} items={document.items} accounts={accounts} policyId={policyId} date={date} onBusy={(value) => { if (active.current) setBusy(value); }} onPosted={(entryId) => {
      if (!active.current) return;
      setSelected((current) => current?.id === selected.id ? { ...current, status: "posted", posting: { entry_id: entryId, version: selected.version } } : current);
      setRows((current) => current.map((row) => row.id === selected.id ? { ...row, status: "posted", posting: { entry_id: entryId, version: selected.version } } : row));
      setReload((value) => value + 1); onPosted?.();
    }} />)}
    {selected && !dirty && document.supplier_id && <Link className="text-accent underline" href={`/erp/wms/receipts/from-primary?org=${org}&receipt=${selected.id}&version=${selected.version}`}>Подготовить складскую приёмку</Link>}
    {selected && <details><summary>История накладной № {selected.id}</summary>{selected.revisions.map((row) => <article key={row.version} className="border-b border-line py-3"><h3>Версия {row.version} · {row.actor} · {row.created_at}</h3><dl>{fields.map(([field, label]) => <div key={field}><dt>{label}</dt><dd>{row.document[field]}</dd></div>)}<div><dt>Поставщик накладной</dt><dd>{row.document.supplier} · {row.document.supplier_unp || "УНП не указан"} · {row.document.supplier_id ? `ID ${row.document.supplier_id}` : "связь со справочником неизвестна"}</dd></div></dl>{row.document.items.map((r, i) => <p key={i}>{r.sku}{r.order_id ? ` · заказ № ${r.order_id}` : ""} · партия {r.lot} · {r.quantity} {r.unit ?? "(единица не указана)"} · без НДС {r.net_amount} BYN · НДС {r.vat_rate}% / {r.vat_amount} BYN · {r.vat_basis}</p>)}</article>)}</details>}
  </section>;
}
