"use client";

import { useEffect, useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import { Input, Select } from "@/components/ui/input";

type Organization = { id: number; name: string; unp: string };
type PnlMovement = {
  entry_id: number; source: string; date: string; account: string; title: string;
  line_id: number; currency: string; ledger_currency?: string; valuation_only?: boolean; side: "debit" | "credit"; amount: string;
  dimensions: Record<string, string>; category: "income" | "expense";
};
type ReviewItem = { code: string; count: number; message: string };
type Report = {
  organization_id: number; from: string; to: string; status: "preliminary" | "closed_periods" | string;
  pending_documents: number; review_items?: ReviewItem[];
  pnl: { income: string; expenses: string; profit: string };
  pnl_movements: PnlMovement[];
};
type Applied = { org: string; start: string; end: string };
type EntryDetail = { id: number; source: string; operation: string; explanation: string; posting_date: string; lines: { id: number; account_code: string; account_title: string; side: string; amount: string; currency?: string; dimensions: Record<string, string> }[] };

const today = () => new Date().toISOString().slice(0, 10);

function csvCell(value: unknown) {
  const text = String(value ?? "");
  return /[;"\r\n]/.test(text) ? `"${text.replaceAll('"', '""')}"` : text;
}

export function pnlCsv(report: Report, applied: Applied) {
  const header = ["Организация", "С", "По", "Статус", "Доходы", "Расходы", "Финансовый результат", "Источник", "Дата", "Проводка", "Счёт", "Наименование", "Категория", "Сторона", "Сумма BYN", "Валюта позиции или строки", "Валюта строки при переоценке", "Оценка", "Аналитика"];
  const summary = [applied.org, applied.start, applied.end, report.status, report.pnl.income, report.pnl.expenses, report.pnl.profit, "", "", "", "", "", "", "", "", "", "", "", ""];
  const rows = report.pnl_movements.map((row) => [
    applied.org, applied.start, applied.end, report.status, report.pnl.income, report.pnl.expenses, report.pnl.profit,
    row.source, row.date, row.entry_id, row.account, row.title, row.category, row.side, row.amount, row.currency,
    row.ledger_currency ?? "", row.valuation_only ? "Переоценка" : "",
    JSON.stringify(row.dimensions),
  ]);
  return [header, summary, ...rows].map((row) => row.map(csvCell).join(";")).join("\r\n");
}

function money(value: string) { return `${value} BYN`; }
function movementAmount(row: PnlMovement) {
  if (row.valuation_only) return `${row.amount} BYN · валюта позиции: ${row.currency}${row.ledger_currency ? ` (переоценка; валюта строки: ${row.ledger_currency})` : " (переоценка)"}`;
  return `${row.amount} BYN${row.currency !== "BYN" ? ` · валюта строки: ${row.currency}` : ""}`;
}
function message(data: unknown, fallback: string) {
  return typeof (data as { detail?: unknown })?.detail === "string" ? (data as { detail: string }).detail : fallback;
}

function checkedReport(value: unknown, applied: Applied): Report {
  const report = value as Partial<Report>;
  if (!report || Number(report.organization_id) !== Number(applied.org) || report.from !== applied.start || report.to !== applied.end
    || !report.pnl || typeof report.pnl.income !== "string" || typeof report.pnl.expenses !== "string" || typeof report.pnl.profit !== "string"
    || !Array.isArray(report.pnl_movements) || !report.pnl_movements.every((row) => row && typeof row.entry_id === "number" && typeof row.source === "string" && typeof row.date === "string" && typeof row.account === "string" && typeof row.title === "string" && typeof row.line_id === "number" && typeof row.currency === "string" && (row.ledger_currency === undefined || typeof row.ledger_currency === "string") && (row.valuation_only === undefined || typeof row.valuation_only === "boolean") && (!row.valuation_only || typeof row.ledger_currency === "string") && (row.side === "debit" || row.side === "credit") && typeof row.amount === "string" && row.dimensions && typeof row.dimensions === "object" && (row.category === "income" || row.category === "expense")))
    throw new Error("Ответ P&L не соответствует применённой организации или периоду.");
  return report as Report;
}

function checkedEntry(value: unknown, entryId: number): EntryDetail {
  const entry = value as Partial<EntryDetail>;
  if (!entry || entry.id !== entryId || typeof entry.source !== "string" || typeof entry.operation !== "string" || typeof entry.explanation !== "string" || typeof entry.posting_date !== "string" || !Array.isArray(entry.lines)) throw new Error("Ответ операции имеет неверный формат.");
  return entry as EntryDetail;
}

export function FinanceLedgerPnl() {
  const initial = today();
  const [organizations, setOrganizations] = useState<Organization[]>([]);
  const [org, setOrg] = useState("");
  const [start, setStart] = useState(`${initial.slice(0, 7)}-01`);
  const [end, setEnd] = useState(initial);
  const [applied, setApplied] = useState<Applied | null>(null);
  const [report, setReport] = useState<Report | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [detail, setDetail] = useState<EntryDetail | null>(null);
  const [detailError, setDetailError] = useState("");
  const [detailLoading, setDetailLoading] = useState(false);
  const request = useRef(0);
  const detailRequest = useRef(0);

  useEffect(() => {
    let active = true;
    void fetch("/api/accounting/organizations", { cache: "no-store" })
      .then(async (response) => {
        const body: unknown = await response.json();
        if (!response.ok) throw new Error(message(body, "Не удалось загрузить доступные организации."));
        if (!Array.isArray(body)) throw new Error("Ответ организаций имеет неверный формат.");
        return body as Organization[];
      })
      .then((rows) => { if (active) setOrganizations(rows); })
      .catch((reason: Error) => { if (active) setError(reason.message); });
    return () => { active = false; };
  }, []);

  async function apply() {
    if (!org) { setError("Выберите организацию."); return; }
    if (!start || !end || start > end) { setError("Проверьте даты периода."); return; }
    const next = { org, start, end };
    const token = ++request.current;
    detailRequest.current += 1;
    setLoading(true); setError(""); setReport(null); setApplied(null); setDetail(null); setDetailError(""); setDetailLoading(false);
    try {
      const response = await fetch(`/api/accounting/organizations/${encodeURIComponent(org)}/reports?start=${encodeURIComponent(start)}&end=${encodeURIComponent(end)}`, { cache: "no-store" });
      const body: unknown = await response.json();
      if (!response.ok) throw new Error(message(body, "Не удалось загрузить P&L бухгалтерской книги."));
      const nextReport = checkedReport(body, next);
      if (request.current === token) { setReport(nextReport); setApplied(next); }
    } catch (reason) {
      if (request.current === token) setError(reason instanceof Error ? reason.message : "Не удалось загрузить P&L бухгалтерской книги.");
    } finally {
      if (request.current === token) setLoading(false);
    }
  }

  async function openEntry(row: PnlMovement) {
    if (!applied) return;
    const token = ++detailRequest.current;
    setDetailLoading(true); setDetailError(""); setDetail(null);
    try {
      const response = await fetch(`/api/accounting/organizations/${encodeURIComponent(applied.org)}/entries/${row.entry_id}`, { cache: "no-store" });
      const body: unknown = await response.json();
      if (!response.ok) throw new Error(message(body, "Не удалось загрузить операцию P&L."));
      const entry = checkedEntry(body, row.entry_id);
      if (detailRequest.current === token) setDetail(entry);
    } catch (reason) {
      if (detailRequest.current === token) setDetailError(reason instanceof Error ? reason.message : "Не удалось загрузить операцию P&L.");
    } finally {
      if (detailRequest.current === token) setDetailLoading(false);
    }
  }

  function downloadCsv() {
    if (!report || !applied) return;
    const blob = new Blob(["\uFEFF" + pnlCsv(report, applied)], { type: "text/csv;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url; link.download = `accounting-pnl-${applied.org}-${applied.start}-${applied.end}.csv`;
    link.click(); URL.revokeObjectURL(url);
  }

  return <section aria-label="Бухгалтерский P&L" className="space-y-4 rounded-xl border border-line bg-surface p-4">
    <div><h2 className="text-lg font-bold text-ink">Финансовый результат бухгалтерской книги</h2><p className="text-sm text-muted">Доходы и расходы по проведённым строкам учёта. Все суммы — BYN; валюта строки или позиции не является суммой операции. Не является операционной маржой или регламентированной отчётностью.</p></div>
    <div className="flex flex-wrap gap-3">
      <label className="min-w-56 flex-1 text-sm">Организация<Select aria-label="Организация P&L" value={org} onChange={(event) => setOrg(event.target.value)}><option value="">Выберите организацию</option>{organizations.map((item) => <option key={item.id} value={item.id}>{item.name} · {item.unp}</option>)}</Select></label>
      <label className="text-sm">С<Input aria-label="Начало периода P&L" type="date" value={start} onChange={(event) => setStart(event.target.value)} /></label>
      <label className="text-sm">По<Input aria-label="Конец периода P&L" type="date" value={end} onChange={(event) => setEnd(event.target.value)} /></label>
      <div className="self-end"><Button variant="secondary" aria-busy={loading} onClick={() => void apply()}>Применить</Button></div>
    </div>
    {error && <p role="alert" className="rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700">{error}</p>}
    {!organizations.length && !error && <p className="text-sm text-muted">Нет доступных организаций.</p>}
    {report && applied && <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2"><p className="text-sm text-muted">Применено: организация {applied.org}, {applied.start} — {applied.end}</p><Button size="sm" variant="secondary" onClick={downloadCsv}>Скачать CSV</Button></div>
      <p className={`rounded-lg p-3 text-sm ${report.status === "closed_periods" ? "bg-emerald-50 text-emerald-800" : "bg-amber-50 text-amber-800"}`}>{report.status === "closed_periods" ? "Периоды закрыты; регламентированная отчётность не подтверждена." : "Предварительный отчёт; закрытие периодов и регламентированная отчётность не подтверждены."}</p>
      <div className="grid gap-3 sm:grid-cols-3"><Metric label="Доходы" value={report.pnl.income} tone="text-emerald-700" /><Metric label="Расходы" value={report.pnl.expenses} tone="text-rose-700" /><Metric label="Финансовый результат" value={report.pnl.profit} tone="text-ink" /></div>
      <div className="rounded-lg border border-line p-3 text-sm"><p>Необработанные документы: <strong>{report.pending_documents}</strong></p>{report.review_items?.length ? <ul className="mt-2 list-disc pl-5">{report.review_items.map((item) => <li key={item.code}>{item.message} ({item.count})</li>)}</ul> : <p className="mt-2 text-muted">Замечаний проверки нет.</p>}</div>
      <div className="overflow-x-auto"><table className="min-w-full text-left text-sm"><caption className="mb-2 text-left font-semibold text-ink">Строки, вошедшие в P&L</caption><thead className="border-b border-line text-muted"><tr><th>Дата</th><th>Категория</th><th>Источник</th><th>Счёт</th><th>Сторона</th><th>Сумма</th><th>Аналитика</th><th>Операция</th></tr></thead><tbody>{report.pnl_movements.map((row) => <tr key={row.line_id} className="border-b border-line"><td>{row.date}</td><td>{row.category === "income" ? "Доход" : "Расход"}</td><td>{row.source} · №{row.entry_id}</td><td>{row.account} · {row.title}</td><td>{row.side === "debit" ? "Дебет" : "Кредит"}</td><td>{movementAmount(row)}</td><td>{Object.entries(row.dimensions).map(([key, value]) => `${key}: ${value}`).join(", ") || "—"}</td><td><Button size="sm" variant="ghost" onClick={() => void openEntry(row)}>Открыть</Button></td></tr>)}</tbody></table>{!report.pnl_movements.length && <p className="py-3 text-sm text-muted">В применённом периоде нет строк доходов и расходов.</p>}</div>
      {detailLoading && <p role="status" className="text-sm text-muted">Загрузка операции…</p>}
      {detailError && <p role="alert" className="rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700">{detailError}</p>}
      {detail && <div className="rounded-lg border border-line p-3 text-sm"><h3 className="font-semibold text-ink">Операция № {detail.id}</h3><p className="text-muted">{detail.posting_date} · {detail.source} · {detail.operation}</p><p className="mt-1">{detail.explanation}</p><ul className="mt-2 list-disc pl-5">{detail.lines.map((line) => <li key={line.id}>{line.account_code} · {line.account_title}: {line.side === "debit" ? "Дебет" : "Кредит"} {line.amount} BYN{line.currency !== "BYN" ? ` · валюта строки: ${line.currency}` : ""}</li>)}</ul></div>}
    </div>}
  </section>;
}

function Metric({ label, value, tone }: { label: string; value: string; tone: string }) {
  return <div className="rounded-xl bg-sunken p-4"><p className="text-sm text-muted">{label}</p><p className={`mt-1 text-xl font-bold ${tone}`}>{money(value)}</p></div>;
}
