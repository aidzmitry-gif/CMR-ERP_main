import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { AccountingPayrollAccrualImport } from "./accounting-payroll-accrual-import";

const fetchMock = vi.fn();
const respond = (data: unknown, ok = true) => Promise.resolve({ ok, status: ok ? 200 : 422, json: async () => data } as Response);
const props = { org: "11", month: "2026-10", policyId: "7", disabled: false };

beforeEach(() => { vi.stubGlobal("fetch", fetchMock); fetchMock.mockReset(); });
afterEach(() => { vi.unstubAllGlobals(); vi.clearAllMocks(); });

describe("AccountingPayrollAccrualImport", () => {
  it("requires a verified source before preview", () => {
    render(<AccountingPayrollAccrualImport {...props} />);
    fireEvent.click(screen.getByRole("button", { name: "Проверить импорт начислений" }));
    expect(screen.getByRole("alert")).toHaveTextContent("SHA-256");
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("shows the reviewed balanced package before confirmation", async () => {
    fetchMock.mockImplementation((url: string) => url.includes("payroll-accrual-import-preview") ? respond({
      organization_id: 11, month: "2026-10", policy_id: 7, source_digest: "a".repeat(64), digest: "b".repeat(64),
      status: "reviewed_verified_payroll", posting_available: true, posted: false,
      statutory_payroll_certified: false, deductions_and_contributions_available: false,
      posting_document: { lines: [{ account: "26", side: "debit", amount: "100.00", dimensions: { employee: "E-1", department: "SALES" } },
        { account: "70", side: "credit", amount: "100.00", dimensions: { employee: "E-1", department: "SALES" } }] },
    }) : Promise.reject(new Error(url)));
    render(<AccountingPayrollAccrualImport {...props} />);
    fireEvent.change(screen.getByLabelText("Digest ведомости"), { target: { value: "a".repeat(64) } });
    fireEvent.change(screen.getByLabelText("Проверил начисления"), { target: { value: "chief" } });
    fireEvent.change(screen.getByLabelText("Основание ведомости"), { target: { value: "Ведомость и сверка за период" } });
    fireEvent.change(screen.getByLabelText("Сотрудник начислений 1"), { target: { value: "E-1" } });
    fireEvent.change(screen.getByLabelText("Подразделение начислений 1"), { target: { value: "SALES" } });
    fireEvent.change(screen.getByLabelText("Сумма начислений 1"), { target: { value: "100.00" } });
    fireEvent.change(screen.getByLabelText("Основание строки начислений 1"), { target: { value: "Ведомость и табель" } });
    fireEvent.click(screen.getByRole("button", { name: "Проверить импорт начислений" }));
    expect(await screen.findByText("Пакет проверен: Дт и Кт сбалансированы. Проводка ещё не создана.")).toBeInTheDocument();
    expect(screen.getByText(/^Итого: 100\.00 BYN/)).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledWith(expect.stringContaining("payroll-accrual-import-preview"), expect.objectContaining({ method: "POST" }));
  });
});
