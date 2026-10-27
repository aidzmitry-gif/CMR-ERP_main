"use client";
import { useEffect, useState } from "react";
import { Input, Select } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import Link from "next/link";
import { statusLabel } from "@/lib/procurement-orders";
const stages: Record<string, string> = { need: "Потребность", sourcing: "Поиск поставщиков", nego: "Переговоры", analysis: "Анализ поставщика", approval: "Согласование", po: "Заказ / PO", supply: "Производство", qc: "Приёмка / QC", done: "Завершено" };

type Company = { id: number; name: string; unp: string };
type Row = { id: number; number: string; supplier: string; status?: string; stage?: string; item?: string; quantity?: string; planned_amount?: string; due_date?: string; eta_date?: string; freight_byn?: string; lines?: { id: number; sku: string; quantity: string; goods_value_byn: string }[] };
type Page = { items: Row[]; next_after_id: number | null };
async function read<T>(url: string): Promise<T> {
  const response = await fetch(url, { cache: "no-store" });
  if (!response.ok) throw new Error(response.status === 403 ? "Нет доступа к документам выбранного юрлица." : "Не удалось загрузить документы. Повторите запрос.");
  return await response.json() as T;
}
function CompanyList({ org, kind }: { org: string; kind: string }) {
  const [refresh, setRefresh] = useState(0);
  const [query, setQuery] = useState(""), [search, setSearch] = useState("");
  const [after, setAfter] = useState(0), [page, setPage] = useState<Page | null>(null), [error, setError] = useState("");
  useEffect(() => {
    let active = true;
    void read<Page>(`/api/procurement/organizations/${org}/owned-sources?kind=${kind}&after_id=${after}&q=${encodeURIComponent(search)}`).then((data) => { if (active) setPage(data); }).catch((e: Error) => { if (active) setError(e.message); });
    return () => { active = false; };
  }, [org, kind, search, after, refresh]);
  return <section className="space-y-3"><div className="flex gap-3"><Input aria-label="Поиск документов юрлица" placeholder="Номер, поставщик или товар" value={query} maxLength={200} onChange={(e) => setQuery(e.target.value)} /><Button onClick={() => { setPage(null); setError(""); setAfter(0); setSearch(query); setRefresh((value) => value + 1); }}>Найти</Button></div>
    {error && <p role="alert">{error}</p>}{!page && !error && <p role="status">Загрузка документов…</p>}
    {page?.items.map((row) => <article key={row.id} className="space-y-2 rounded-xl border border-line bg-surface p-4"><h2 className="font-semibold">{row.number || `№ ${row.id}`} · {row.supplier}</h2>{kind === "order" ? <><p>Статус: {statusLabel(row.status || "")} · Ожидается: {row.eta_date || "не указано"}</p><p>Плановый фрахт: {row.freight_byn} BYN</p><ul>{row.lines?.map((line) => <li key={line.id}>{line.sku} · количество {line.quantity} · стоимость {line.goods_value_byn} BYN</li>)}</ul>{!row.lines?.length && <p>Строки заказа не заполнены.</p>}</> : <><p>{row.item} · количество {row.quantity} · плановая сумма {row.planned_amount} (валюта не задана)</p><p>Срок: {row.due_date || "не указан"} · стадия: {stages[row.stage || ""] || row.stage}</p></>}</article>)}
    {page && !page.items.length && <p>Подтверждённых документов по этому запросу нет.</p>}
    <div className="flex gap-3">{after > 0 && <Button variant="secondary" onClick={() => { setPage(null); setError(""); setAfter(0); }}>В начало списка</Button>}{page?.next_after_id != null && <Button variant="secondary" onClick={() => { setAfter(page.next_after_id!); setPage(null); setError(""); }}>Следующие документы</Button>}</div>
  </section>;
}
export function ProcurementCompanyDocuments() {
  const [companies, setCompanies] = useState<Company[]>([]), [org, setOrg] = useState(""), [kind, setKind] = useState("order"), [error, setError] = useState("");
  useEffect(() => { let active = true; void read<Company[]>("/api/procurement/receipt-organizations").then((data) => { if (active) setCompanies(data); }).catch((e: Error) => { if (active) setError(e.message); }); return () => { active = false; }; }, []);
  return <main className="w-full space-y-4 overflow-auto p-6 lg:pr-24"><h1 className="text-2xl font-semibold">Документы закупок по юрлицу</h1><p>Текущие заявки и заказы с подтверждённым владельцем. Это оперативный список, суммы не являются бухгалтерскими расходами.</p><div className="flex flex-wrap gap-3"><label>Юрлицо документов<Select value={org} onChange={(e) => setOrg(e.target.value)}><option value="">Выберите юрлицо</option>{companies.map((company) => <option key={company.id} value={company.id}>{company.name} · {company.unp}</option>)}</Select></label><label>Вид документов<Select value={kind} onChange={(e) => setKind(e.target.value)}><option value="order">Заказы поставщикам</option><option value="request">Заявки плана закупок</option></Select></label></div>{error && <p role="alert">{error}</p>}{org && <CompanyList key={`${org}/${kind}`} org={org} kind={kind} />}<Link className="text-accent underline" href="/erp/procurement/ownership">Сопоставить документы с юрлицами и связать заявки с заказами</Link></main>;
}
