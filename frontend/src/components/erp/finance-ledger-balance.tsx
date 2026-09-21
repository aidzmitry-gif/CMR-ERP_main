"use client";

import { useEffect, useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import { Input, Select } from "@/components/ui/input";

type Organization = { id: number; name: string; unp: string };
type Applied = { org: string; start: string; end: string };
type Category = "asset" | "liability" | "equity" | "income" | "expense";
type PeriodBucket = "opening" | "movement";
type Balance = { assets: string; liabilities: string; equity: string; current_result: string; difference: string };
type Movement = {
  entry_id: number; source: string; date: string; account: string; title: string; line_id: number;
  currency: string; ledger_currency?: string; valuation_only?: boolean; side: "debit" | "credit";
  amount: string; dimensions: Record<string, string>; category: Category; period_bucket: PeriodBucket;
};
type ReviewItem = { code: string; count: number; message: string };
type Report = {
  organization_id: number; from: string; to: string; status: string; pending_documents: number;
  review_items?: ReviewItem[]; balance: Balance; balance_movements: Movement[];
};
type EntryDetail = {
  id: number; source: string; operation: string; posting_date: string; explanation: string;
  lines: { id: number; account_code: string; account_title: string; side: "debit" | "credit"; amount: string; currency: string }[];
};

const categoryLabels: Record<Category, string> = {
  asset: "Актив", liability: "Обязательство", equity: "Капитал", income: "Доход", expense: "Расход",
};
const today = () => new Date().toISOString().slice(0, 10);
const isAmount = (value: unknown): value is string => typeof value === "string" && /^-?\d+\.\d{2}$/.test(value);
const isCount = (value: unknown) => typeof value === "number" && Number.isSafeInteger(value) && value >= 0;
const isDimensions = (value: unknown): value is Record<string, string> => value !== null && typeof value === "object"
  && !Array.isArray(value) && Object.values(value).every(item => typeof item === "string");
const csvCell = (value: unknown) => {
  const text = String(value ?? "");
  return /[;"\r\n]/.test(text) ? `"${text.replaceAll('"', '""')}"` : text;
};
const errorText = (value: unknown, fallback: string) => typeof (value as { detail?: unknown })?.detail === "string"
  ? (value as { detail: string }).detail : fallback;

export function balanceCsv(report: Report, applied: Applied) {
  const rows: unknown[][] = [
    ["Организация", applied.org], ["С", applied.start], ["По", applied.end], ["Статус", report.status],
    ["Необработанные документы", report.pending_documents], ["Активы", report.balance.assets],
    ["Обязательства", report.balance.liabilities], ["Капитал", report.balance.equity],
    ["Текущий финансовый результат", report.balance.current_result], ["Расхождение", report.balance.difference],
    [], ["Период", "Категория", "Источник", "Дата", "Проводка", "Счёт", "Наименование", "Сторона", "Сумма в BYN", "Валюта позиции или строки", "Валюта строки при переоценке", "Оценка", "Аналитика"],
  ];
  for (const row of report.balance_movements) rows.push([
    row.period_bucket === "opening" ? "Остаток на начало" : "Движение периода", categoryLabels[row.category],
    row.source, row.date, row.entry_id, row.account, row.title, row.side === "debit" ? "Дебет" : "Кредит",
    row.amount, row.currency, row.ledger_currency ?? "", row.valuation_only ? "Переоценка" : "", JSON.stringify(row.dimensions),
  ]);
  for (const item of report.review_items ?? []) rows.push(["Проверка", item.message, item.count]);
  return rows.map(row => row.map(csvCell).join(";")).join("\r\n");
}

function movementAmount(row: Movement) {
  if (row.valuation_only) return `${row.amount} BYN · валюта позиции: ${row.currency}${row.ledger_currency ? ` (переоценка; валюта строки: ${row.ledger_currency})` : " (переоценка)"}`;
  return `${row.amount} BYN${row.currency !== "BYN" ? ` · валюта строки: ${row.currency}` : ""}`;
}

function checkedReport(value: unknown, applied: Applied): Report {
  const report = value as Partial<Report>;
  const balance = report?.balance as Partial<Balance> | undefined;
  const invalid = !report || report.organization_id !== Number(applied.org) || report.from !== applied.start || report.to !== applied.end
    || typeof report.status !== "string" || !isCount(report.pending_documents)
    || !balance || !["assets", "liabilities", "equity", "current_result", "difference"].every(key => isAmount(balance[key as keyof Balance]))
    || (report.review_items !== undefined && (!Array.isArray(report.review_items) || !report.review_items.every(item => item
      && typeof item.code === "string" && typeof item.message === "string" && isCount(item.count))))
    || !Array.isArray(report.balance_movements) || !report.balance_movements.every(row => row
      && Number.isSafeInteger(row.entry_id) && Number.isSafeInteger(row.line_id) && typeof row.source === "string"
      && typeof row.date === "string" && typeof row.account === "string" && typeof row.title === "string"
      && typeof row.currency === "string" && (row.ledger_currency === undefined || typeof row.ledger_currency === "string")
      && (row.valuation_only === undefined || typeof row.valuation_only === "boolean") && (!row.valuation_only || typeof row.ledger_currency === "string") && (row.side === "debit" || row.side === "credit")
      && isAmount(row.amount) && isDimensions(row.dimensions) && ["asset", "liability", "equity", "income", "expense"].includes(row.category)
      && (row.period_bucket === "opening" || row.period_bucket === "movement"));
  if (invalid) throw new Error("Ответ баланса имеет неверный формат или не соответствует выбранной организации и периоду.");
  return report as Report;
}

function checkedEntry(value: unknown, expectedId: number): EntryDetail {
  const entry = value as Partial<EntryDetail>;
  if (!entry || entry.id !== expectedId || typeof entry.source !== "string" || typeof entry.operation !== "string"
    || typeof entry.posting_date !== "string" || typeof entry.explanation !== "string" || !Array.isArray(entry.lines)
    || !entry.lines.every(line => line && Number.isSafeInteger(line.id) && typeof line.account_code === "string"
      && typeof line.account_title === "string" && typeof line.amount === "string" && typeof line.currency === "string"
      && (line.side === "debit" || line.side === "credit"))) throw new Error("Неверный формат операции.");
  return entry as EntryDetail;
}

export function FinanceLedgerBalance() {
  const now = today();
  const [organizations, setOrganizations] = useState<Organization[]>([]);
  const [org, setOrg] = useState("");
  const [start, setStart] = useState(`${now.slice(0, 7)}-01`);
  const [end, setEnd] = useState(now);
  const [applied, setApplied] = useState<Applied | null>(null);
  const [report, setReport] = useState<Report | null>(null);
  const [error, setError] = useState("");
  const [detail, setDetail] = useState<EntryDetail | null>(null);
  const [detailError, setDetailError] = useState("");
  const request = useRef(0);
  const detailRequest = useRef(0);

  useEffect(() => {
    let active = true;
    void fetch("/api/accounting/organizations", { cache: "no-store" }).then(async response => {
      const body: unknown = await response.json();
      if (!response.ok || !Array.isArray(body)) throw new Error(errorText(body, "Не удалось загрузить доступные организации."));
      return body as Organization[];
    }).then(rows => { if (active) setOrganizations(rows); }).catch((reason: Error) => { if (active) setError(reason.message); });
    return () => { active = false; };
  }, []);

  async function apply() {
    if (!org) { setError("Выберите организацию."); return; }
    if (!start || !end || start > end) { setError("Проверьте даты периода."); return; }
    const next = { org, start, end };
    const token = ++request.current;
    detailRequest.current += 1;
    setError(""); setDetail(null); setDetailError(""); setReport(null); setApplied(null);
    try {
      const response = await fetch(`/api/accounting/organizations/${encodeURIComponent(org)}/reports?start=${encodeURIComponent(start)}&end=${encodeURIComponent(end)}`, { cache: "no-store" });
      const body: unknown = await response.json();
      if (!response.ok) throw new Error(errorText(body, "Не удалось загрузить баланс бухгалтерской книги."));
      const nextReport = checkedReport(body, next);
      if (request.current === token) { setReport(nextReport); setApplied(next); }
    } catch (reason) {
      if (request.current === token) setError(reason instanceof Error ? reason.message : "Не удалось загрузить баланс бухгалтерской книги.");
    }
  }

  async function openEntry(row: Movement) {
    if (!applied) return;
    const token = ++detailRequest.current;
    setDetail(null); setDetailError("");
    try {
      const response = await fetch(`/api/accounting/organizations/${encodeURIComponent(applied.org)}/entries/${row.entry_id}`, { cache: "no-store" });
      const body: unknown = await response.json();
      if (!response.ok) throw new Error(errorText(body, "Не удалось загрузить операцию."));
      const entry = checkedEntry(body, row.entry_id);
      if (detailRequest.current === token) setDetail(entry);
    } catch (reason) {
      if (detailRequest.current === token) setDetailError(reason instanceof Error ? reason.message : "Не удалось загрузить операцию.");
    }
  }

  function downloadCsv() {
    if (!report || !applied) return;
    const blob = new Blob(["\uFEFF" + balanceCsv(report, applied)], { type: "text/csv;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = `ledger-balance-${applied.org}-${applied.end}.csv`;
    link.click();
    URL.revokeObjectURL(url);
  }

  const balance = report?.balance;
  const balanced = balance?.difference === "0.00";
  return <section aria-label="Баланс бухгалтерской книги" className="space-y-4 rounded-xl border border-line bg-surface p-4">
    <div><h2 className="text-lg font-bold text-ink">Баланс бухгалтерской книги</h2><p className="text-sm text-muted">Накопительные остатки по проведённым строкам до конца выбранного периода. Все суммы — BYN; валюта позиции показывается отдельно только для переоценки.</p></div>
    <div className="flex flex-wrap gap-3">
      <label className="min-w-56 flex-1 text-sm">Организация<Select aria-label="Организация баланса" value={org} onChange={event => setOrg(event.target.value)}><option value="">Выберите организацию</option>{organizations.map(item => <option key={item.id} value={item.id}>{item.name} · {item.unp}</option>)}</Select></label>
      <label className="text-sm">С<Input aria-label="Начало периода баланса" type="date" value={start} onChange={event => setStart(event.target.value)} /></label>
      <label className="text-sm">По<Input aria-label="Конец периода баланса" type="date" value={end} onChange={event => setEnd(event.target.value)} /></label>
      <div className="self-end"><Button variant="secondary" onClick={() => void apply()}>Применить</Button></div>
    </div>
    {error && <p role="alert" className="rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700">{error}</p>}
    {!organizations.length && !error && <p className="text-sm text-muted">Нет доступных организаций.</p>}
    {report && applied && balance && <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2"><p className="text-sm text-muted">Применено: организация {applied.org}, {applied.start} — {applied.end}</p><Button size="sm" variant="secondary" onClick={downloadCsv}>Скачать CSV</Button></div>
      <p className={`rounded-lg p-3 text-sm ${report.status === "closed_periods" ? "bg-emerald-50 text-emerald-800" : "bg-amber-50 text-amber-800"}`}>{report.status === "closed_periods" ? "Периоды закрыты; регламентированная отчётность не подтверждена." : "Предварительный отчёт; закрытие периодов и регламентированная отчётность не подтверждены."}</p>
      <div className="rounded-lg border border-line p-3 text-sm"><p>Необработанные документы: <strong>{report.pending_documents}</strong></p>{report.review_items?.length ? <ul className="mt-2 list-disc pl-5">{report.review_items.map(item => <li key={item.code}>{item.message} ({item.count})</li>)}</ul> : <p className="mt-2 text-muted">Замечаний проверки нет.</p>}</div>
      <div className="grid gap-3 sm:grid-cols-3"><Metric label="Активы" value={balance.assets} /><Metric label="Обязательства" value={balance.liabilities} /><Metric label="Капитал" value={balance.equity} /><Metric label="Текущий финансовый результат" value={balance.current_result} /><Metric label="Расхождение" value={balance.difference} tone={balanced ? "text-emerald-700" : "text-red-700"} /></div>
      <div className={`rounded-lg border p-3 text-sm ${balanced ? "border-emerald-200 bg-emerald-50" : "border-red-200 bg-red-50 text-red-700"}`}><p>Уравнение: {balance.assets} = {balance.liabilities} + {balance.equity} + {balance.current_result} + {balance.difference} BYN</p><p role={balanced ? "status" : "alert"}>{balanced ? "Расхождений баланса нет." : `Расхождение баланса: ${balance.difference} BYN. Требуется проверка.`}</p></div>
      <div className="overflow-x-auto"><table className="min-w-full text-left text-sm"><caption className="mb-2 text-left font-semibold text-ink">Строки, вошедшие в баланс</caption><thead className="border-b border-line text-muted"><tr><th>Период</th><th>Категория</th><th>Дата</th><th>Источник</th><th>Счёт</th><th>Сторона</th><th>Сумма</th><th>Аналитика</th><th>Операция</th></tr></thead><tbody>{report.balance_movements.map(row => <tr key={row.line_id} className="border-b border-line"><td>{row.period_bucket === "opening" ? "Остаток на начало" : "Движение периода"}</td><td>{categoryLabels[row.category]}</td><td>{row.date}</td><td>{row.source} · №{row.entry_id}</td><td>{row.account} · {row.title}</td><td>{row.side === "debit" ? "Дебет" : "Кредит"}</td><td>{movementAmount(row)}</td><td>{Object.entries(row.dimensions).map(([key, value]) => `${key}: ${value}`).join(", ") || "—"}</td><td><Button size="sm" variant="ghost" onClick={() => void openEntry(row)}>Открыть</Button></td></tr>)}</tbody></table>{!report.balance_movements.length && <p className="py-3 text-sm text-muted">До конца выбранного периода нет балансовых строк.</p>}</div>
      {detailError && <p role="alert" className="rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700">{detailError}</p>}
      {detail && <div className="rounded-lg border border-line p-3 text-sm"><h3 className="font-semibold text-ink">Операция № {detail.id}</h3><p className="text-muted">{detail.posting_date} · {detail.source} · {detail.operation}</p><p className="mt-1">{detail.explanation}</p><ul className="mt-2 list-disc pl-5">{detail.lines.map(line => <li key={line.id}>{line.account_code} · {line.account_title}: {line.side === "debit" ? "Дебет" : "Кредит"} {line.amount} BYN{line.currency !== "BYN" ? ` · валюта строки: ${line.currency}` : ""}</li>)}</ul></div>}
    </div>}
  </section>;
}

function Metric({ label, value, tone = "text-ink" }: { label: string; value: string; tone?: string }) {
  return <div className="rounded-xl bg-sunken p-4"><p className="text-sm text-muted">{label}</p><p className={`mt-1 text-xl font-bold ${tone}`}>{value} BYN</p></div>;
}
