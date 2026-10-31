"use client";

import { useInstanceOrganization,withInstanceOrganization } from "@/components/instance-organization-gate";

import { businessDate } from "@/lib/business-date";

import Link from "next/link";
import { useEffect,useState } from "react";

import { Input } from "@/components/ui/input";

import { ProcurementReceiptDrafts } from "./procurement-receipt-drafts";
import { ProcurementUnlinkedPurchases } from "./procurement-unlinked-purchases";
import styles from "./procurement-receipts.module.css";

type Account = { code: string; title: string; category: string; cash: boolean; quantity_tracking: boolean };
type Policy = { id: number; effective_from: string };
type Entry = { id: number; source: string; source_version: number; document_date: string; posting_date: string; operation: string; explanation: string };
async function get<T>(path: string): Promise<T> {
  let response: Response;
  try { response = await fetch(`/api/accounting${path}`, { cache: "no-store" }); }
  catch { throw new Error("Не удалось загрузить поступления. Проверьте соединение с сервером."); }
  if (!response.ok) throw new Error(response.status === 403
    ? "Нет доступа к бухгалтерским поступлениям этого юрлица."
    : "Не удалось загрузить поступления.");
  let data: unknown;
  try { data = await response.json(); }
  catch { throw new Error("Ответ со списком поступлений не подтверждён."); }
  if (!Array.isArray(data)) throw new Error("Ответ со списком поступлений не подтверждён.");
  return data as T;
}

 function ProcurementReceiptsWorkspace({ initialOrganization, initialReceipt }: { initialOrganization?: string; initialReceipt?: string } = {}) {
  const org = String(useInstanceOrganization().id);
  const [, setPendingDocument] = useState(false);
  const [date, setDate] = useState(businessDate());
  const [generation, setGeneration] = useState(0), [error, setError] = useState("");
  const [loaded, setLoaded] = useState<{ key: string; accounts: Account[]; policies: Policy[]; entries: Entry[] } | null>(null);

  const foreignLink = initialOrganization !== undefined && initialOrganization !== org;
  const key = `${org}/${date}/${generation}`;
  useEffect(() => {
    if (!org || foreignLink) return;
    let active = true;
    const prefix = `/organizations/${org}`;
    void Promise.all([get<Account[]>(`${prefix}/accounts?on=${date}`), get<Policy[]>(`${prefix}/policies`), get<Entry[]>(`${prefix}/entries?start=${date.slice(0, 7)}-01&end=${date}`)])
      .then(([accounts, policies, entries]) => { if (active) { setLoaded({ key, accounts, policies, entries }); setError(""); } })
      .catch((e: Error) => { if (active) { setError(e.message); setLoaded(null); } });
    return () => { active = false; };
  }, [org, date, key, foreignLink]);
  const current = loaded?.key === key ? loaded : null;
  const policy = current?.policies.filter((p) => p.effective_from <= date).sort((a, b) => b.effective_from.localeCompare(a.effective_from))[0];
  if (foreignLink) return <p role="alert">Юрлицо ссылки не совпадает с настройкой установки.</p>;
  return <main className={`${styles.workspace} space-y-5 text-ink`}>
    <header className="space-y-2">
      <p className="text-xs font-semibold uppercase tracking-widest text-muted">Закупки · первичные документы</p>
      <h1 className="text-2xl font-semibold tracking-tight">Накладные на поступление</h1>
      <p className="max-w-3xl text-sm leading-relaxed text-muted">Реестр накладных поставщиков и сверка проведённых поступлений.</p>
    </header>
    <div className="flex flex-wrap items-center justify-between gap-4 rounded-2xl border border-line bg-surface p-4">
      <span className="text-sm text-muted">Юрлицо задано в настройках.</span>
      <label className="w-full sm:w-64">Дата отражения<Input aria-label="Дата отражения" type="date" value={date} onChange={(e) => setDate(e.target.value)} /></label>
    </div>
    {error && <p role="alert" className="rounded-xl border border-amber-300 bg-amber-50 p-4 text-sm leading-relaxed text-amber-900 dark:border-amber-500/40 dark:bg-amber-500/10 dark:text-amber-200">{error}</p>}
    {!org && !error && <p>Выберите юрлицо перед просмотром или созданием накладной.</p>}
    {org && <ProcurementReceiptDrafts key={`draft:${org}`} org={org} initialReceipt={org === initialOrganization ? initialReceipt : undefined} accounts={current?.accounts ?? []} policyId={policy?.id} date={date} onPosted={() => setGeneration((v) => v + 1)} onPendingChange={setPendingDocument} />}
    {org && <ProcurementUnlinkedPurchases key={`unlinked:${org}:${generation}`} org={org} />}
    {org && !current && !error && <p role="status">Загрузка поступлений…</p>}
    {current && <section className="rounded-xl border border-line bg-surface p-4"><h2 className="font-semibold">Проведённые поступления с начала месяца по {date}</h2>
      <ul className="divide-y divide-line">{current.entries.filter((entry) => entry.operation === "inventory_purchase").map((entry) => <li key={entry.id} className="py-3">{entry.document_date} · {entry.source} · версия {entry.source_version}<p className="text-sm text-muted">{entry.explanation} · проводка № {entry.id}</p></li>)}</ul>
      {!current.entries.some((entry) => entry.operation === "inventory_purchase") && <p className="py-3 text-sm text-muted">За выбранный период проведённых поступлений нет.</p>}
      <Link className="text-sm text-accent underline" href="/erp/accounting">Открыть бухгалтерские проводки и отчёты</Link>
    </section>}
  </main>;
}

export const ProcurementReceipts = withInstanceOrganization<{ initialOrganization?: string; initialReceipt?: string }>(ProcurementReceiptsWorkspace);
