"use client";

import { useEffect, useState } from "react";

import { Button } from "@/components/ui/button";

type Amounts = {
  gross_byn: string;
  listed_employee_deductions_byn: string;
  after_listed_deductions_byn: string;
  listed_employer_contributions_byn: string;
  cost_including_listed_contributions_byn: string;
};
type CoverageIssue = { kind: string; employment_binding_id: number; work_from: string; work_to: string };
type Summary = {
  organization_id: number;
  month: string;
  review_count: number;
  selected_segment_count: number;
  totals: Amounts;
  bindings: { employment_binding_id: number; segments: { review_id: number; revision: number; work_from: string; work_to: string }[]; totals: Amounts }[];
  known_binding_coverage: { active_binding_count: number; known_binding_coverage_complete: boolean; issues: CoverageIssue[] };
  current_file_bytes_verified: boolean;
  statutory_payroll_certified: false;
};
type ComparisonAmounts = Pick<Amounts, "gross_byn" | "listed_employee_deductions_byn" | "listed_employer_contributions_byn">;
type Comparison = {
  organization_id: number;
  month: string;
  status: "not_ready" | "differences" | "matched_arithmetic_only";
  comparison_ready: boolean;
  population_review_current: boolean;
  known_workpaper_coverage_complete: boolean;
  receipt_entry_ids: { gross: number[]; statutory: number[] };
  receipt_gaps: { gross: number; statutory: number };
  unmapped_source_lines: { gross: number; statutory: number };
  missing_gross_binding_ids: number[];
  missing_statutory_binding_ids: number[];
  conflicting_statutory_zero_binding_ids: number[];
  unmatched_import_binding_ids: number[];
  differing_binding_count: number;
  bindings: { employment_binding_id: number; known_active: boolean; reviewed: ComparisonAmounts | null; imported: ComparisonAmounts; difference_import_less_review: ComparisonAmounts | null }[];
  source_facts_verified: false;
  statutory_payroll_certified: false;
};
type Loaded = { summary: Summary | null; comparison: Comparison | null; summaryError: string; comparisonError: string; loading: boolean };

const amountLabels: [keyof Amounts, string][] = [
  ["gross_byn", "Начислено"],
  ["listed_employee_deductions_byn", "Перечисленные удержания"],
  ["after_listed_deductions_byn", "После перечисленных удержаний"],
  ["listed_employer_contributions_byn", "Перечисленные взносы нанимателя"],
  ["cost_including_listed_contributions_byn", "Начислено со взносами"],
];
const differenceLabels: [keyof ComparisonAmounts, string][] = [
  ["gross_byn", "Начислено"],
  ["listed_employee_deductions_byn", "Удержания"],
  ["listed_employer_contributions_byn", "Взносы нанимателя"],
];
const issueLabels: Record<string, string> = {
  unreviewed_interval: "Нет рассмотренного расчётного отрезка",
  outside_current_binding: "Расчётный отрезок вне действующего договора",
};

async function readScoped<T extends { organization_id: number; month: string }>(
  path: string, org: string, month: string, signal: AbortSignal,
): Promise<T> {
  const response = await fetch(`/api/accounting/organizations/${org}/periods/${month}/${path}`, {
    cache: "no-store", signal,
  });
  if (!response.ok) {
    let detail = "Не удалось загрузить контроль зарплаты.";
    try {
      const body = await response.json() as { detail?: unknown };
      if (typeof body.detail === "string") detail = body.detail;
    } catch { /* Keep the explicit fallback. */ }
    throw new Error(detail);
  }
  const body = await response.json() as T;
  if (body.organization_id !== Number(org) || body.month !== month) {
    throw new Error("Ответ относится к другому юридическому лицу или периоду.");
  }
  return body;
}

function ids(label: string, values: number[]) {
  return values.length ? <li>{label}: {values.join(", ")}</li> : null;
}

