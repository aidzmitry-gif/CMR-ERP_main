import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { AccountingPayrollControl } from "@/components/erp/accounting-payroll-control";

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
      input.includes("payroll-arithmetic-summary") ? data.summary : data.comparison,
    )));
    vi.stubGlobal("fetch", fetchMock);

    render(<AccountingPayrollControl org="7" month="2026-10" onEntry={onEntry} />);
    expect(await screen.findByText("Есть расхождения по договорам: 1.")).toBeInTheDocument();
    expect(screen.getByText(/Нет рассмотренного расчётного отрезка: договор № 10/)).toBeInTheDocument();
    expect(screen.getByText(/полноту работников, применимость ставок/)).toBeInTheDocument();
    expect(screen.getByText(/файлы-основания действующих отрезков повторно сверены по байтам/)).toBeInTheDocument();
    expect(screen.getByText(/Без отдельного подтверждения исходных данных: квитанции № 5/)).toBeInTheDocument();
    expect(screen.getByText(/Удержания: расчёт 10.00, импорт 11.00, разница 1.00 BYN/)).toBeInTheDocument();
    expect(screen.getByText(/Источники для сравнения: собраны; суммы всё ещё могут расходиться/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Начисление · проводка № 41" }));
    expect(onEntry).toHaveBeenCalledWith(41);
    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(fetchMock.mock.calls.every(([url]) => String(url).includes("/organizations/7/periods/2026-10/"))).toBe(true);
  });

  it("rejects a response scoped to another organization", async () => {
    const data = reports(7);
    vi.stubGlobal("fetch", vi.fn((input: string) => Promise.resolve(response(
      input.includes("payroll-arithmetic-summary") ? data.summary : data.comparison,
    ))));
    render(<AccountingPayrollControl org="8" month="2026-10" onEntry={vi.fn()} />);
    const alerts = await screen.findAllByRole("alert");
    expect(alerts).toHaveLength(2);
    expect(alerts[0]).toHaveTextContent("другому юридическому лицу");
    expect(screen.queryByText("100.00 BYN")).not.toBeInTheDocument();
  });

  it("does not call an empty month an uncovered employment interval", async () => {
    const data = reports(7);
    data.summary.known_binding_coverage.active_binding_count = 0;
    data.summary.known_binding_coverage.issues = [];
    data.summary.bindings = [];
    vi.stubGlobal("fetch", vi.fn((input: string) => Promise.resolve(response(
      input.includes("payroll-arithmetic-summary") ? data.summary : data.comparison,
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
      const value = input.includes("payroll-arithmetic-summary") ? "summary" : "comparison";
      if (input.includes("/organizations/7/")) {
        oldSignals.push(init.signal as AbortSignal);
        return new Promise<ReturnType<typeof response>>((resolve) => oldResolvers.push(resolve));
      }
      return Promise.resolve(response(second[value]));
    }));
    const onEntry = vi.fn();
    const { rerender } = render(<AccountingPayrollControl key="7" org="7" month="2026-10" onEntry={onEntry} />);
    rerender(<AccountingPayrollControl key="8" org="8" month="2026-10" onEntry={onEntry} />);
    expect(oldSignals).toHaveLength(2);
    expect(oldSignals.every((signal) => signal.aborted)).toBe(true);
    expect(await screen.findByText("Есть расхождения по договорам: 1.")).toBeInTheDocument();
    await act(async () => {
      oldResolvers[0](response(first.summary));
      oldResolvers[1](response(first.comparison));
    });
    expect(screen.getByText("Есть расхождения по договорам: 1.")).toBeInTheDocument();
    expect(screen.queryByText(/другому юридическому лицу/)).not.toBeInTheDocument();
  });
});
