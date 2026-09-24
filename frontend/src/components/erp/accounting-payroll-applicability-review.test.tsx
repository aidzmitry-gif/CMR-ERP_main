import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { AccountingPayrollApplicabilityReview } from "@/components/erp/accounting-payroll-applicability-review";

vi.mock("@/components/erp/accounting-payroll-evidence-upload", () => ({
  AccountingPayrollEvidenceUpload: () => null,
}));

const source = {
  file_id: 7, organization_id: 4, employment_binding_id: 9,
  kind: "payroll_applicability", month: "2026-10", reference: "dossier-1",
  sha256: "a".repeat(64),
};
function response(value: unknown, status = 200) {
  return { ok: status < 400, status, json: async () => value };
}

afterEach(() => vi.unstubAllGlobals());

describe("AccountingPayrollApplicabilityReview", () => {
  it("saves an evidenced chief review as a non-posting revision", async () => {
    let saved: Record<string, unknown> | null = null;
    const onReviewed = vi.fn();
    const fetchMock = vi.fn((input: string, init?: RequestInit) => {
      if (input.endsWith("/payroll-workpaper-access")) return Promise.resolve(response({ organization_id: 4, can_review: true }));
      if (input.includes("/payroll-evidence-files?")) return Promise.resolve(response([source]));
      if (input.endsWith("/payroll-applicability-reviews/9")) {
        return Promise.resolve(saved ? response({ ...saved, source_file_bytes_verified_now: true })
          : response({ detail: "not found" }, 404));
      }
      if (input.endsWith("/payroll-applicability-reviews") && init?.method === "POST") {
        const command = JSON.parse(init.body as string);
        saved = {
          ...command, review_id: 21, organization_id: 4, month: "2026-10", revision: 1,
          digest: "b".repeat(64), posting_available: false, statutory_payroll_certified: false,
        };
        return Promise.resolve(response(saved));
      }
      throw new Error(`Unexpected request: ${input}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    render(<AccountingPayrollApplicabilityReview org="4" month="2026-10" bindingIds={[9]} onReviewed={onReviewed} />);
    await screen.findByRole("option", { name: "dossier-1 · № 7" });
    fireEvent.change(screen.getByLabelText("Файл налоговых условий"), { target: { value: "7" } });
    fireEvent.click(screen.getByLabelText("Основное место работы и стандартный вычет"));
    fireEvent.change(screen.getByLabelText("Вывод main_workplace_and_deduction_basis"), {
      target: { value: "Main workplace asserted in the source dossier" },
    });
    fireEvent.change(screen.getByLabelText("Место main_workplace_and_deduction_basis"), {
      target: { value: "page 1, section 2" },
    });
    fireEvent.click(screen.getByLabelText("Применимость минимальной суммы взносов ФСЗН (статья 9)"));
    fireEvent.change(screen.getByLabelText("Вывод fszn_minimum_condition"), {
      target: { value: "Ordinary employee subject to the source rule" },
    });
    fireEvent.change(screen.getByLabelText("Место fszn_minimum_condition"), {
      target: { value: "page 1, employment category" },
    });
    fireEvent.change(screen.getByLabelText("Решение о минимуме ФСЗН"), {
      target: { value: "applies" },
    });
    fireEvent.change(screen.getByLabelText("Полная норма часов месяца ФСЗН"), {
      target: { value: "160.00" },
    });
    fireEvent.change(screen.getByLabelText("Место полной нормы ФСЗН"), {
      target: { value: "page 1, full-month schedule" },
    });
    fireEvent.change(screen.getByLabelText("Пояснение проверки налоговых условий"), {
      target: { value: "Synthetic chief checked the indicated paragraph" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Подтвердить факты" }));
    await waitFor(() => expect(onReviewed).toHaveBeenCalledTimes(1));
    const sent = JSON.parse((fetchMock.mock.calls.find(([url, init]) =>
      String(url).endsWith("/payroll-applicability-reviews") && init?.method === "POST")?.[1] as RequestInit).body as string);
    expect(sent).toMatchObject({
      employment_binding_id: 9, source_file_id: 7, source_document: "dossier-1", supersedes_id: null,
      facts: [{ code: "fszn_minimum_condition", fszn_minimum_condition: "applies",
        fszn_minimum_full_month_norm_hours: "160.00",
        fszn_minimum_full_norm_locator: "page 1, full-month schedule",
        source_locator: "page 1, employment category" },
      { code: "main_workplace_and_deduction_basis", source_locator: "page 1, section 2" }],
    });
    expect(fetchMock.mock.calls.some(([url]) => String(url).includes("/payroll/accrue") || String(url).includes("/payroll/pay"))).toBe(false);
    expect(await screen.findByText(/Текущая редакция № 1/)).toBeInTheDocument();
  });

  it("does not offer chief review to an accountant", async () => {
    vi.stubGlobal("fetch", vi.fn((input: string) => {
      if (input.endsWith("/payroll-workpaper-access")) return Promise.resolve(response({ organization_id: 4, can_review: false }));
      if (input.includes("/payroll-evidence-files?")) return Promise.resolve(response([]));
      if (input.endsWith("/payroll-applicability-reviews/9")) return Promise.resolve(response({ detail: "not found" }, 404));
      throw new Error(`Unexpected request: ${input}`);
    }));
    render(<AccountingPayrollApplicabilityReview org="4" month="2026-10" bindingIds={[9]} onReviewed={vi.fn()} />);
    await waitFor(() => expect(screen.queryByText("Загрузка оснований…")).not.toBeInTheDocument());
    expect(screen.queryByRole("button", { name: "Подтвердить факты" })).not.toBeInTheDocument();
  });
});
