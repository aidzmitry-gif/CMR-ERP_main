import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { AccountingPayrollControl } from "@/components/erp/accounting-payroll-control";

vi.mock("@/components/erp/accounting-payroll-applicability-review", () => ({
  AccountingPayrollApplicabilityReview: () => null,
}));
vi.mock("@/components/erp/accounting-payroll-organization-review", () => ({
  AccountingPayrollOrganizationReview: () => null,
}));

const amounts = {
  gross_byn: "100.00",
  listed_employee_deductions_byn: "10.00",
  after_listed_deductions_byn: "90.00",
  listed_employer_contributions_byn: "20.00",
  cost_including_listed_contributions_byn: "120.00",
};

function reports(organizationId: number) {
  return {
    summary: {
      organization_id: organizationId, month: "2026-10", review_count: 2,
      selected_segment_count: 1, source_fact_attested_segment_count: 0,
      source_fact_unattested_review_ids: [5], totals: amounts, current_file_bytes_verified: true,
      statutory_payroll_certified: false,
      bindings: [{ employment_binding_id: 9, segments: [{ review_id: 5, revision: 2, work_from: "2026-10-01", work_to: "2026-10-31" }], totals: amounts }],
      known_binding_coverage: {
        active_binding_count: 2, known_binding_coverage_complete: false,
        issues: [{ kind: "unreviewed_interval", employment_binding_id: 10, work_from: "2026-10-01", work_to: "2026-10-31" }],
      },
    },
    comparison: {
      organization_id: organizationId, month: "2026-10", status: "differences",
      comparison_ready: true, population_review_current: true,
      known_workpaper_coverage_complete: false, differing_binding_count: 1,
      receipt_entry_ids: { gross: [41], statutory: [42] },
      receipt_gaps: { gross: 0, statutory: 0 },
      unmapped_source_lines: { gross: 0, statutory: 0 },
      missing_gross_binding_ids: [10], missing_statutory_binding_ids: [],
      conflicting_statutory_zero_binding_ids: [], unmatched_import_binding_ids: [],
      bindings: [{ employment_binding_id: 9, known_active: true,
        reviewed: { gross_byn: "100.00", listed_employee_deductions_byn: "10.00", listed_employer_contributions_byn: "20.00" },
        imported: { gross_byn: "100.00", listed_employee_deductions_byn: "11.00", listed_employer_contributions_byn: "20.00" },
        difference_import_less_review: { gross_byn: "0.00", listed_employee_deductions_byn: "1.00", listed_employer_contributions_byn: "0.00" },
      }],
      source_facts_verified: false, statutory_payroll_certified: false,
    },
    candidate: {
      organization_id: organizationId, month: "2026-10",
      status: "provisional_payroll_candidate_only", candidate_digest: "a".repeat(64),
      included_segment_count: 0, selected_segment_count: 1,
      unattested_review_ids: [5], totals: { ...amounts, gross_byn: "0.00" },
      blockers: ["source_facts_not_attested", "payroll_rate_obligation_unreviewed", "statutory_rule_completeness_unverified"],
      arithmetic_scope_complete: false, posting_available: false,
      statutory_payroll_certified: false,
      applicability: {
        status: "facts_and_rules_unverified", population_scope: "known_erp_bindings_only",
        reference_year: 2026, reference_scope: "selected_mns_topics_only",
        references: [{ topic: "standard_deductions_and_main_workplace", url: "https://nalog.gov.by/individuals/income_taxation/tax_deductions/9332/" }],
        organization_gap_codes: ["period_income_tax_withholding_rule", "period_fszn_rules_and_limits", "period_work_injury_insurance_tariff"],
        organization: { review_id: 18, review_digest: "c".repeat(64),
          reviewed_rule_codes: ["period_fszn_rules_and_limits", "period_income_tax_withholding_rule"],
          unresolved_rule_codes: ["period_work_injury_insurance_tariff"],
          rule_decisions: { period_fszn_rules_and_limits: "applicable", period_income_tax_withholding_rule: "applicable",
            period_work_injury_insurance_tariff: "unresolved" } },
        rate_obligations: [{ rate_code: "SYNTHETIC-RATE", obligation_code: "period_work_injury_insurance_tariff",
          chief_decision: "unresolved" }],
        bindings: [{ employment_binding_id: 9, review_id: null, review_digest: null,
          reviewed_fact_codes: [], unrecorded_fact_codes: ["main_workplace_and_deduction_basis", "year_to_date_taxable_income"] }],
        statutory_completeness_verified: false,
      },
    },
  };
}

function response(value: unknown) {
  return { ok: true, json: async () => value };
}

afterEach(() => vi.unstubAllGlobals());