export function AccountingPayrollControl({ org, month, onEntry }: {
  org: string; month: string; onEntry: (id: number) => void;
}) {
  const [reload, setReload] = useState(0);
  const [loaded, setLoaded] = useState<Loaded>({
    summary: null, comparison: null, summaryError: "", comparisonError: "", loading: true,
  });

  useEffect(() => {
    if (!org || !/^\d{4}-(0[1-9]|1[0-2])$/.test(month)) return;
    const controller = new AbortController();
    void Promise.allSettled([
      readScoped<Summary>("payroll-arithmetic-summary", org, month, controller.signal),
      readScoped<Comparison>("payroll-source-reconciliation", org, month, controller.signal),
    ]).then(([summary, comparison]) => {
      if (controller.signal.aborted) return;
      setLoaded({
        summary: summary.status === "fulfilled" ? summary.value : null,
        comparison: comparison.status === "fulfilled" ? comparison.value : null,
        summaryError: summary.status === "rejected" ? String(summary.reason?.message ?? summary.reason) : "",
        comparisonError: comparison.status === "rejected" ? String(comparison.reason?.message ?? comparison.reason) : "",
        loading: false,
      });
    });
    return () => controller.abort();
  }, [org, month, reload]);

  return <section aria-label="Контроль зарплаты" className="space-y-4 rounded-xl border border-line bg-surface p-4">
    <div className="flex flex-wrap items-start justify-between gap-3">
      <div>
        <h2 className="text-lg font-semibold">Контроль зарплаты · {month}</h2>
        <p className="mt-1 text-sm text-muted">Расчётные листы здесь показывают только проверенную арифметику перечисленных компонентов. Сверка с проводками не подтверждает исходные данные, полноту работников, применимость ставок или обязательную отчётность.</p>
      </div>
      <Button variant="secondary" disabled={!org || loaded.loading} onClick={() => {
        setLoaded({ summary: null, comparison: null, summaryError: "", comparisonError: "", loading: true });
        setReload((value) => value + 1);
      }}>Обновить контроль</Button>
    </div>
    {!org && <p className="text-sm text-muted">Выберите юридическое лицо.</p>}
    {org && !/^\d{4}-(0[1-9]|1[0-2])$/.test(month) && <p role="alert">Выберите корректный месяц.</p>}
    {loaded.loading && org && <p role="status">Загрузка контроля зарплаты…</p>}

    {loaded.summaryError && <p role="alert" className="text-red-700">Расчётные листы: {loaded.summaryError}</p>}
    {loaded.summary && <div className="space-y-3 rounded-lg border border-line p-4">
      <h3 className="font-semibold">Рассмотренные расчётные отрезки</h3>
      <p className="text-sm text-muted">Квитанций: {loaded.summary.review_count}; действующих редакций отрезков: {loaded.summary.selected_segment_count}. Известных активных договоров: {loaded.summary.known_binding_coverage.active_binding_count}.</p>
      {loaded.summary.current_file_bytes_verified && <p className="text-xs text-muted">Сохранённые файлы-основания действующих отрезков повторно сверены по байтам. Содержание документов подтверждает бухгалтер.</p>}
      <dl className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">{amountLabels.map(([key, label]) => <div key={key} className="rounded-lg bg-canvas p-3"><dt className="text-xs text-muted">{label}</dt><dd className="font-semibold tabular-nums">{loaded.summary!.totals[key]} BYN</dd></div>)}</dl>
      <p className="text-sm">{loaded.summary.known_binding_coverage.active_binding_count === 0 ? "На этот месяц нет известных активных договоров. Проверьте реестр работников и основание нулевых начислений." : loaded.summary.known_binding_coverage.known_binding_coverage_complete ? "Все отрезки известных договоров рассмотрены; полнота реального штата не подтверждена." : "Есть нерассмотренные или устаревшие отрезки известных договоров."}</p>
      {!!loaded.summary.known_binding_coverage.issues.length && <ul className="list-disc space-y-1 pl-5 text-sm">{loaded.summary.known_binding_coverage.issues.map((issue, index) => <li key={`${issue.kind}-${issue.employment_binding_id}-${index}`}>{issueLabels[issue.kind] ?? issue.kind}: договор № {issue.employment_binding_id}, {issue.work_from}–{issue.work_to}</li>)}</ul>}
      {!!loaded.summary.bindings.length && <div className="space-y-2">{loaded.summary.bindings.map((binding) => <div key={binding.employment_binding_id} className="rounded-lg border border-line p-3 text-sm"><strong>Договор № {binding.employment_binding_id}</strong><span className="ml-3">Начислено: {binding.totals.gross_byn} BYN</span><span className="ml-3">Отрезков: {binding.segments.length}</span></div>)}</div>}
    </div>}

    {loaded.comparisonError && <p role="alert" className="text-red-700">Сверка с проводками: {loaded.comparisonError}</p>}
    {loaded.comparison && <div className="space-y-3 rounded-lg border border-line p-4">
      <h3 className="font-semibold">Сверка с проведёнными импортами</h3>
      <p className="text-sm">{loaded.comparison.status === "matched_arithmetic_only" ? "Арифметика совпадает; бухгалтерское и нормативное подтверждение ещё требуется." : loaded.comparison.status === "differences" ? `Есть расхождения по договорам: ${loaded.comparison.differing_binding_count}.` : "Сверка не готова: проверьте источники и покрытие."}</p>
      <p className="text-xs text-muted">Все суммы в BYN. Разница — импорт минус рассмотренный расчёт.</p>
      <ul className="list-disc space-y-1 pl-5 text-sm">
        {!loaded.comparison.population_review_current && <li>Состав известных работников не подтверждён текущей редакцией.</li>}
        {!loaded.comparison.known_workpaper_coverage_complete && <li>Расчётные отрезки известных договоров покрыты не полностью.</li>}
        {ids("Без валового начисления, договоры", loaded.comparison.missing_gross_binding_ids)}
        {ids("Без источника удержаний и взносов, договоры", loaded.comparison.missing_statutory_binding_ids)}
        {ids("Конфликт с нулевым источником, договоры", loaded.comparison.conflicting_statutory_zero_binding_ids)}
        {ids("Импорт без расчётного листа, договоры", loaded.comparison.unmatched_import_binding_ids)}
        {(loaded.comparison.unmapped_source_lines.gross + loaded.comparison.unmapped_source_lines.statutory) > 0 && <li>Строки без договора: {loaded.comparison.unmapped_source_lines.gross + loaded.comparison.unmapped_source_lines.statutory}.</li>}
        {(loaded.comparison.receipt_gaps.gross + loaded.comparison.receipt_gaps.statutory) > 0 && <li>Проводки без квитанции импорта: {loaded.comparison.receipt_gaps.gross + loaded.comparison.receipt_gaps.statutory}.</li>}
      </ul>
      <div className="flex flex-wrap gap-3 text-sm">{(["gross", "statutory"] as const).flatMap((kind) => loaded.comparison!.receipt_entry_ids[kind].map((entryId) => <button key={`${kind}-${entryId}`} type="button" className="text-accent underline" onClick={() => onEntry(entryId)}>{kind === "gross" ? "Начисление" : "Удержания и взносы"} · проводка № {entryId}</button>))}</div>
      {!!loaded.comparison.bindings.length && <div className="space-y-2">{loaded.comparison.bindings.map((binding) => <div key={binding.employment_binding_id} className="rounded-lg border border-line p-3 text-sm"><strong>Договор № {binding.employment_binding_id}</strong>{differenceLabels.map(([key, label]) => <p key={key}>{label}: расчёт {binding.reviewed?.[key] ?? "—"}, импорт {binding.imported[key]}, разница {binding.difference_import_less_review?.[key] ?? "—"} BYN</p>)}</div>)}</div>}
      <p className="text-xs text-muted">Источники для сравнения: {loaded.comparison.comparison_ready ? "собраны; суммы всё ещё могут расходиться" : "неполные"}. Нормативная сертификация и проведение собственного расчёта недоступны.</p>
    </div>}
  </section>;
}
