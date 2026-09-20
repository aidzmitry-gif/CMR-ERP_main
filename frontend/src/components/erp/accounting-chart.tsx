"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import { Input, Select } from "@/components/ui/input";
import { AccountingControls } from "./accounting-controls";

type ChartRow = { code: string; title: string; parent?: string | null; off_balance?: boolean; category?: string; valid_from?: string; required_dimensions?: string[]; currency_tracking?: boolean; quantity_tracking?: boolean };
type CatalogAmendment = { document: string; date: string; effective_from: string; status: string; impact_on_chart?: string; chart_appendix_verified?: boolean; full_text_verified?: boolean; checked_at?: string; evidence?: string; source_url?: string; source_kind?: string; review_scope?: string };
type NormativeEvidence = { document: string; url: string; source_kind: string; coverage: string; full_text_verified: boolean };
type NormativeReview = { status: string; checked_at: string; verified_through: string; source_access?: string; note?: string; blocking_reasons?: string[]; evidence?: NormativeEvidence[] };
type Catalog = { version: string; source: string; verified_through: string; current_revision_reference?: string; current_normative_verified: boolean; chart_codes_verified?: boolean; verification_note?: string; normative_review?: NormativeReview; known_amendments?: CatalogAmendment[]; accounts: ChartRow[] };
type Org = { id: number; name: string; unp: string };
const labels: Record<string, string> = { counterparty: "Контрагент", contract: "Договор", settlement_document: "Документ расчётов", warehouse: "Склад", sku: "Номенклатура", lot: "Партия", order: "Заказ", employee: "Сотрудник", asset: "Основное средство", department: "Подразделение", owner: "Владелец", serial: "Серийный номер" };
const amendmentImpact = (amendment: CatalogAmendment) => amendment.impact_on_chart === "no_chart_code_change"
  ? "номера счетов и субсчета в проверенном тексте не изменены."
  : amendment.impact_on_chart === "instruction_scope_only"
    ? "доступная область изменения касается инструкции; полный первичный текст ещё проверяется."
    : "влияние на план счетов не установлено.";
async function read<T>(path: string): Promise<T> {
  const response = await fetch(`/api/accounting${path}`, { cache: "no-store" });
  const data = await response.json();
  if (!response.ok) throw new Error(typeof data.detail === "string" ? data.detail : "Не удалось загрузить план счетов.");
  return data as T;
}

