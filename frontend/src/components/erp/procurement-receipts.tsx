"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { Input, Select } from "@/components/ui/input";

import { ProcurementReceiptDrafts } from "./procurement-receipt-drafts";

type Organization = { id: number; name: string; unp: string };
type Account = { code: string; title: string; category: string; cash: boolean; quantity_tracking: boolean };
type Policy = { id: number; effective_from: string };
type Entry = { id: number; source: string; source_version: number; document_date: string; posting_date: string; operation: string; explanation: string };
async function get<T>(path: string): Promise<T> {
  const response = await fetch(`/api/accounting${path}`, { cache: "no-store" });
  const data = await response.json();
  if (!response.ok) throw new Error(typeof data.detail === "string" ? data.detail : "Не удалось загрузить поступления.");
  return data as T;
}
export function ProcurementReceipts({ initialOrganization, initialReceipt }: { initialOrganization?: string; initialReceipt?: string } = {}) {
  const [organizations, setOrganizations] = useState<Organization[]>([]), [org, setOrg] = useState("");
  const [date, setDate] = useState(new Date().toISOString().slice(0, 10));
  const [generation, setGeneration] = useState(0), [error, setError] = useState("");
  const [loaded, setLoaded] = useState<{ key: string; accounts: Account[]; policies: Policy[]; entries: Entry[] } | null>(null);
  useEffect(() => {
    let active = true;
    void fetch("/api/procurement/receipt-organizations", { cache: "no-store" }).then(async (response) => {
      if (!response.ok) throw new Error("Не удалось загрузить организации закупок.");
      return await response.json() as Organization[];
    }).then((rows) => { if (active) {
      setOrganizations(rows);
      if (initialOrganization !== undefined) {
        const found = rows.find(row => String(row.id) === initialOrganization);
        setOrg(found ? String(found.id) : "");
        if (!found) setError("Юрлицо из ссылки недоступно. Выберите организацию с подтверждённым доступом.");
      } else setOrg(rows[0] ? String(rows[0].id) : "");
    } }).catch((e: Error) => { if (active) setError(e.message); });
    return () => { active = false; };
  }, [initialOrganization]);
  const key = `${org}/${date}/${generation}`;
  useEffect(() => {
    if (!org) return;
    let active = true;
    const prefix = `/organizations/${org}`;
    void Promise.all([get<Account[]>(`${prefix}/accounts?on=${date}`), get<Policy[]>(`${prefix}/policies`), get<Entry[]>(`${prefix}/entries?start=${date.slice(0, 7)}-01&end=${date}`)])
      .then(([accounts, policies, entries]) => { if (active) { setLoaded({ key, accounts, policies, entries }); setError(""); } })
      .catch((e: Error) => { if (active) { setError(e.message); setLoaded(null); } });
    return () => { active = false; };
  }, [org, date, key]);
  const current = loaded?.key === key ? loaded : null;
  const policy = current?.policies.filter((p) => p.effective_from <= date).sort((a, b) => b.effective_from.localeCompare(a.effective_from))[0];
  return <main className="min-w-0 w-0 flex-1 space-y-4 overflow-auto p-6 lg:pr-24">
    <h1 className="text-2xl font-semibold">Накладные на поступление</h1>
    <div className="grid gap-3 rounded-xl border border-line bg-surface p-4 md:grid-cols-2">
      <label>Юрлицо поступления<Select aria-label="Юрлицо поступления" value={org} onChange={(e) => setOrg(e.target.value)}><option value="">Выберите организацию</option>{organizations.map((row) => <option key={row.id} value={row.id}>{row.name} · {row.unp}</option>)}</Select></label>
      <label>Дата отражения<Input aria-label="Дата отражения" type="date" value={date} onChange={(e) => setDate(e.target.value)} /></label>
    </div>
    {error && <p role="alert" className="text-red-700">{error}</p>}
    {org && <ProcurementReceiptDrafts key={`draft:${org}`} org={org} initialReceipt={org === initialOrganization ? initialReceipt : undefined} accounts={current?.accounts ?? []} policyId={policy?.id} date={date} onPosted={() => setGeneration((v) => v + 1)} />}
    {org && !current && !error && <p role="status">Загрузка поступлений…</p>}
    {current && <section className="rounded-xl border border-line bg-surface p-4"><h2 className="font-semibold">Проведённые поступления с начала месяца по {date}</h2>
      <ul className="divide-y divide-line">{current.entries.filter((entry) => entry.operation === "inventory_purchase").map((entry) => <li key={entry.id} className="py-3">{entry.document_date} · {entry.source} · версия {entry.source_version}<p className="text-sm text-muted">{entry.explanation} · проводка № {entry.id}</p></li>)}</ul>
      {!current.entries.some((entry) => entry.operation === "inventory_purchase") && <p className="py-3 text-sm text-muted">За выбранный период проведённых поступлений нет.</p>}
      <Link className="text-sm text-accent underline" href="/erp/accounting">Открыть бухгалтерские проводки и отчёты</Link>
    </section>}
  </main>;
}
