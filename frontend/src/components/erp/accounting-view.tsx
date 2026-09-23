"use client";

import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import { Input, Select } from "@/components/ui/input";
import { AccountingCurrencyFields, type CurrencyFields } from "./accounting-currency-fields";
import { downloadTrialBalance, type ExportTrial } from "./accounting-export";
import { AccountingReconciliation } from "./accounting-reconciliation";
import { AccountingInventoryIssue } from "./accounting-inventory-issue";
import { AccountingInputVat } from "./accounting-input-vat";
import { AccountingOutputVat } from "./accounting-output-vat";
import { AccountingForeignTrade } from "./accounting-foreign-trade";
import { AccountingFixedAssets } from "./accounting-fixed-assets";
import { AccountingRepairs } from "./accounting-repairs";
import { AccountingProductionCostSources } from "./accounting-production-cost-sources";
import { AccountingPayrollAccrualImport } from "./accounting-payroll-accrual-import";
import { AccountingPayrollStatutoryImport } from "./accounting-payroll-statutory-import";
import { AccountingPayrollControl } from "./accounting-payroll-control";
import { AccountingPayrollWorkpaper } from "./accounting-payroll-workpaper";
import { AccountingPayrollRuleSet } from "./accounting-payroll-rule-set";
import { AccountingStatutoryRequirements } from "./accounting-statutory-requirements";
import { AccountingBank } from "./accounting-bank";
import { AccountingBankImport } from "./accounting-bank-import";
import { AccountingSellerProfiles } from "./accounting-seller-profiles";

import { AccountingInvoiceSettlements } from "./accounting-invoice-settlements";
import { AccountingControls } from "./accounting-controls";
import { AccountingSourceLink } from "./accounting-source-link";
import { AccountingShipmentPreview } from "./accounting-shipment-preview";
import { AccountingShipmentPackage } from "./accounting-shipment-package";
import { AccountingFxRevaluation } from "./accounting-fx-revaluation";
import { ExpenseControl } from "./expense-control";
import { AccountingHome, type AccountingDestination } from "./accounting-home";
import { AccountingAccountActivity, type AccountMovement } from "./accounting-account-activity";

type Organization = { id: number; name: string; unp: string };
type Account = { id: number; code: string; title: string; cash: boolean; category: string; required_dimensions: string[]; currency_tracking: boolean; quantity_tracking: boolean };
type Policy = { id: number; effective_from: string; reference: string; normative_verified: boolean; inventory_method?: "specific" | "fifo" | "weighted_average"; currency_revaluation?: { monetary_accounts: string[]; gain_account: string; loss_account: string; gain_dimensions: Record<string, string>; loss_dimensions: Record<string, string>; reference: string; settlement_allocation?: "proportional_carrying"; settlement_rate_date?: "posting_date" } | null };
type JournalLine = CurrencyFields & { account: string; title?: string; side: "debit" | "credit"; amount: string; dimensions: Record<string, string>; cash_activity?: string };
type Posting = { source: string; source_version: number; operation: string; document_date: string; operation_date: string; posting_date: string; policy_id: number; correction_of?: number; rule_version: string; explanation: string; lines: JournalLine[] };
type Preview = { digest: string; explanation: string; lines: JournalLine[]; normative_verified: boolean };
type Trial = ExportTrial;
type Movement = AccountMovement;
type Report = { from: string; to: string; organization_id: number; status: string; pending_documents: number; review_items?: { code: string; count: number; message: string }[]; trial_balance: Trial[]; movements: Movement[]; opening_movements: Movement[]; balance: Record<string, string>; pnl: { income: string; expenses: string; profit: string }; cashflow: Record<string, string> };
type EntryDetail = { id: number; operation: string; source: string; explanation: string; posting_date: string; document_date: string; operation_date: string; created_at: string; source_version: number; rule_version: string; correction_of: number | null; lines: (CurrencyFields & { id: number; account_code: string; account_title: string; side: string; amount: string; dimensions: Record<string, string> })[] };
const organizationHint = (value: string | undefined) => value && /^[1-9]\d*$/.test(value) && Number.isSafeInteger(Number(value)) ? value : undefined;

const labels: Record<string, string> = { counterparty: "Контрагент", contract: "Договор", settlement_document: "Документ расчётов", warehouse: "Склад", sku: "Номенклатура", lot: "Партия", order: "Заказ", employee: "Сотрудник", asset: "Основное средство", department: "Подразделение", owner: "Владелец", serial: "Серийный номер" };