export function AccountingChart() {
  const [catalog, setCatalog] = useState<Catalog | null>(null);
  const [organizations, setOrganizations] = useState<Org[]>([]);
  const [org, setOrg] = useState("");
  const [on, setOn] = useState(new Date().toISOString().slice(0, 10));
  const [mode, setMode] = useState("catalog");
  const [query, setQuery] = useState("");
  const [working, setWorking] = useState<ChartRow[] | null>(null);
  const [error, setError] = useState("");
  const [reload, setReload] = useState(0);
  useEffect(() => {
    let active = true;
    void read<Catalog>("/catalog").then((data) => { if (active) setCatalog(data); }).catch((e: Error) => { if (active) setError(e.message); });
    void read<Org[]>("/organizations").then((data) => { if (active) { setOrganizations(data); setOrg((current) => data.some((o) => String(o.id) === current) ? current : data[0] ? String(data[0].id) : ""); } }).catch((e: Error) => { if (active) setError(e.message); });
    return () => { active = false; };
  }, [reload]);
  useEffect(() => {
    if (!org) return;
    let active = true;
    void read<ChartRow[]>(`/organizations/${org}/accounts?on=${on}`).then((data) => { if (active) { setWorking(data); setError(""); } }).catch((e: Error) => { if (active) setError(e.message); });
    return () => { active = false; };
  }, [org, on, reload]);
  const source = mode === "catalog" ? catalog?.accounts : working;
  const rows = source?.filter((row) => `${row.code} ${row.title}`.toLocaleLowerCase("ru").includes(query.trim().toLocaleLowerCase("ru"))).sort((a, b) => Number(Boolean(a.off_balance || a.category === "off_balance")) - Number(Boolean(b.off_balance || b.category === "off_balance")) || a.code.localeCompare(b.code, "ru", { numeric: true }));
  return <div className="min-w-0 w-0 flex-1 space-y-4 p-6 lg:pr-24 text-ink">
    <header className="flex flex-wrap items-start justify-between gap-3"><div><h1 className="text-2xl font-semibold">План счетов</h1><p className="mt-1 text-sm text-muted">Справочник Беларуси и рабочий план каждого юридического лица.</p></div><Link className="text-sm text-accent underline" href="/erp/accounting">Перейти в бухгалтерию</Link></header>
    {error && <p role="alert" className="rounded-xl border border-red-300 p-3 text-red-700">{error}</p>}
    <div className="flex flex-wrap gap-3">{[["catalog", "Типовой справочник"], ["working", "Рабочий план"], ["settings", "Настроить счета"]].map(([id, title]) => <Button key={id} variant={mode === id ? "primary" : "secondary"} onClick={() => setMode(id)}>{title}</Button>)}</div>
    {mode === "catalog" && catalog && <div className="rounded-xl border border-line bg-surface p-3 text-sm text-muted"><p>Основа — постановление Минфина № 50, транскрипция проверена по {catalog.verified_through}. {catalog.chart_codes_verified ? "Номера счетов и субсчета приложения 1 сверены с текущей редакцией; применение Инструкции ещё требует первичного текста изменений и политики юрлица." : "Актуальность на 2026 год требует проверки; редакция для 2026 года не подтверждена."} <a className="text-accent underline" href={catalog.source} target="_blank" rel="noreferrer">Официальный источник</a></p>{catalog.verification_note && <p className="mt-2">{catalog.verification_note}</p>}{catalog.normative_review && <><p className="mt-2">Проверка сведений: {catalog.normative_review.checked_at}; {catalog.chart_codes_verified ? "приложение 1 сверено, полный текст Инструкции ещё требуется." : "статус: требуется полный текст изменений."} Проверено до {catalog.normative_review.verified_through}.</p>{catalog.normative_review.blocking_reasons?.length ? <div className="mt-2"><b className="text-ink">До регламентированного применения нужно:</b><ul className="list-disc pl-5">{catalog.normative_review.blocking_reasons.map((reason) => <li key={reason}>{reason}</li>)}</ul></div> : null}{catalog.normative_review.evidence?.length ? <div className="mt-2"><b className="text-ink">Источники проверки:</b><ul className="list-disc pl-5">{catalog.normative_review.evidence.map((item) => <li key={item.document}><a className="text-accent underline" href={item.url} target="_blank" rel="noreferrer">{item.document}</a>: {item.coverage} {item.full_text_verified ? "Полный текст проверен." : "Полный текст не получен."}</li>)}</ul></div> : null}</>}{catalog.known_amendments?.length ? <ul className="mt-2 list-disc pl-5">{catalog.known_amendments.map((amendment) => <li key={amendment.document}><span>{amendment.document} от {amendment.date}, действует с {amendment.effective_from}: {amendmentImpact(amendment)}</span>{amendment.chart_appendix_verified && <div className="mt-1">Приложение 1 сверено в текущей консолидированной редакции.</div>}{amendment.review_scope && <div className="mt-1">Область проверки: {amendment.review_scope}</div>}{amendment.evidence && <div className="mt-1">{amendment.evidence}</div>}{amendment.source_url && <a className="mt-1 inline-block text-accent underline" href={amendment.source_url} target="_blank" rel="noreferrer">Открыть карточку источника</a>}</li>)}</ul> : null}</div>}
    {mode !== "catalog" && <div className="flex flex-wrap gap-3 rounded-xl border border-line bg-surface p-4"><label className="min-w-64 flex-1 text-sm">Юридическое лицо<Select aria-label="Юридическое лицо" value={org} onChange={(e) => { setWorking(null); setError(""); setOrg(e.target.value); }}><option value="">Выберите организацию</option>{organizations.map((o) => <option key={o.id} value={o.id}>{o.name} · {o.unp}</option>)}</Select></label><label className="text-sm">Действует на дату<Input aria-label="Дата рабочего плана" type="date" value={on} onChange={(e) => { setWorking(null); setOn(e.target.value); }} /></label></div>}
    {mode === "settings" ? <AccountingControls key={org} org={org} onChanged={() => { setWorking(null); setReload((v) => v + 1); }} /> : <>
      <Input aria-label="Поиск счетов" placeholder="Поиск по номеру или названию счёта" value={query} onChange={(e) => setQuery(e.target.value)} />
      <div className="overflow-x-auto rounded-xl border border-line bg-surface"><table className="w-full text-sm"><caption className="p-3 text-left text-muted">{mode === "catalog" ? "Синтетические счета и субсчета" : "Действующие версии рабочих счетов"} · {rows?.length ?? "…"}</caption><thead><tr>{["Счёт", "Наименование", "Вид / аналитика", ...(mode === "working" ? ["Учёт", "Действует с"] : [])].map((title) => <th key={title} className="border-b border-line p-3 text-left">{title}</th>)}</tr></thead><tbody>{rows?.map((row) => <tr key={row.code}><td className="border-b border-line p-3 font-semibold tabular-nums">{row.code}</td><td className={`border-b border-line p-3 ${row.parent || row.code.includes(".") ? "pl-8" : "font-medium"}`}>{row.title}</td><td className="border-b border-line p-3 text-muted">{row.off_balance || row.category === "off_balance" ? "Забалансовый" : row.parent || row.code.includes(".") ? "Субсчёт" : "Синтетический"}{row.required_dimensions?.length ? <div className="mt-1">{row.required_dimensions.map((d) => labels[d] || d).join(" · ")}</div> : null}</td>{mode === "working" && <><td className="border-b border-line p-3">{[row.currency_tracking && "Валютный", row.quantity_tracking && "Количественный"].filter(Boolean).join(" · ") || "Суммовой"}</td><td className="border-b border-line p-3">{row.valid_from}</td></>}</tr>)}</tbody></table>{source && !rows?.length && <p className="p-4 text-muted">{query ? "Счета не найдены." : "Рабочие счета на эту дату не настроены."}</p>}{mode === "working" && !org && <p className="p-4 text-muted">Выберите доступную организацию или создайте книгу в настройках.</p>}</div>
    </>}
  </div>;
}