describe("AccountingPayrollControl", () => {
  it("shows provisional coverage, differences and source ledger entries", async () => {
    const data = reports(7);
    const onEntry = vi.fn();
    const fetchMock = vi.fn((input: string) => Promise.resolve(response(
      input.includes("payroll-own-candidate") ? data.candidate : input.includes("payroll-arithmetic-summary") ? data.summary : data.comparison,
    )));
    vi.stubGlobal("fetch", fetchMock);

    render(<AccountingPayrollControl org="7" month="2026-10" onEntry={onEntry} />);
    expect(await screen.findByText("Есть расхождения по договорам: 1.")).toBeInTheDocument();
    expect(screen.getByText(/Нет рассмотренного расчётного отрезка: договор № 10/)).toBeInTheDocument();
    expect(screen.getByText(/полноту работников, применимость ставок/)).toBeInTheDocument();
    expect(screen.getByText(/файлы-основания действующих отрезков повторно сверены по байтам/)).toBeInTheDocument();
    expect(screen.getByText(/Без отдельного подтверждения исходных данных: квитанции № 5/)).toBeInTheDocument();
    expect(screen.getByText(/Включено подтверждённых отрезков: 0 из 1/)).toBeInTheDocument();
    expect(screen.getByText(/Полнота применимых удержаний, взносов, вычетов и льгот не подтверждена/)).toBeInTheDocument();
    expect(screen.getByText(/Применимость указанного обязательства главбухом не рассмотрена/)).toBeInTheDocument();
    expect(screen.getByText(/SYNTHETIC-RATE:.*применимость не определена/)).toBeInTheDocument();
    expect(screen.getByText(/Утвердить правило удержания подоходного налога/)).toBeInTheDocument();
    expect(screen.getByTestId("payroll-organization-review-summary")).toHaveTextContent("квитанция № 18; рассмотрено правил 2; нерешённых 1");
    expect(screen.getByText(/Обзор фактов о применимости не закрывает правовые пробелы ниже/)).toBeInTheDocument();
    expect(screen.getByText(/Подтвердить тариф страхования от несчастных случаев этого юрлица/)).toBeInTheDocument();
    fireEvent.click(screen.getByText("Данные по договорам: 1"));
    expect(screen.getByText("Накопленный облагаемый доход за год")).toBeInTheDocument();
    expect(screen.getByText(/Удержания: расчёт 10.00, импорт 11.00, разница 1.00 BYN/)).toBeInTheDocument();
    expect(screen.getByText(/Источники для сравнения: собраны; суммы всё ещё могут расходиться/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Начисление · проводка № 41" }));
    expect(onEntry).toHaveBeenCalledWith(41);
    expect(fetchMock).toHaveBeenCalledTimes(3);
    expect(fetchMock.mock.calls.every(([url]) => String(url).includes("/organizations/7/periods/2026-10/"))).toBe(true);
  });

  it("rejects a response scoped to another organization", async () => {
    const data = reports(7);
    vi.stubGlobal("fetch", vi.fn((input: string) => Promise.resolve(response(
      input.includes("payroll-own-candidate") ? data.candidate : input.includes("payroll-arithmetic-summary") ? data.summary : data.comparison,
    ))));
    render(<AccountingPayrollControl org="8" month="2026-10" onEntry={vi.fn()} />);
    const alerts = await screen.findAllByRole("alert");
    expect(alerts).toHaveLength(3);
    expect(alerts[0]).toHaveTextContent("другому юридическому лицу");
    expect(screen.queryByText("100.00 BYN")).not.toBeInTheDocument();
  });

  it("hides an inconsistent chief decision in the payroll candidate", async () => {
    const data = reports(7);
    data.candidate.applicability.rate_obligations[0].chief_decision = "applicable";
    vi.stubGlobal("fetch", vi.fn((input: string) => Promise.resolve(response(
      input.includes("payroll-own-candidate") ? data.candidate : input.includes("payroll-arithmetic-summary") ? data.summary : data.comparison,
    ))));
    render(<AccountingPayrollControl org="7" month="2026-10" onEntry={vi.fn()} />);
    expect(await screen.findByRole("alert")).toHaveTextContent("Ответ черновика имеет неожиданный статус");
    expect(screen.queryByText("Связь ставок с обязательствами")).not.toBeInTheDocument();
  });

  it("shows the provisional monthly FSZN ceiling without claiming recalculated contributions", async () => {
    const data = reports(7);
    const wage = { wage_month: "2026-09", wage_byn: "3135.90", published_on: "2026-10-24",
      url: "https://www.belstat.gov.by/example/wage.pdf", source_file_id: 87,
      source_file_sha256: "d".repeat(64) };
    Object.assign(data.candidate.applicability.organization, { fszn_reference_wage: wage });
    Object.assign(data.candidate, { fszn_monthly_cap_preview: {
      scope: "attested_erp_segments_only", month: "2026-10", multiplier: 5,
      reference_wage: wage, ceiling_byn: "15679.50",
      employees: [{ employee_id: 41, review_ids: [101, 102],
        listed_eligible_base_byn: "16000.00", capped_listed_base_byn: "15679.50" }],
      all_selected_segments_attested: true, statutory_base_certified: false,
      contributions_recalculated: false,
    } });
    const minimum = { wage_month: "2026-10", wage_byn: "858.00", published_on: "2026-07-13",
      url: "https://nalog.gov.by/news/36005/", source_file_id: 88,
      source_file_sha256: "e".repeat(64), source_locator: "page 1, amount" };
    Object.assign(data.candidate.applicability.organization, { fszn_minimum_wage: minimum });
    Object.assign(data.candidate, { fszn_minimum_preview: {
      scope: "attested_erp_segments_and_listed_rates_only", month: "2026-10", minimum_wage: minimum,
      employees: [{ employee_id: 41, review_ids: [101, 102], status: "comparison", chief_condition: "applies",
        worked_hours: "80.00", full_month_norm_hours: "160.00", time_adjusted_minimum_base_byn: "429.00",
        listed_fszn_components_byn: "60.00", minimum_of_listed_components_byn: "85.80",
        indicative_shortfall_byn: "25.80" }],
      all_selected_segments_attested: true, statutory_minimum_certified: false,
      contributions_recalculated: false,
    } });
    vi.stubGlobal("fetch", vi.fn((input: string) => Promise.resolve(response(
      input.includes("payroll-own-candidate") ? data.candidate : input.includes("payroll-arithmetic-summary") ? data.summary : data.comparison,
    ))));
    render(<AccountingPayrollControl org="7" month="2026-10" onEntry={vi.fn()} />);
    expect(await screen.findByText("Предварительное сравнение с месячным пределом ФСЗН")).toBeInTheDocument();
    expect(screen.getByText(/Работник № 41: показанные базы 16000.00 BYN, после ограничения 15679.50 BYN/)).toBeInTheDocument();
    expect(screen.getByText(/Показанные выше суммы взносов не пересчитаны; проведение и выплата недоступны/)).toBeInTheDocument();
    expect(screen.getByText("Предварительная проверка минимальной суммы ФСЗН · статья 9")).toBeInTheDocument();
    expect(screen.getByText(/ориентир базы 429.00 BYN, минимум перечисленных компонентов 85.80 BYN/)).toBeInTheDocument();
  });

  it("does not call an empty month an uncovered employment interval", async () => {
    const data = reports(7);
    data.summary.known_binding_coverage.active_binding_count = 0;
    data.summary.known_binding_coverage.issues = [];
    data.summary.bindings = [];
    vi.stubGlobal("fetch", vi.fn((input: string) => Promise.resolve(response(
      input.includes("payroll-own-candidate") ? data.candidate : input.includes("payroll-arithmetic-summary") ? data.summary : data.comparison,
    ))));
    render(<AccountingPayrollControl org="7" month="2026-10" onEntry={vi.fn()} />);
    expect(await screen.findByText(/нет известных активных договоров/)).toBeInTheDocument();
    expect(screen.queryByText(/Есть нерассмотренные или устаревшие отрезки/)).not.toBeInTheDocument();
  });

  it("does not show an old organization's late response after a book switch", async () => {
    const first = reports(7);
    const second = reports(8);
    const oldResolvers: ((value: ReturnType<typeof response>) => void)[] = [];
    const oldSignals: AbortSignal[] = [];
    vi.stubGlobal("fetch", vi.fn((input: string, init: RequestInit) => {
      const value = input.includes("payroll-own-candidate") ? "candidate" : input.includes("payroll-arithmetic-summary") ? "summary" : "comparison";
      if (input.includes("/organizations/7/")) {
        oldSignals.push(init.signal as AbortSignal);
        return new Promise<ReturnType<typeof response>>((resolve) => oldResolvers.push(resolve));
      }
      return Promise.resolve(response(second[value]));
    }));
    const onEntry = vi.fn();
    const { rerender } = render(<AccountingPayrollControl key="7" org="7" month="2026-10" onEntry={onEntry} />);
    rerender(<AccountingPayrollControl key="8" org="8" month="2026-10" onEntry={onEntry} />);
    expect(oldSignals).toHaveLength(3);
    expect(oldSignals.every((signal) => signal.aborted)).toBe(true);
    expect(await screen.findByText("Есть расхождения по договорам: 1.")).toBeInTheDocument();
    await act(async () => {
      oldResolvers[0](response(first.summary));
      oldResolvers[1](response(first.comparison));
      oldResolvers[2](response(first.candidate));
    });
    expect(screen.getByText("Есть расхождения по договорам: 1.")).toBeInTheDocument();
    expect(screen.queryByText(/другому юридическому лицу/)).not.toBeInTheDocument();
  });
});
