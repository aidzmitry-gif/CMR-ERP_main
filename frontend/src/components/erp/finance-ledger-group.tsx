"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

type Organization = { id: number; name: string; unp: string };
type ReviewItem = { code: string; count: number; message: string };
type LedgerReport = {
  organization_id: number; from: string; to: string; status: string; pending_documents: number;
  review_items?: ReviewItem[];
  pnl: { profit: string };
  cashflow: { closing: string };
  balance: { equity: string; difference: string };
};
type Result = { organization: Organization; report?: LedgerReport; error?: string };
type Period = { start: string; end: string };

const today = () => new Date().toISOString().slice(0, 10);
const money = (value: unknown): value is string => typeof value === "string" && /^-?\d+\.\d{2}$/.test(value);
const positiveId = (value: unknown): value is number => typeof value === "number" && Number.isSafeInteger(value) && value > 0;
const cents = (value: string) => {
  const [whole, fraction] = value.replace("-", "").split(".");
  const amount = BigInt(whole) * 100n + BigInt(fraction);
  return value.startsWith("-") ? -amount : amount;
};
const totalMoney = (values: string[]) => {
  const amount = values.reduce((total, value) => total + cents(value), 0n);
  const sign = amount < 0n ? "-" : "";
  const absolute = amount < 0n ? -amount : amount;
  return `${sign}${absolute / 100n}.${String(absolute % 100n).padStart(2, "0")}`;
};

function reportFor(value: unknown, organization: Organization, period: Period): LedgerReport {
  const row = value as Partial<LedgerReport>;
  const balance = row.balance as Partial<LedgerReport["balance"]> | undefined;
  const pnl = row.pnl as Partial<LedgerReport["pnl"]> | undefined;
  const cashflow = row.cashflow as Partial<LedgerReport["cashflow"]> | undefined;
  const validReviews = row.review_items === undefined || (Array.isArray(row.review_items) && row.review_items.every(item =>
    item && typeof item.code === "string" && typeof item.message === "string" && Number.isSafeInteger(item.count) && item.count >= 0));
  if (!row || row.organization_id !== organization.id || row.from !== period.start || row.to !== period.end
    || typeof row.status !== "string" || typeof row.pending_documents !== "number" || !Number.isSafeInteger(row.pending_documents) || row.pending_documents < 0
    || !pnl || !cashflow || !balance || !money(pnl.profit) || !money(cashflow.closing)
    || !money(balance.equity) || !money(balance.difference) || !validReviews) {
    throw new Error("Ответ бухгалтерского отчёта не соответствует организации или периоду.");
  }
  return row as LedgerReport;
}

async function readJson(response: Response): Promise<unknown> {
  return response.json().catch(() => null);
}

function errorText(body: unknown, fallback: string) {
  return typeof (body as { detail?: unknown } | null)?.detail === "string"
    ? (body as { detail: string }).detail : fallback;
}