type AccountingSection = { id: string; label: string; pages: { id: string; label: string }[]; hiddenTabs?: string[] };
const accountingSections: AccountingSection[] = [
  { id: "workspace", label: "Рабочее место", pages: [{ id: "home", label: "Обзор" }] },
  { id: "documents", label: "Документы", pages: [
    { id: "sale", label: "Продажа товаров" }, { id: "inventory-issue", label: "Списание запасов" },
    { id: "entry", label: "Ручная операция" }, { id: "production", label: "Производство" },
    { id: "repairs", label: "Ремонты" }, { id: "fixed-assets", label: "ОС и амортизация" },
  ], hiddenTabs: ["shipment-preview"] },
  { id: "banking", label: "Банк и платежи", pages: [
    { id: "bank", label: "Банк" }, { id: "bank-import", label: "Импорт выписки" },
    { id: "invoice-settlements", label: "Оплаты счетов" },
  ] },
  { id: "payroll", label: "Зарплата", pages: [
    { id: "payroll-control", label: "Контроль зарплаты" }, { id: "payroll-workpaper", label: "Расчётный лист" },
    { id: "payroll-rules", label: "Правила расчёта" },
    { id: "payroll-accruals", label: "Начисления зарплаты" }, { id: "payroll-statutory", label: "Удержания и взносы" },
  ] },
  { id: "tax", label: "Налоги и обязательные платежи", pages: [
    { id: "input-vat", label: "Входной НДС" }, { id: "output-vat", label: "Исходящий НДС" },
    { id: "foreign-trade", label: "ВЭД" }, { id: "statutory-requirements", label: "Формы и ставки" },
  ] },
  { id: "reports", label: "Отчёты", pages: [
    { id: "reports", label: "ОСВ и отчёты" }, { id: "reconciliation", label: "Сверка ОСВ" },
    { id: "expenses", label: "Контроль расходов" },
  ] },
  { id: "closing", label: "Закрытие месяца", pages: [
    { id: "controls", label: "Управление книгой" }, { id: "accounts", label: "План счетов" },
    { id: "fx-revaluation", label: "Валюты" },
    { id: "seller-profiles", label: "Реквизиты продавца" },
  ] },
];

function salesOriginal(org: string, reference: string) {
  const match = /^sales:document:([1-9][0-9]*)$/.exec(reference);
  return match && org ? <a className="text-accent underline" href={`/api/sales/organizations/${encodeURIComponent(org)}/documents/${match[1]}/original`} target="_blank" rel="noreferrer">Оригинал документа № {match[1]}</a> : null;
}

async function request<T>(path: string, body?: unknown): Promise<T> {
  const response = await fetch(`/api/accounting${path}`, { method: body === undefined ? "GET" : "POST", headers: body === undefined ? undefined : { "Content-Type": "application/json" }, body: body === undefined ? undefined : JSON.stringify(body), cache: "no-store" });
  let data: unknown;
  try {
    data = await response.json();
  } catch {
    throw new Error(response.ok
      ? "ERP вернула некорректный ответ. Повторите загрузку."
      : "Бухгалтерия временно недоступна. Повторите загрузку.");
  }
  if (!response.ok) {
    const detail = data && typeof data === "object" && "detail" in data && typeof data.detail === "string" ? data.detail : undefined;
    throw new Error(detail ?? "Проверьте заполнение полей и права доступа.");
  }
  return data as T;
}

