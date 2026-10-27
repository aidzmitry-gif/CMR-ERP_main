"use client";

import { useEffect, useState } from "react";
import { InvoicePhysicalShipment } from "./invoice-physical-shipment";
import type { Scope } from "@/lib/invoice-physical-shipment-api";

type Invoice = { document_id: number; deal_id: number; number: string; status: string };
export function AccountingStockIssues() {
  const [organizations, setOrganizations] = useState<{ id: number; name: string }[]>([]);
  const [org, setOrg] = useState("");
  const [rows, setRows] = useState<Invoice[] | null>(null);
  const [cursor, setCursor] = useState(0);
  const [next, setNext] = useState<number | null>(null);
  const [scope, setScope] = useState<Scope | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    const abort = new AbortController();
    void fetch("/api/accounting/organizations", { cache: "no-store", signal: abort.signal })
      .then(async response => { if (!response.ok) throw new Error("Не удалось загрузить организации."); return response.json(); })
      .then(data => {
        if (!Array.isArray(data) || data.some(r => !Number.isSafeInteger(r.id) || r.id <= 0 || typeof r.name !== "string")) throw new Error("Список организаций не подтверждён.");
        if (!abort.signal.aborted) setOrganizations(data);
      }).catch(e => { if (!abort.signal.aborted) setError(String(e.message)); });
    return () => abort.abort();
  }, []);
  useEffect(() => {
    if (!org) return;
    const abort = new AbortController();
    void fetch(`/api/accounting/organizations/${org}/stock-issue-invoices?after_id=${cursor}`, { cache: "no-store", signal: abort.signal })
      .then(async response => { if (!response.ok) throw new Error("Нет доступа к документам или сервис недоступен."); return response.json(); })
      .then(data => {
        if (String(data.organization_id) !== org || !Array.isArray(data.items)
          || data.items.some((r: Invoice) => !Number.isSafeInteger(r.document_id) || r.document_id <= cursor || !Number.isSafeInteger(r.deal_id) || r.deal_id <= 0 || typeof r.number !== "string" || typeof r.status !== "string")
          || !(data.next_after_id === null || Number.isSafeInteger(data.next_after_id) && data.next_after_id > cursor)) throw new Error("Документы не соответствуют выбранной организации.");
        if (!abort.signal.aborted) { setRows(data.items); setNext(data.next_after_id); }
      }).catch(e => { if (!abort.signal.aborted) setError(String(e.message)); });
    return () => abort.abort();
  }, [org, cursor]);
  return <main className="space-y-4 p-6">
    <h1 className="text-xl font-semibold">Списание по накладной</h1>
    <p>Накладную заполняет сотрудник. Выберите организацию и исходный счёт, затем укажите оформленную накладную и фактическое количество. Режим каждого склада определяется его настройкой.</p>
    <label>Организация <select className="rounded border border-line p-2" value={org} onChange={e => { setOrg(e.target.value); setCursor(0); setRows(null); setNext(null); setScope(null); setError(""); }}>
      <option value="">Выберите организацию</option>{organizations.map(o => <option key={o.id} value={o.id}>{o.name}</option>)}
    </select></label>
    {error && <p role="alert">{error}</p>}
    {org && rows === null && !error && <p role="status">Загрузка счетов…</p>}
    {rows?.length === 0 && !error && <p>Счета с зарегистрированным складским резервом не найдены.</p>}
    {!error && rows && <ul className="space-y-2">{rows.map(row => <li key={row.document_id}><button className="text-accent underline" onClick={() => setScope({ organization_id: Number(org), deal_id: row.deal_id, document_id: row.document_id })}>Счёт {row.number || `№ ${row.document_id}`}</button> · {row.status}</li>)}</ul>}
    {next !== null && !error && <button onClick={() => { setCursor(next); setRows(null); setNext(null); setError(""); }}>Следующие счета</button>}
    {scope && <InvoicePhysicalShipment scope={scope} remainderReadOnly />}
  </main>;
}