export function FinanceLedgerGroup() {
  const initial = today();
  const [organizations, setOrganizations] = useState<Organization[] | null>(null);
  const [organizationsError, setOrganizationsError] = useState("");
  const [start, setStart] = useState(`${initial.slice(0, 7)}-01`);
  const [end, setEnd] = useState(initial);
  const [period, setPeriod] = useState<Period>({ start: `${initial.slice(0, 7)}-01`, end: initial });
  const [results, setResults] = useState<Result[] | null>(null);
  const request = useRef(0);

  useEffect(() => {
    const controller = new AbortController();
    void fetch("/api/accounting/organizations", { cache: "no-store", signal: controller.signal })
      .then(async response => {
        const body = await readJson(response);
        if (!response.ok || !Array.isArray(body) || body.some(row => !row || !positiveId(row.id) || typeof row.name !== "string" || typeof row.unp !== "string")) {
          throw new Error(errorText(body, "Не удалось загрузить доступные организации."));
        }
        return body as Organization[];
      })
      .then(rows => { if (!controller.signal.aborted) setOrganizations(rows); })
      .catch(reason => { if (!controller.signal.aborted) setOrganizationsError(reason instanceof Error ? reason.message : "Не удалось загрузить доступные организации."); });
    return () => controller.abort();
  }, []);

  useEffect(() => {
    if (!organizations) return;
    const controller = new AbortController();
    const token = ++request.current;
    setResults(null);
    void Promise.all(organizations.map(async organization => {
      try {
        const response = await fetch(`/api/accounting/organizations/${organization.id}/reports?start=${encodeURIComponent(period.start)}&end=${encodeURIComponent(period.end)}`, { cache: "no-store", signal: controller.signal });
        const body = await readJson(response);
        if (!response.ok) throw new Error(errorText(body, `Не удалось загрузить отчёт (${response.status}).`));
        return { organization, report: reportFor(body, organization, period) } as Result;
      } catch (reason) {
        if (controller.signal.aborted) throw reason;
        return { organization, error: reason instanceof Error ? reason.message : "Не удалось загрузить отчёт." } as Result;
      }
    })).then(rows => { if (!controller.signal.aborted && request.current === token) setResults(rows); })
      .catch(() => { /* Abort cancels the whole batch; a newer period owns the visible state. */ });
    return () => controller.abort();
  }, [organizations, period]);

  function apply() {
    if (!start || !end || start > end) { setOrganizationsError("Проверьте даты периода."); return; }
    setOrganizationsError("");
    setPeriod({ start, end });
  }

  const available = results?.filter(row => row.report) ?? [];
  const failed = results?.filter(row => row.error) ?? [];
  const profit = available.length ? totalMoney(available.map(row => row.report!.pnl.profit)) : null;

  return <section aria-label="Обзор группы" className="space-y-4 rounded-xl border border-line bg-surface p-4">
    <div><h2 className="text-lg font-bold text-ink">Обзор группы</h2><p className="text-sm text-muted">Отдельные бухгалтерские результаты доступных юрлиц. Внутригрупповые исключения и консолидированная прибыль не рассчитаны.</p></div>
    <div className="flex flex-wrap gap-3"><label className="text-sm">С<Input aria-label="Начало периода обзора группы" type="date" value={start} onChange={event => setStart(event.target.value)} /></label><label className="text-sm">По<Input aria-label="Конец периода обзора группы" type="date" value={end} onChange={event => setEnd(event.target.value)} /></label><div className="self-end"><Button variant="secondary" onClick={apply}>Обновить обзор</Button></div></div>
    {organizationsError && <p role="alert" className="rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700">{organizationsError}</p>}
    {organizations === null && !organizationsError && <p role="status" className="text-sm text-muted">Загрузка доступных организаций…</p>}
    {organizations?.length === 0 && <p className="text-sm text-muted">Нет доступных организаций для бухгалтерского обзора.</p>}
    {organizations && organizations.length > 0 && results === null && !organizationsError && <p role="status" className="text-sm text-muted">Загрузка отдельных бухгалтерских отчётов…</p>}
    {results && <div className="space-y-3"><div className="overflow-x-auto"><table className="min-w-full text-left text-sm"><caption className="mb-2 text-left font-semibold text-ink">Показатели отдельных юридических лиц за {period.start} — {period.end}</caption><thead className="border-b border-line text-muted"><tr><th>Юрлицо</th><th>Статус данных</th><th className="text-right">Прибыль/убыток</th><th className="text-right">Деньги на конец</th><th className="text-right">Капитал</th><th className="text-right">Расхождение баланса</th><th>Drill-down</th></tr></thead><tbody>{results.map(row => row.report ? <tr key={row.organization.id} className="border-b border-line"><td>{row.organization.name} · {row.organization.unp}</td><td>{row.report.status === "closed_periods" ? "Периоды закрыты; регламентированная отчётность не подтверждена." : "Предварительный отчёт."}{row.report.pending_documents > 0 ? ` Необработанные документы: ${row.report.pending_documents}.` : ""}{row.report.review_items?.length ? ` Замечания: ${row.report.review_items.map(item => `${item.message} (${item.count})`).join("; ")}` : ""}</td><td className="text-right tabular-nums">{row.report.pnl.profit} BYN</td><td className="text-right tabular-nums">{row.report.cashflow.closing} BYN</td><td className="text-right tabular-nums">{row.report.balance.equity} BYN</td><td className="text-right tabular-nums">{row.report.balance.difference} BYN</td><td><Link className="text-accent underline" href={`/erp/accounting?org=${row.organization.id}`}>Открыть отчёт {row.organization.name}</Link></td></tr> : <tr key={row.organization.id} className="border-b border-line"><td>{row.organization.name} · {row.organization.unp}</td><td colSpan={6}><span role="alert">Отчёт недоступен: {row.error}</span></td></tr>)}</tbody></table></div><div className="rounded-lg border border-amber-300 bg-amber-50 p-3 text-sm text-amber-900"><strong>Сумма отдельных результатов — не консолидация:</strong> {profit === null ? "нет загруженных отдельных результатов" : `${profit} BYN`}.{failed.length ? ` Отчёты с ошибкой: ${failed.length}; они не заменены нулями.` : ""}<p className="mt-1">Внутригрупповые исключения, консолидированная прибыль и налоговая отчётность не рассчитаны без отдельного утверждённого контура.</p></div></div>}
  </section>;
}
