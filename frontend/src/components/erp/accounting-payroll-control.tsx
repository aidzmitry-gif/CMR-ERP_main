"use client";

import { useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import { AccountingPayrollApplicabilityReview } from "./accounting-payroll-applicability-review";
import { AccountingPayrollOrganizationReview } from "./accounting-payroll-organization-review";

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
  source_fact_attested_segment_count: number;
  source_fact_unattested_review_ids: number[];
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
type Candidate = {
  organization_id: number;
  month: string;
  status: "provisional_payroll_candidate_only";
  candidate_digest: string;
  included_segment_count: number;
  selected_segment_count: number;
  unattested_review_ids: number[];
  totals: Amounts;
  blockers: string[];
  applicability: {
    status: "facts_and_rules_unverified";
    population_scope: "known_erp_bindings_only";
    reference_year: number;
    reference_scope: "selected_mns_topics_only" | "no_period_source_checked";
    references: { topic: string; url: string }[];
    organization_gap_codes: string[];
    organization: { review_id: number | null; review_digest: string | null; reviewed_rule_codes: string[]; unresolved_rule_codes: string[]; rule_decisions?: Record<string, string> };
    rate_obligations?: { rate_code: string; obligation_code: string | null; chief_decision: "applicable" | "not_applicable" | "unresolved" | null }[];
    bindings: { employment_binding_id: number; review_id: number | null; review_digest: string | null; reviewed_fact_codes: string[]; unrecorded_fact_codes: string[] }[];
    statutory_completeness_verified: false;
  };
  arithmetic_scope_complete: boolean;
  posting_available: false;
  statutory_payroll_certified: false;
};
type Loaded = { summary: Summary | null; comparison: Comparison | null; candidate: Candidate | null; summaryError: string; comparisonError: string; candidateError: string; loading: boolean };

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
const candidateBlockers: Record<string, string> = {
  no_reviewed_segments: "Нет рассмотренных расчётных отрезков.",
  source_facts_not_attested: "Главбух не подтвердил исходные данные всех выбранных отрезков.",
  known_binding_coverage_incomplete: "Отрезки известных договоров покрыты не полностью.",
  population_review_missing_or_stale: "Нет актуального подтверждённого реестра работников.",
  rule_set_missing: "Для месяца не задан набор правил расчёта.",
  accounting_policy_changed_or_unverified: "Учётная политика для месяца изменилась или не подтверждена.",
  rule_source_file_missing: "К набору правил не приложен сохранённый файл политики.",
  rule_version_changed: "Версия правила или ставки изменилась после проверки расчётного листа.",
  payroll_rate_obligation_unmapped: "Для одной или нескольких ставок не указано обязательство (подоходный налог, ФСЗН или страхование от несчастных случаев).",
  payroll_rate_obligation_unreviewed: "Применимость указанного обязательства главбухом не рассмотрена или не определена.",
  payroll_rate_conflicts_with_organization_review: "Ставка включена в расчёт, хотя обзор организации помечает её обязательство неприменимым.",
  statutory_rule_completeness_unverified: "Полнота применимых удержаний, взносов, вычетов и льгот не подтверждена.",
};
const applicabilityLabels: Record<string, string> = {
  period_income_tax_sources_unverified: "Проверить официальные налоговые правила именно для этого года.",
  period_income_tax_withholding_rule: "Утвердить правило удержания подоходного налога для периода и вида дохода.",
  period_fszn_rules_and_limits: "Подтвердить применимые правила и ограничения взносов ФСЗН.",
  period_work_injury_insurance_tariff: "Подтвердить тариф страхования от несчастных случаев этого юрлица.",
  income_kind_and_tax_agent_treatment: "Вид дохода и порядок действий налогового агента",
  year_to_date_taxable_income: "Накопленный облагаемый доход за год",
  main_workplace_and_deduction_basis: "Основное место работы и основание стандартного вычета",
  dependants_special_status_and_deduction_documents: "Дети, иждивенцы, особый статус и подтверждающие документы",
  other_deduction_claims_and_documents: "Другие заявленные вычеты и подтверждающие документы",
  insurance_applicability_and_base: "Страховой статус и база для взносов",
};
const referenceLabels: Record<string, string> = {
  income_tax_rate_categories: "виды доходов и категории ставок",
  standard_deductions_and_main_workplace: "стандартные вычеты и основное место работы",
  deduction_categories: "виды налоговых вычетов",
};
const organizationRuleCodes = [
  "period_income_tax_withholding_rule",
  "period_fszn_rules_and_limits",
  "period_work_injury_insurance_tariff",
];
const obligationTitles: Record<string, string> = {
  period_income_tax_withholding_rule: "Подоходный налог",
  period_fszn_rules_and_limits: "Взносы ФСЗН",
  period_work_injury_insurance_tariff: "Страхование от несчастных случаев",
};

function validOrganizationApplicability(candidate: Candidate) {
  const review = candidate.applicability.organization;
  if (!review || typeof review !== "object" || !Array.isArray(review.reviewed_rule_codes)
      || !Array.isArray(review.unresolved_rule_codes) || !Array.isArray(candidate.applicability.organization_gap_codes)) return false;
  const reviewed = review.reviewed_rule_codes;
  const unresolved = review.unresolved_rule_codes;
  const known = (codes: string[]) => codes.every((code) => organizationRuleCodes.includes(code))
    && new Set(codes).size === codes.length;
  const reviewShape = review.review_id === null
    ? review.review_digest === null && reviewed.length === 0
      && unresolved.length === organizationRuleCodes.length
    : Number.isInteger(review.review_id) && review.review_id > 0
      && typeof review.review_digest === "string" && /^[a-f0-9]{64}$/.test(review.review_digest);
  const rates = candidate.applicability.rate_obligations;
  const decisions = review.rule_decisions ?? {};
  const decisionsShape = rates === undefined || (review.rule_decisions !== null
    && typeof review.rule_decisions === "object" && !Array.isArray(review.rule_decisions)
    && Object.entries(decisions).every(([code, decision]) =>
      organizationRuleCodes.includes(code) && ["applicable", "not_applicable", "unresolved"].includes(decision)));
  const ratesShape = rates === undefined || (Array.isArray(rates) && rates.every((row) =>
    typeof row.rate_code === "string" && row.rate_code.length > 0
    && (row.obligation_code === null || organizationRuleCodes.includes(row.obligation_code))
    && row.chief_decision === (row.obligation_code === null ? null : decisions[row.obligation_code] ?? null))
    && new Set(rates.map((row) => row.rate_code)).size === rates.length);
  return Array.isArray(reviewed) && Array.isArray(unresolved)
    && known(reviewed) && known(unresolved)
    && reviewShape && decisionsShape && ratesShape
    && organizationRuleCodes.every((code) => reviewed.includes(code) !== unresolved.includes(code))
    && organizationRuleCodes.every((code) => candidate.applicability.organization_gap_codes.includes(code));
}

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
    summary: null, comparison: null, candidate: null,
    summaryError: "", comparisonError: "", candidateError: "", loading: true,
  });

  useEffect(() => {
    if (!org || !/^\d{4}-(0[1-9]|1[0-2])$/.test(month)) return;
    const controller = new AbortController();
    void Promise.allSettled([
      readScoped<Summary>("payroll-arithmetic-summary", org, month, controller.signal),
      readScoped<Comparison>("payroll-source-reconciliation", org, month, controller.signal),
      readScoped<Candidate>("payroll-own-candidate", org, month, controller.signal),
    ]).then(([summary, comparison, candidate]) => {
      if (controller.signal.aborted) return;
      const candidateValue = candidate.status === "fulfilled" ? candidate.value : null;
      const candidateSafe = candidateValue?.status === "provisional_payroll_candidate_only"
        && candidateValue.posting_available === false
        && candidateValue.statutory_payroll_certified === false
        && candidateValue.applicability?.status === "facts_and_rules_unverified"
        && candidateValue.applicability.statutory_completeness_verified === false
        && validOrganizationApplicability(candidateValue);
      setLoaded({
        summary: summary.status === "fulfilled" ? summary.value : null,
        comparison: comparison.status === "fulfilled" ? comparison.value : null,
        candidate: candidateSafe ? candidateValue : null,
        summaryError: summary.status === "rejected" ? String(summary.reason?.message ?? summary.reason) : "",
        comparisonError: comparison.status === "rejected" ? String(comparison.reason?.message ?? comparison.reason) : "",
        candidateError: candidate.status === "rejected" ? String(candidate.reason?.message ?? candidate.reason)
          : candidateSafe ? "" : "Ответ черновика имеет неожиданный статус.",
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
        setLoaded({ summary: null, comparison: null, candidate: null, summaryError: "", comparisonError: "", candidateError: "", loading: true });
        setReload((value) => value + 1);
      }}>Обновить контроль</Button>
    </div>
    {!org && <p className="text-sm text-muted">Выберите юридическое лицо.</p>}
    {org && !/^\d{4}-(0[1-9]|1[0-2])$/.test(month) && <p role="alert">Выберите корректный месяц.</p>}
    {loaded.loading && org && <p role="status">Загрузка контроля зарплаты…</p>}

    {loaded.summaryError && <p role="alert" className="text-red-700">Расчётные листы: {loaded.summaryError}</p>}
    {loaded.summary && <div className="space-y-3 rounded-lg border border-line p-4">
      <h3 className="font-semibold">Рассмотренные расчётные отрезки</h3>
      <p className="text-sm text-muted">Квитанций: {loaded.summary.review_count}; действующих редакций отрезков: {loaded.summary.selected_segment_count}; исходные данные подтверждены главбухом для {loaded.summary.source_fact_attested_segment_count} отрезков. Известных активных договоров: {loaded.summary.known_binding_coverage.active_binding_count}.</p>
      {!!loaded.summary.source_fact_unattested_review_ids.length && <p className="text-sm">Без отдельного подтверждения исходных данных: квитанции № {loaded.summary.source_fact_unattested_review_ids.join(", ")}.</p>}
      {loaded.summary.current_file_bytes_verified && <p className="text-xs text-muted">Сохранённые файлы-основания действующих отрезков повторно сверены по байтам. Содержание документов требует отдельного подтверждения главбуха.</p>}
      <dl className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">{amountLabels.map(([key, label]) => <div key={key} className="rounded-lg bg-canvas p-3"><dt className="text-xs text-muted">{label}</dt><dd className="font-semibold tabular-nums">{loaded.summary!.totals[key]} BYN</dd></div>)}</dl>
      <p className="text-sm">{loaded.summary.known_binding_coverage.active_binding_count === 0 ? "На этот месяц нет известных активных договоров. Проверьте реестр работников и основание нулевых начислений." : loaded.summary.known_binding_coverage.known_binding_coverage_complete ? "Все отрезки известных договоров рассмотрены; полнота реального штата не подтверждена." : "Есть нерассмотренные или устаревшие отрезки известных договоров."}</p>
      {!!loaded.summary.known_binding_coverage.issues.length && <ul className="list-disc space-y-1 pl-5 text-sm">{loaded.summary.known_binding_coverage.issues.map((issue, index) => <li key={`${issue.kind}-${issue.employment_binding_id}-${index}`}>{issueLabels[issue.kind] ?? issue.kind}: договор № {issue.employment_binding_id}, {issue.work_from}–{issue.work_to}</li>)}</ul>}
      {!!loaded.summary.bindings.length && <div className="space-y-2">{loaded.summary.bindings.map((binding) => <div key={binding.employment_binding_id} className="rounded-lg border border-line p-3 text-sm"><strong>Договор № {binding.employment_binding_id}</strong><span className="ml-3">Начислено: {binding.totals.gross_byn} BYN</span><span className="ml-3">Отрезков: {binding.segments.length}</span></div>)}</div>}
    </div>}

    {loaded.candidateError && <p role="alert" className="text-red-700">Черновик собственного расчёта: {loaded.candidateError}</p>}
    {loaded.candidate && <div className="space-y-3 rounded-lg border border-line p-4">
      <h3 className="font-semibold">Черновик собственного расчёта</h3>
      <p className="text-sm">Включено подтверждённых отрезков: {loaded.candidate.included_segment_count} из {loaded.candidate.selected_segment_count}. Суммы ниже относятся только к ним и не являются начисленной зарплатой.</p>
      <dl className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">{amountLabels.map(([key, label]) => <div key={key} className="rounded-lg bg-canvas p-3"><dt className="text-xs text-muted">{label}</dt><dd className="font-semibold tabular-nums">{loaded.candidate!.totals[key]} BYN</dd></div>)}</dl>
      <p className="text-sm">{loaded.candidate.arithmetic_scope_complete ? "Исходные расчётные отрезки собраны; нормативная полнота ещё не подтверждена." : "Черновик неполон: проверьте причины ниже."}</p>
      <ul className="list-disc space-y-1 pl-5 text-sm">{loaded.candidate.blockers.map((code) => <li key={code}>{candidateBlockers[code] ?? code}</li>)}</ul>
      {!!loaded.candidate.applicability.rate_obligations?.length && <div className="rounded-lg border border-line p-3 text-sm"><h4 className="font-semibold">Связь ставок с обязательствами</h4><ul className="mt-1 list-disc space-y-1 pl-5">{loaded.candidate.applicability.rate_obligations.map((row) => <li key={row.rate_code}>{row.rate_code}: {row.obligation_code ? obligationTitles[row.obligation_code] ?? row.obligation_code : "обязательство не указано"}; {row.chief_decision === "applicable" ? "главбух отметил применимость" : row.chief_decision === "not_applicable" ? "главбух отметил неприменимость — конфликт" : "применимость не определена"}.</li>)}</ul><p className="mt-1 text-xs text-muted">Сопоставление не подтверждает ставку, базу или нормативную полноту.</p></div>}
      <div className="space-y-2 rounded-lg border border-line p-3 text-sm">
        <h4 className="font-semibold">Что нужно для проверки налоговых условий</h4>
        <p className="text-muted">ERP пока не хранит перечисленные ниже факты по работникам. Список охватывает только известные ERP договоры; отсутствие заявления о вычете нельзя считать нулевым вычетом.</p>
        <p className="text-xs text-muted">Обзор фактов о применимости не закрывает правовые пробелы ниже и не подтверждает полноту расчёта.</p>
        <ul className="list-disc space-y-1 pl-5">{loaded.candidate.applicability.organization_gap_codes.map((code) => <li key={code}>{applicabilityLabels[code] ?? code}</li>)}</ul>
        {loaded.candidate.applicability.organization?.review_id !== null
          && loaded.candidate.applicability.organization?.review_id !== undefined
          && <p data-testid="payroll-organization-review-summary">Фактический обзор организации: квитанция № {loaded.candidate.applicability.organization.review_id}; рассмотрено правил {loaded.candidate.applicability.organization.reviewed_rule_codes.length}; нерешённых {loaded.candidate.applicability.organization.unresolved_rule_codes.length}. Правовые пробелы сохраняются.</p>}
        {loaded.candidate.applicability.bindings.length === 0
          ? <p>Известных договоров нет: сначала подтвердите реестр работников.</p>
          : <details><summary className="cursor-pointer">Данные по договорам: {loaded.candidate.applicability.bindings.length}</summary>
            <div className="mt-2 space-y-2">{loaded.candidate.applicability.bindings.map((binding) => <div key={binding.employment_binding_id} className="rounded border border-line p-2">
              <strong>Договор № {binding.employment_binding_id}</strong>
              {binding.review_id && <p>Квитанция главбуха № {binding.review_id}: рассмотрено фактов {binding.reviewed_fact_codes.length}. Выводы требуют проверки по применимым правилам.</p>}
              <ul className="list-disc pl-5">{binding.unrecorded_fact_codes.map((code) => <li key={code}>{applicabilityLabels[code] ?? code}</li>)}</ul>
            </div>)}</div>
          </details>}
        {loaded.candidate.applicability.references.length > 0
          ? <p className="text-xs text-muted">Проверенные страницы МНС за {loaded.candidate.applicability.reference_year} год описывают только отдельные налоговые условия: {loaded.candidate.applicability.references.map((source, index) => <span key={source.topic}>{index > 0 ? ", " : ""}<a className="underline" href={source.url} target="_blank" rel="noreferrer">{referenceLabels[source.topic] ?? source.topic}</a></span>)}. Они не подтверждают полноту расчёта.</p>
          : <p className="text-xs text-muted">Для {loaded.candidate.applicability.reference_year} года официальные налоговые источники в этом контроле ещё не проверены.</p>}
      </div>
      <AccountingPayrollOrganizationReview org={org} month={month} onReviewed={() => setReload((value) => value + 1)} />
      <AccountingPayrollApplicabilityReview org={org} month={month} bindingIds={loaded.candidate.applicability.bindings.map((row) => row.employment_binding_id)} onReviewed={() => setReload((value) => value + 1)} />
      <p className="break-all text-xs text-muted">Отпечаток исходной версии: {loaded.candidate.candidate_digest}. Проведение, выплата и обязательная отчётность недоступны.</p>
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