export function AccountingView({ suggestedOrg }: { suggestedOrg?: string }) {
  const today = new Date().toISOString().slice(0, 10);
  const [organizations, setOrganizations] = useState<Organization[]>([]);
  const [organizationRefresh, setOrganizationRefresh] = useState(0);
  const [organizationError, setOrganizationError] = useState("");
  const [org, setOrg] = useState("");
  const [start, setStart] = useState(`${today.slice(0, 7)}-01`);
  const [end, setEnd] = useState(today);
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [policies, setPolicies] = useState<Policy[]>([]);
  const [report, setReport] = useState<Report | null>(null);
  const [accountActivity, setAccountActivity] = useState<Trial | null>(null);
  const [tab, setTab] = useState("home");
  const [shipmentSource, setShipmentSource] = useState("");
  const [controlSection, setControlSection] = useState("setup");
  const [controlsBusy, setControlsBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);
  const locked = busy || controlsBusy;
  const [detail, setDetail] = useState<EntryDetail | null>(null);
  const [preview, setPreview] = useState<Preview | null>(null);
  const [prepared, setPrepared] = useState<Posting | null>(null);
  const [operationDate, setOperationDate] = useState(today);
  const [documentDate, setDocumentDate] = useState(today);
  const [economicDate, setEconomicDate] = useState(today);
  const [sourceVersion, setSourceVersion] = useState(1);
  const [correctionOf, setCorrectionOf] = useState("");
  const [source, setSource] = useState("");
  const [explanation, setExplanation] = useState("");
  const [lines, setLines] = useState<JournalLine[]>([{ account: "", side: "debit", amount: "", dimensions: {} }, { account: "", side: "credit", amount: "", dimensions: {} }]);
  const generation = useRef(0);
  const entryGeneration = useRef(0);
  const previewGeneration = useRef(0);
  const appliedSuggestedOrg = useRef<string | undefined>(undefined);

  useEffect(() => {
    let active = true;
    request<Organization[]>("/organizations").then((rows) => { if (active) { setOrganizationError(""); setOrganizations(rows); setOrg((current) => {
      if (appliedSuggestedOrg.current !== suggestedOrg) {
        appliedSuggestedOrg.current = suggestedOrg;
        const hint = organizationHint(suggestedOrg);
        if (hint && rows.some((row) => String(row.id) === hint)) return hint;
      }
      return rows.some((row) => String(row.id) === current) ? current : rows[0] ? String(rows[0].id) : "";
    }); } }).catch((e: Error) => { if (active) setOrganizationError(e.message); });
    return () => { active = false; };
  }, [organizationRefresh, suggestedOrg]);

  const refresh = useCallback(async () => {
    const token = ++generation.current;
    setReport(null); setAccountActivity(null); setAccounts([]); setPolicies([]); setDetail(null); setPreview(null); setPrepared(null); setError("");
    if (!org) return;
    setBusy(true);
    try {
      const prefix = `/organizations/${org}`;
      const [r, a, p] = await Promise.all([request<Report>(`${prefix}/reports?start=${start}&end=${end}`), request<Account[]>(`${prefix}/accounts?on=${operationDate}`), request<Policy[]>(`${prefix}/policies`)]);
      if (token === generation.current) { setReport(r); setAccounts(a); setPolicies(p); }
    } catch (e) { if (token === generation.current) setError((e as Error).message); }
    finally { if (token === generation.current) setBusy(false); }
  }, [org, start, end, operationDate]);

  useEffect(() => {
    const token = ++generation.current;
    if (!org) return;
    const prefix = `/organizations/${org}`;
    void Promise.all([request<Report>(`${prefix}/reports?start=${start}&end=${end}`), request<Account[]>(`${prefix}/accounts?on=${operationDate}`), request<Policy[]>(`${prefix}/policies`)])
      .then(([r, a, p]) => { if (token === generation.current) { setReport(r); setAccounts(a); setPolicies(p); setError(""); } })
      .catch((e: Error) => { if (token === generation.current) { setError(e.message); setReport(null); setAccountActivity(null); } });
    return () => { generation.current += 1; };
  }, [org, start, end, operationDate]);
  function invalidatePreview() { previewGeneration.current += 1; setPreview(null); setPrepared(null); }
  function changeDate(kind: "start" | "end" | "operation", value: string) {
    generation.current += 1; invalidatePreview(); setReport(null); setAccountActivity(null); setDetail(null); setNotice("");
    if (kind === "start") setStart(value);
    else if (kind === "end") setEnd(value);
    else { setAccounts([]); setPolicies([]); setOperationDate(value); }
  }
  function changeLine(index: number, patch: Partial<JournalLine>) { invalidatePreview(); setLines((current) => current.map((line, i) => i === index ? { ...line, ...patch } : line)); }

  async function prepare() {
    const policy = policies.filter((p) => p.effective_from <= operationDate).sort((a, b) => b.effective_from.localeCompare(a.effective_from))[0];
    if (!policy) { setError("Сначала утвердите учётную политику организации."); return; }
    const body: Posting = { source, source_version: sourceVersion, correction_of: correctionOf ? Number(correctionOf) : undefined, operation: "manual", document_date: documentDate, operation_date: economicDate, posting_date: operationDate, policy_id: policy.id, rule_version: "manual-v1", explanation, lines };
    const token = generation.current;
    const previewToken = previewGeneration.current;
    setBusy(true); setError(""); setNotice("");
    try { const result = await request<Preview>(`/organizations/${org}/preview`, body); if (token === generation.current && previewToken === previewGeneration.current) { setPreview(result); setPrepared(body); } }
    catch (e) { if (token === generation.current) setError((e as Error).message); }
    finally { if (token === generation.current) setBusy(false); }
  }

  async function post() {
    if (!prepared || !preview) return;
    const token = generation.current;
    setBusy(true); setError("");
    try { const result = await request<{ id: number }>(`/organizations/${org}/entries`, prepared); if (token === generation.current) { await refresh(); setNotice(`Операция № ${result.id} проведена.`); } }
    catch (e) { if (token === generation.current) setError((e as Error).message); }
    finally { setBusy(false); }
  }

  async function openEntry(id: number) {
    const token = generation.current;
    const entryToken = ++entryGeneration.current;
    setError("");
    try { const result = await request<EntryDetail>(`/organizations/${org}/entries/${id}`); if (token === generation.current && entryToken === entryGeneration.current) setDetail(result); }
    catch (e) { if (token === generation.current && entryToken === entryGeneration.current) setError((e as Error).message); }
  }

  function openWorkspace(destination: AccountingDestination) {
    if (["setup", "periods", "inbox", "import"].includes(destination)) { setControlSection(destination); setTab("controls"); }
    else setTab(destination);
  }

  const currentSection = accountingSections.find((section) =>
    section.pages.some((page) => page.id === tab) || section.hiddenTabs?.includes(tab)) ?? accountingSections[0];

  return <div className="min-w-0 w-full space-y-5 p-6 lg:pr-24 text-ink">
    <header><h1 className="text-2xl font-semibold">Бухгалтерия</h1><p className="mt-1 text-sm text-muted">Проводки и регистры по каждому юридическому лицу. Суммы в BYN.</p></header>
    {organizationError && <div role="alert" className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-red-300 bg-surface p-3 text-red-700"><span>{organizationError}</span><Button variant="secondary" onClick={() => { setOrganizationError(""); setOrganizationRefresh((value) => value + 1); }}>Повторить список организаций</Button></div>}
    {error && <div role="alert" className="rounded-xl border border-red-300 bg-surface p-3 text-red-700">{error}</div>}
    {notice && <p role="status" className="text-money">{notice}</p>}
    <div className="flex flex-wrap gap-4 rounded-xl border border-line bg-surface p-4">
      <label className="min-w-0 basis-64 flex-1 text-sm">Организация<Select className="min-w-0" aria-label="Организация" value={org} disabled={locked} onChange={(e) => { const next = e.target.value; if (next === org) return; generation.current += 1; setReport(null); setAccountActivity(null); setDetail(null); setPreview(null); setPrepared(null); setNotice(""); setLines([{ account: "", side: "debit", amount: "", dimensions: {} }, { account: "", side: "credit", amount: "", dimensions: {} }]); setOrg(next); }}><option value="">Выберите организацию</option>{organizations.map((o) => <option key={o.id} value={o.id}>{o.name} · {o.unp}</option>)}</Select></label>
      <label className="text-sm">С<Input aria-label="Начало периода" type="date" value={start} disabled={locked} onChange={(e) => changeDate("start", e.target.value)} /></label>
      <label className="text-sm">По<Input aria-label="Конец периода" type="date" value={end} disabled={locked} onChange={(e) => changeDate("end", e.target.value)} /></label>
      <Button variant="secondary" disabled={locked || !org} onClick={() => void refresh()}>Обновить</Button>
    </div>
    {!organizations.length && !organizationError && !error && <p className="rounded-xl border border-line p-5 text-muted">Нет доступных книг. Руководитель создаёт организацию и назначает доступ бухгалтеру.</p>}
    <nav aria-label="Разделы бухгалтерии" className="flex flex-wrap gap-2">{accountingSections.map((section) =>
      <Button key={section.id} disabled={locked} aria-pressed={currentSection.id === section.id} variant={currentSection.id === section.id ? "primary" : "secondary"} onClick={() => { if (section.id === "closing") setControlSection("periods"); setTab(section.pages[0].id); }}>{section.label}</Button>
    )}</nav>
    {currentSection.pages.length > 1 && <nav aria-label={`Страницы раздела ${currentSection.label}`} className="flex flex-wrap gap-2 rounded-xl border border-line bg-surface p-3">{currentSection.pages.map((page) =>
      <Button key={page.id} disabled={locked} aria-pressed={tab === page.id} variant={tab === page.id ? "primary" : "secondary"} onClick={() => setTab(page.id)}>{page.label}</Button>
    )}</nav>}
    {tab === "expenses" && <ExpenseControl org={org} onEntry={(id) => void openEntry(id)} />}
    {tab === "home" && <AccountingHome selected={!!org} pending={report?.pending_documents ?? null} onOpen={openWorkspace} />}
    {tab === "seller-profiles" && <AccountingSellerProfiles org={org} organization={organizations.find((row) => String(row.id) === org)} onBusyChange={setControlsBusy} />}
    {tab === "invoice-settlements" && <AccountingInvoiceSettlements org={org} onBusyChange={setControlsBusy} />}
    {tab === "reconciliation" && <AccountingReconciliation key={org} org={org} />}
    {tab === "input-vat" && <AccountingInputVat org={org} start={start} end={end} onEntry={(id) => void openEntry(id)} />}
    {tab === "output-vat" && <AccountingOutputVat org={org} start={start} end={end} onEntry={(id) => void openEntry(id)} />}
    {tab === "foreign-trade" && <AccountingForeignTrade org={org} start={start} end={end} onEntry={(id) => void openEntry(id)} />}
    {tab === "fx-revaluation" && <AccountingFxRevaluation org={org} month={operationDate.slice(0, 7)} date={operationDate} policy={policies.filter((p) => p.effective_from <= operationDate).sort((a, b) => b.effective_from.localeCompare(a.effective_from))[0]} disabled={locked} onEntry={(id) => void openEntry(id)} />}
    {tab === "fixed-assets" && <AccountingFixedAssets org={org} month={operationDate.slice(0, 7)} policyId={String(policies.filter((p) => p.effective_from <= operationDate).sort((a, b) => b.effective_from.localeCompare(a.effective_from))[0]?.id || "")} onEntry={(id) => void openEntry(id)} disabled={locked} />}
    {tab === "repairs" && <AccountingRepairs org={org} month={operationDate.slice(0, 7)} policyId={String(policies.filter((p) => p.effective_from <= operationDate).sort((a, b) => b.effective_from.localeCompare(a.effective_from))[0]?.id || "")} onEntry={(id) => void openEntry(id)} disabled={locked} />}
    {tab === "production" && <AccountingProductionCostSources org={org} month={operationDate.slice(0, 7)} disabled={locked} onEntry={(id) => void openEntry(id)} onLock={setControlsBusy} onChanged={() => { setOrganizationRefresh((value) => value + 1); void refresh(); }} />}
    {tab === "payroll-control" && <AccountingPayrollControl key={`${org}:${end.slice(0, 7)}`} org={org} month={end.slice(0, 7)} onEntry={(id) => void openEntry(id)} />}
    {tab === "payroll-workpaper" && <AccountingPayrollWorkpaper key={`${org}:${end.slice(0, 7)}`} org={org} month={end.slice(0, 7)} disabled={locked} onBusyChange={setControlsBusy} onOpenRules={() => setTab("payroll-rules")} />}
    {tab === "payroll-rules" && <AccountingPayrollRuleSet key={`${org}:${end.slice(0, 7)}`} org={org} month={end.slice(0, 7)} policies={policies} disabled={locked} onBusyChange={setControlsBusy} onOpenRates={() => setTab("statutory-requirements")} />}
    {tab === "payroll-accruals" && <AccountingPayrollAccrualImport org={org} month={operationDate.slice(0, 7)} policyId={String(policies.filter((p) => p.effective_from <= operationDate).sort((a, b) => b.effective_from.localeCompare(a.effective_from))[0]?.id || "")} disabled={locked} onEntry={(id) => void openEntry(id)} onLock={setControlsBusy} />}
    {tab === "payroll-statutory" && <AccountingPayrollStatutoryImport org={org} month={operationDate.slice(0, 7)} policyId={String(policies.filter((p) => p.effective_from <= operationDate).sort((a, b) => b.effective_from.localeCompare(a.effective_from))[0]?.id || "")} disabled={locked} onEntry={(id) => void openEntry(id)} onLock={setControlsBusy} />}
    {tab === "statutory-requirements" && <AccountingStatutoryRequirements org={org} month={operationDate.slice(0, 7)} disabled={locked} onBusyChange={setControlsBusy} />}
    {(tab === "inventory-issue" || tab === "sale") && <AccountingInventoryIssue sale={tab === "sale"} key={`${org}/${tab}`} org={org} accounts={accounts} policyId={policies.filter((p) => p.effective_from <= operationDate).sort((a, b) => b.effective_from.localeCompare(a.effective_from))[0]?.id} inventoryMethod={policies.filter((p) => p.effective_from <= operationDate).sort((a, b) => b.effective_from.localeCompare(a.effective_from))[0]?.inventory_method} date={operationDate} onDate={(value) => changeDate("operation", value)} onBusyChange={setControlsBusy} onPosted={() => void refresh()} onEntry={(id) => void openEntry(id)} />}
    {tab === "bank" && <AccountingBank key={org} org={org} accounts={accounts} policyId={policies.filter((p) => p.effective_from <= operationDate).sort((a, b) => b.effective_from.localeCompare(a.effective_from))[0]?.id} date={operationDate} onDate={(value) => changeDate("operation", value)} onPosted={() => void refresh()} />}
    {tab === "bank-import" && <AccountingBankImport key={org} org={org} accounts={accounts} policyId={policies.filter((p) => p.effective_from <= operationDate).sort((a, b) => b.effective_from.localeCompare(a.effective_from))[0]?.id} date={operationDate} onDate={(value) => changeDate("operation", value)} onPosted={() => void refresh()} onEntry={(id) => void openEntry(id)} />}
    {tab === "shipment-preview" && <AccountingShipmentPreview key={`${org}/${shipmentSource}`} org={org} source={shipmentSource} accounts={accounts} date={operationDate} policyId={policies.filter((p) => p.effective_from <= operationDate).sort((a, b) => b.effective_from.localeCompare(a.effective_from))[0]?.id} disabled={locked} onDate={(value) => changeDate("operation", value)} onPosted={async () => { setNotice("Отгрузка проведена."); await refresh(); }} />}
    {tab === "controls" && <AccountingControls onEntry={id => void openEntry(id)} onShipment={(source) => { setShipmentSource(source); setTab("shipment-preview"); }} key={`${org}/${controlSection}`} org={org} initialSection={controlSection} onBusyChange={setControlsBusy} onChanged={() => { setOrganizationRefresh((v) => v + 1); void refresh(); }} />}
    {busy && <p role="status">Загрузка…</p>}
    {report && tab === "reports" && <>
      <nav aria-label="Отчёты бухгалтерской книги" className="flex flex-wrap gap-3 rounded-xl border border-line bg-surface p-4 text-sm">
        <span className="font-semibold">ОСВ и журнал — открыты здесь</span>
        <Link className="text-accent underline" href="/erp/finance?tab=pnl">Прибыль и убытки</Link>
        <Link className="text-accent underline" href="/erp/finance?tab=dds">Движение денег</Link>
        <Link className="text-accent underline" href="/erp/finance?tab=balance">Баланс</Link>
        <p className="w-full text-muted">Финансовые отчёты строятся по этой же бухгалтерской книге. На открывшейся странице выберите юрлицо и период заново.</p>
      </nav>
      <Button variant="secondary" onClick={() => { try { downloadTrialBalance(report); } catch (e) { setError((e as Error).message); } }}>Скачать ОСВ CSV</Button>
      <p className="text-xs text-muted">CSV содержит показанный отчёт, валютные суммы и количества. При импорте в Excel задайте счетам текстовый формат, суммам — десятичную точку. Сальдо со знаком: плюс — дебет, минус — кредит. Строка report содержит параметры выгрузки; balance — остатки и обороты.</p>
      <p className="text-sm text-muted">{report.status === "closed_periods" ? "Периоды закрыты" : "Предварительные данные"} · Не проведено документов: {report.pending_documents}. Регламентированная отчётность требует отдельной проверки.</p>
      {!!report.review_items?.length && <div role="status" className="rounded-xl border border-amber-300 bg-surface p-3 text-sm"><p className="font-semibold">Отчёт нельзя считать окончательным</p><ul className="mt-1 list-disc pl-5">{report.review_items.map((item) => <li key={item.code}>{item.message} ({item.count})</li>)}</ul></div>}
      <div className="grid gap-3 md:grid-cols-4">{[["Прибыль", report.pnl.profit], ["Деньги на конец", report.cashflow.closing], ["Капитал", report.balance.equity], ["Расхождение баланса", report.balance.difference]].map(([label, value]) => <section key={label} className="rounded-xl border border-line bg-surface p-4"><h2 className="text-sm text-muted">{label}</h2><p className="mt-2 text-xl font-semibold tabular-nums">{value} BYN</p></section>)}</div>
      <div className="overflow-x-auto rounded-xl border border-line bg-surface"><table className="w-full text-sm"><caption className="p-3 text-left font-semibold">Оборотно-сальдовая ведомость</caption><thead><tr>{["Счёт / аналитика", "Валюта", "Начальное сальдо", "Дебет", "Кредит", "Конечное сальдо"].map((x) => <th key={x} className="border-b border-line p-3 text-left">{x}</th>)}</tr></thead><tbody>{report.trial_balance.map((row, i) => <tr key={i}><td className="border-b border-line p-3"><button className="text-accent underline" onClick={() => setAccountActivity(row)} aria-label={`Обороты ${row.account} ${Object.values(row.dimensions).join(" ")} ${row.currency}`}>{row.account} · {row.title}</button>{row.off_balance && " (забалансовый)"}<div className="text-xs text-muted">{Object.entries(row.dimensions).map(([k, v]) => `${labels[k] || k}: ${v}`).join(" · ")}</div></td><td className="p-3">{row.currency}</td>{[row.opening, row.debit, row.credit, row.closing].map((v, j) => <td key={j} className="p-3 text-right tabular-nums">{v}</td>)}</tr>)}</tbody></table>{!report.trial_balance.length && <p className="p-4 text-muted">За выбранный период нет проводок.</p>}</div>
      {accountActivity && <AccountingAccountActivity row={accountActivity} movements={report.movements} openingMovements={report.opening_movements} onEntry={(id) => void openEntry(id)} onClose={() => setAccountActivity(null)} />}
      <section className="rounded-xl border border-line bg-surface p-4"><h2 className="mb-3 font-semibold">Проводки за период</h2>{report.movements.map((m, i) => <div key={i} className="flex flex-wrap items-center justify-between gap-3 border-b border-line py-2 text-sm"><button className="text-accent underline" onClick={() => void openEntry(m.entry_id)}>№ {m.entry_id} · {m.source}</button><span>{m.date} · {m.side === "debit" ? "Дт" : "Кт"} {m.account}</span><span className="tabular-nums">{m.amount} BYN</span></div>)}</section>
    </>}
    {tab === "accounts" && <section className="rounded-xl border border-line bg-surface p-4"><h2 className="font-semibold">Рабочий план счетов</h2><p className="my-2 text-sm text-muted">Действует на {operationDate}. Настройки и версии утверждает главный бухгалтер.</p>{accounts.map((a) => <div key={a.id} className="border-b border-line py-3"><span className="font-semibold">{a.code}</span> · {a.title}<p className="text-xs text-muted">{a.required_dimensions.map((d) => labels[d] || d).join(" · ") || "Без обязательной аналитики"}</p></div>)}{!accounts.length && <p className="py-4 text-muted">Рабочий план счетов ещё не настроен.</p>}</section>}
    {tab === "entry" && <section className="space-y-4 rounded-xl border border-line bg-surface p-4"><h2 className="font-semibold">Бухгалтерская справка</h2><div className="grid gap-3 md:grid-cols-3"><label>Основание<Input aria-label="Основание" value={source} disabled={locked} onChange={(e) => { invalidatePreview(); setSource(e.target.value); }} placeholder="Номер документа" /></label><label>Дата отражения<Input aria-label="Дата операции" type="date" value={operationDate} disabled={locked} onChange={(e) => changeDate("operation", e.target.value)} /></label><label>Содержание<Input aria-label="Содержание" value={explanation} disabled={locked} onChange={(e) => { invalidatePreview(); setExplanation(e.target.value); }} /></label></div>
      <div className="grid gap-3 md:grid-cols-4"><label className="text-sm">Дата документа<Input aria-label="Дата документа" type="date" value={documentDate} disabled={locked} onChange={(e) => { invalidatePreview(); setDocumentDate(e.target.value); }} /></label><label className="text-sm">Дата хозяйственной операции<Input aria-label="Дата хозяйственной операции" type="date" value={economicDate} disabled={locked} onChange={(e) => { invalidatePreview(); setEconomicDate(e.target.value); }} /></label><label className="text-sm">Версия документа<Input aria-label="Версия документа" type="number" min="1" step="1" value={sourceVersion} disabled={locked} onChange={(e) => { invalidatePreview(); setSourceVersion(Number(e.target.value)); }} /></label><label className="text-sm">Исправляет операцию №<Input aria-label="Исправляет операцию" type="number" min="1" step="1" value={correctionOf} disabled={locked} onChange={(e) => { invalidatePreview(); setCorrectionOf(e.target.value); }} placeholder="Если это исправление" /></label></div>
      {lines.map((line, i) => <fieldset key={i} disabled={locked} className="space-y-2 rounded-lg border border-line p-3"><legend className="text-sm">Строка {i + 1}</legend><div className="grid gap-3 md:grid-cols-3"><Select aria-label={`Сторона ${i + 1}`} value={line.side} onChange={(e) => changeLine(i, { side: e.target.value as "debit" | "credit" })}><option value="debit">Дебет</option><option value="credit">Кредит</option></Select><Select aria-label={`Счёт ${i + 1}`} value={line.account} onChange={(e) => changeLine(i, { account: e.target.value, dimensions: {}, cash_activity: undefined, currency: "BYN", original_amount: undefined, rate: undefined, rate_scale: undefined, rate_date: undefined, rate_source: undefined, quantity: undefined })}><option value="">Выберите счёт</option>{accounts.map((a) => <option key={a.id} value={a.code}>{a.code} · {a.title}</option>)}</Select><Input aria-label={`Сумма ${i + 1}`} inputMode="decimal" value={line.amount} placeholder="0.00 BYN" onChange={(e) => changeLine(i, { amount: e.target.value })} /></div>{accounts.find((a) => a.code === line.account)?.required_dimensions.map((dimension) => <label key={dimension} className="block text-sm">{labels[dimension] || dimension}<Input value={line.dimensions[dimension] || ""} onChange={(e) => changeLine(i, { dimensions: { ...line.dimensions, [dimension]: e.target.value } })} /></label>)}{accounts.find((a) => a.code === line.account)?.cash && <label className="block text-sm">Вид денежного потока<Select value={line.cash_activity || ""} onChange={(e) => changeLine(i, { cash_activity: e.target.value })}><option value="">Выберите вид</option><option value="operating">Текущая деятельность</option><option value="investing">Инвестиционная</option><option value="financing">Финансовая</option><option value="internal">Внутреннее перемещение</option></Select></label>}<AccountingCurrencyFields value={line} currency={accounts.find((a) => a.code === line.account)?.currency_tracking ?? false} quantity={accounts.find((a) => a.code === line.account)?.quantity_tracking ?? false} onChange={(patch) => changeLine(i, patch)} /></fieldset>)}
      <div className="flex flex-wrap gap-2"><Button variant="secondary" disabled={locked} onClick={() => { invalidatePreview(); setLines([...lines, { account: "", side: "debit", amount: "", dimensions: {} }]); }}>Добавить строку</Button><Button disabled={locked || !org || !source || !explanation} onClick={() => void prepare()}>Проверить проводки</Button></div>
      {preview && <div className="rounded-xl border border-accent p-4"><h3 className="font-semibold">Проверенные проводки</h3><p className="my-2">{preview.explanation}</p>{preview.lines.map((line, i) => <p key={i}>{line.side === "debit" ? "Дт" : "Кт"} {line.account} · {line.title} — {line.amount} BYN</p>)}{!preview.normative_verified && <p className="my-2 text-sm text-muted">Нормативная база не подтверждена: закрытие периода будет недоступно.</p>}<Button className="mt-3" disabled={locked} onClick={() => void post()}>Подтвердить и провести</Button></div>}
    </section>}
    {detail && <section aria-label="Карточка проводки" className="min-w-0 break-words rounded-xl border border-accent bg-surface p-4">
      <div className="flex flex-wrap justify-between gap-2"><h2 className="font-semibold">Операция № {detail.id}</h2><Button variant="ghost" onClick={() => { entryGeneration.current += 1; setDetail(null); }}>Закрыть карточку</Button></div>
      <p>{detail.source}</p>
      {salesOriginal(org, detail.source)}
      <AccountingSourceLink org={org} source={detail.source} />
      {detail.source.startsWith(`wms:physical-shipment:${org}:`) && <AccountingShipmentPackage key={`${org}/${detail.id}`} org={org} entryId={detail.id} onEntry={(id) => void openEntry(id)} />}
      <dl className="my-3 grid gap-3 text-sm sm:grid-cols-2 lg:grid-cols-3">{[
        ["Дата документа", detail.document_date], ["Дата хозяйственной операции", detail.operation_date],
        ["Дата отражения", detail.posting_date], ["Время регистрации (как сохранено)", detail.created_at],
        ["Версия документа", detail.source_version], ["Версия правила", detail.rule_version],
      ].map(([label, value]) => <div key={label}><dt className="text-muted">{label}</dt><dd>{value ?? "Не получено"}</dd></div>)}</dl>
      {detail.correction_of != null && <button className="text-accent underline" onClick={() => void openEntry(detail.correction_of!)}>Исправляет операцию № {detail.correction_of}</button>}
      <p className="my-2 text-muted">{detail.explanation}</p>
      {detail.lines.map((line) => <div key={line.id} className="border-t border-line py-3">
        <p>{line.side === "debit" ? "Дт" : "Кт"} {line.account_code} · {line.account_title} — {line.amount} BYN</p>
        <dl className="mt-2 grid gap-2 text-sm sm:grid-cols-2">{Object.entries(line.dimensions ?? {}).map(([key, value]) => <div key={key}><dt className="text-muted">{key === "bank_statement" ? "Банковская выписка" : labels[key] || key}</dt><dd>{key === "settlement_document" ? salesOriginal(org, value) ?? value : value}</dd></div>)}</dl>
        {line.quantity != null && <p className="text-sm">Количество: {line.quantity}</p>}
        {line.currency && line.currency !== "BYN" && <div className="mt-2 text-sm">
          <p>Сумма в валюте: {line.original_amount ?? "Не получено"} {line.currency}</p>
          <p>Курс: {line.rate ?? "Не получено"} BYN за {line.rate_scale ?? "Не получено"} {line.currency}</p>
          <p>Дата курса: {line.rate_date ?? "Не получено"} · Источник: {line.rate_source ?? "Не получено"}</p>
        </div>}
      </div>)}
    </section>}
  </div>;
}
