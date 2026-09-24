import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { AccountingPayrollWorkpaper } from "@/components/erp/accounting-payroll-workpaper";

const rules = {
  rule_set_id: 41, organization_id: 7, policy_id: 3, effective_from: "2026-10-01", revision: 2,
  source_reference: "policy-2026", source_file_id: 90,
  rate_rules: [
    { code: "SYNTHETIC-EMPLOYEE", role: "employee_deduction", base_mode: "gross", classification_evidence: "Synthetic classification" },
    { code: "SYNTHETIC-EMPLOYER", role: "employer_contribution", base_mode: "gross_less_adjustment", classification_evidence: "Synthetic classification" },
  ],
  rate_versions: [
    { code: "SYNTHETIC-EMPLOYEE", requirement_id: 61, requirement_digest: "a".repeat(64) },
    { code: "SYNTHETIC-EMPLOYER", requirement_id: 62, requirement_digest: "b".repeat(64) },
  ],
};
const employment = [{ binding_id: 12, organization_id: 7, employee_id: 27, employee_name: "Тестовый работник", contract_ref: "contract-1", source_document: "signed-contract", personnel_identifier: "worker-a", state: "active", effective_from: "2026-01-01" }];
const sourceFiles = [
  { file_id: 71, organization_id: 7, employment_binding_id: 12, kind: "employment_contract", month: null, reference: "signed-contract", filename: "contract.pdf", content_type: "application/pdf", sha256: "c".repeat(64), size_bytes: 100 },
  { file_id: 72, organization_id: 7, employment_binding_id: 12, kind: "timesheet", month: "2026-10", reference: "timesheet-10", filename: "sheet.pdf", content_type: "application/pdf", sha256: "d".repeat(64), size_bytes: 100 },
  { file_id: 73, organization_id: 7, employment_binding_id: 12, kind: "base_adjustment", month: "2026-10", reference: "adjustment-10", filename: "adjust.pdf", content_type: "application/pdf", sha256: "e".repeat(64), size_bytes: 100 },
  { file_id: 74, organization_id: 7, employment_binding_id: 12, kind: "work_schedule", month: "2026-10", reference: "schedule-10", filename: "schedule.pdf", content_type: "application/pdf", sha256: "f".repeat(64), size_bytes: 100 },
];
const matchingFiles = (input: string) => sourceFiles.filter((row) => row.kind === new URL(input, "http://localhost").searchParams.get("kind"));
const access = { organization_id: 7, can_preview: true, can_upload: true, can_review: true };
const summary = { status: "arithmetic_reviews_aggregate_only", organization_id: 7, month: "2026-10", bindings: [{ employment_binding_id: 12, segments: [{ review_id: 55, revision: 1, work_from: "2026-10-01", work_to: "2026-10-31", basis_digest: "e".repeat(64) }] }] };
const result = {
  status: "arithmetic_workpaper_only", basis_digest: "f".repeat(64),
  gross_byn: "750.00", listed_employee_deductions_byn: "75.00", after_listed_deductions_byn: "675.00",
  listed_employer_contributions_byn: "130.00", cost_including_listed_contributions_byn: "880.00",
  contract_and_timesheet_hashes_verified: true, schedule_file_bytes_verified: true, schedule_numeric_hours_verified: false, rule_source_file_bytes_verified: true,
  posting_available: false, statutory_payroll_certified: false,
  basis: { organization_id: 7, month: "2026-10", employee_name: "Тестовый работник", work_from: "2026-10-01", work_to: "2026-10-31", components: [
    { rate_code: "SYNTHETIC-EMPLOYEE", role: "employee_deduction", base_byn: "750.00", rate_value: "10.00", amount_byn: "75.00" },
    { rate_code: "SYNTHETIC-EMPLOYER", role: "employer_contribution", base_byn: "650.00", rate_value: "20.00", amount_byn: "130.00" },
  ] },
};

const response = (value: unknown) => ({ ok: true, status: 200, json: async () => value });
afterEach(() => vi.unstubAllGlobals());

describe("AccountingPayrollWorkpaper", () => {
  it("previews only source-backed arithmetic with the configured rate identities", async () => {
    const fetchMock = vi.fn((input: string, init: RequestInit) => {
      if (input.includes("payroll-rule-sets/current")) return Promise.resolve(response(rules));
      if (input.includes("payroll-workpaper-access")) return Promise.resolve(response(access));
      if (input.includes("payroll-employments")) return Promise.resolve(response(employment));
      if (input.includes("payroll-evidence-files")) return Promise.resolve(response(matchingFiles(input).map((file) => file.kind === "work_schedule"
        ? { ...file, filename: "schedule.xlsx", content_type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" } : file)));
      if (input.includes("payroll-workpaper-preview")) return Promise.resolve(response({
        ...result, schedule_numeric_hours_verified: true,
        basis: { ...result.basis, work_schedule_cell: "B5" },
      }));
      if (input.includes("payroll-arithmetic-summary")) return Promise.resolve(response(summary));
      if (input.includes("payroll-workpaper-reviews") && init.method === "POST") {
        const command = JSON.parse(init.body as string);
        return Promise.resolve(response({ review_id: 56, organization_id: 7, employment_binding_id: 12, month: "2026-10", work_from: "2026-10-01", work_to: "2026-10-31", request_key: command.request_key, basis_digest: command.basis_digest, revision: 2, supersedes_review_id: 55, status: "arithmetic_review_only", posting_available: false, statutory_payroll_certified: false }));
      }
      throw new Error(`Unexpected request: ${input} ${init.method}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    render(<AccountingPayrollWorkpaper org="7" month="2026-10" disabled={false} />);
    await screen.findByText(/Набор правил № 41/);
    fireEvent.change(screen.getByLabelText("Договор работника"), { target: { value: "12" } });
    await screen.findByRole("option", { name: /timesheet-10/ });
    fireEvent.change(screen.getByLabelText("Файл договора"), { target: { value: "71" } });
    fireEvent.change(screen.getByLabelText("Файл табеля"), { target: { value: "72" } });
    fireEvent.change(screen.getByLabelText("Файл графика работы"), { target: { value: "74" } });
    fireEvent.change(screen.getByLabelText("Ячейка нормы XLSX"), { target: { value: "b5" } });
    fireEvent.change(screen.getByLabelText("Оклад по договору"), { target: { value: "1500.00" } });
    fireEvent.change(screen.getByLabelText("Норма часов"), { target: { value: "160.00" } });
    fireEvent.change(screen.getByLabelText("Отработано часов"), { target: { value: "80.00" } });
    fireEvent.change(screen.getByLabelText("Основание оклада"), { target: { value: "Строка оклада в договоре" } });
    fireEvent.change(screen.getByLabelText("Основание часов"), { target: { value: "Часы в подписанном табеле" } });
    fireEvent.change(screen.getByLabelText("Основание нормы часов"), { target: { value: "Утверждённая норма в графике" } });
    fireEvent.change(screen.getByLabelText("Корректировка SYNTHETIC-EMPLOYER"), { target: { value: "100.00" } });
    fireEvent.change(screen.getByLabelText("Файл корректировки SYNTHETIC-EMPLOYER"), { target: { value: "73" } });
    fireEvent.change(screen.getByLabelText("Основание корректировки SYNTHETIC-EMPLOYER"), { target: { value: "Пункт документа о корректировке" } });
    fireEvent.click(screen.getByRole("button", { name: "Проверить арифметику" }));
    await screen.findByText("Предварительный результат");
    const posts = fetchMock.mock.calls.filter(([, init]) => init.method === "POST");
    expect(posts).toHaveLength(1);
    expect(String(posts[0][0])).toContain("/organizations/7/periods/2026-10/payroll-workpaper-preview");
    const body = JSON.parse(posts[0][1].body as string);
    expect(body).toMatchObject({
      policy_id: 3, rule_set_id: 41, employment_binding_id: 12,
      monthly_salary_byn: "1500.00", month_norm_hours: "160.00", worked_hours: "80.00",
      contract_file_id: 71, contract_digest: "c".repeat(64), timesheet_file_id: 72, timesheet_digest: "d".repeat(64),
      work_schedule_file_id: 74, work_schedule_digest: "f".repeat(64), work_schedule_cell: "B5", norm_hours_evidence: "Утверждённая норма в графике",
      components: [{ requirement_id: 61, adjustment_byn: "0.00" }, { requirement_id: 62, adjustment_byn: "100.00", adjustment_file_id: 73 }],
    });
    expect(screen.getByText(/не сумма зарплаты к выплате/)).toBeInTheDocument();
    expect(screen.getByText(/сверен по ячейке B5/)).toHaveTextContent("подлинность и применимость графика подтверждает бухгалтер");
    expect(await screen.findByText(/Исправление квитанции № 55/)).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Основание проверки главбуха"), { target: { value: "Проверены строки договора, табеля и корректировки" } });
    fireEvent.click(screen.getByRole("button", { name: "Подтвердить исправление" }));
    expect(await screen.findByText(/Квитанция № 56, редакция 2, сохранена без проводок/)).toBeInTheDocument();
    const reviewPosts = fetchMock.mock.calls.filter(([url, init]) => String(url).includes("payroll-workpaper-reviews") && init.method === "POST");
    expect(reviewPosts).toHaveLength(1);
    expect(JSON.parse(reviewPosts[0][1].body as string)).toMatchObject({ request_key: expect.any(String), basis_digest: "f".repeat(64), supersedes_review_id: 55, reviewer_evidence: "Проверены строки договора, табеля и корректировки" });
  });

  it("rejects foreign-organization sources before rendering a preview", async () => {
    vi.stubGlobal("fetch", vi.fn((input: string) => Promise.resolve(response(
      input.includes("payroll-rule-sets/current") ? { ...rules, organization_id: 8 } : input.includes("payroll-workpaper-access") ? access : employment,
    ))));
    render(<AccountingPayrollWorkpaper org="7" month="2026-10" disabled={false} />);
    expect(await screen.findByRole("alert")).toHaveTextContent("другому юридическому лицу");
    expect(screen.queryByRole("button", { name: "Проверить арифметику" })).not.toBeInTheDocument();
  });

  it("does not preview with missing salary, hours or source documents", async () => {
    const fetchMock = vi.fn((input: string) => Promise.resolve(response(
      input.includes("payroll-rule-sets/current") ? rules : input.includes("payroll-workpaper-access") ? access : input.includes("payroll-employments") ? employment : matchingFiles(input),
    )));
    vi.stubGlobal("fetch", fetchMock);
    render(<AccountingPayrollWorkpaper org="7" month="2026-10" disabled={false} />);
    await screen.findByText(/Набор правил № 41/);
    fireEvent.change(screen.getByLabelText("Договор работника"), { target: { value: "12" } });
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(7));
    expect(screen.getByRole("button", { name: "Проверить арифметику" })).toBeDisabled();
    expect(fetchMock.mock.calls.every(([url]) => !String(url).includes("payroll-workpaper-preview"))).toBe(true);
  });

  it("shows XLSX row defects and blocks chief arithmetic confirmation", async () => {
    const xlsxFiles = sourceFiles.map((file) => file.kind === "timesheet"
      ? { ...file, filename: "sheet.xlsx", content_type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" }
      : file);
    const fetchMock = vi.fn((input: string) => {
      if (input.includes("timesheet-preflight")) return Promise.resolve(response({
        file_id: 72, organization_id: 7, employment_binding_id: 12, period: "2026-10",
        source_sha256: "d".repeat(64), status: "structure_failed", structure_ok: false,
        document_facts_verified: false, issues: [{ code: "hours_formula_range", rows: [11] }],
      }));
      if (input.includes("payroll-rule-sets/current")) return Promise.resolve(response(rules));
      if (input.includes("payroll-workpaper-access")) return Promise.resolve(response(access));
      if (input.includes("payroll-employments")) return Promise.resolve(response(employment));
      if (input.includes("payroll-evidence-files")) return Promise.resolve(response(xlsxFiles.filter(
        (file) => file.kind === new URL(input, "http://localhost").searchParams.get("kind"))));
      if (input.includes("payroll-workpaper-preview")) return Promise.resolve(response(result));
      if (input.includes("payroll-arithmetic-summary")) return Promise.resolve(response(summary));
      throw new Error(`Unexpected request: ${input}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    render(<AccountingPayrollWorkpaper org="7" month="2026-10" disabled={false} />);
    await screen.findByText(/Набор правил № 41/);
    fireEvent.change(screen.getByLabelText("Договор работника"), { target: { value: "12" } });
    await screen.findByRole("option", { name: /timesheet-10/ });
    fireEvent.change(screen.getByLabelText("Файл договора"), { target: { value: "71" } });
    fireEvent.change(screen.getByLabelText("Файл табеля"), { target: { value: "72" } });
    fireEvent.change(screen.getByLabelText("Файл графика работы"), { target: { value: "74" } });
    expect(await screen.findByText(/формула часов охватывает не все дни/)).toHaveTextContent("11");
    fireEvent.change(screen.getByLabelText("Оклад по договору"), { target: { value: "1500.00" } });
    fireEvent.change(screen.getByLabelText("Норма часов"), { target: { value: "160.00" } });
    fireEvent.change(screen.getByLabelText("Отработано часов"), { target: { value: "80.00" } });
    fireEvent.change(screen.getByLabelText("Основание оклада"), { target: { value: "Строка оклада в договоре" } });
    fireEvent.change(screen.getByLabelText("Основание часов"), { target: { value: "Часы в подписанном табеле" } });
    fireEvent.change(screen.getByLabelText("Основание нормы часов"), { target: { value: "Утверждённая норма в графике" } });
    fireEvent.change(screen.getByLabelText("Корректировка SYNTHETIC-EMPLOYER"), { target: { value: "100.00" } });
    fireEvent.change(screen.getByLabelText("Файл корректировки SYNTHETIC-EMPLOYER"), { target: { value: "73" } });
    fireEvent.change(screen.getByLabelText("Основание корректировки SYNTHETIC-EMPLOYER"), { target: { value: "Пункт документа о корректировке" } });
    fireEvent.click(screen.getByRole("button", { name: "Проверить арифметику" }));
    await screen.findByText("Предварительный результат");
    const defectPreview = fetchMock.mock.calls.find(([url]) => String(url).includes("payroll-workpaper-preview"));
    expect(defectPreview).toBeDefined();
    expect(JSON.parse(defectPreview![1].body as string)).not.toHaveProperty("timesheet_row");
    fireEvent.change(screen.getByLabelText("Основание проверки главбуха"), { target: { value: "Проверены договор и табель" } });
    expect(screen.getByRole("button", { name: "Подтвердить исправление" })).toBeDisabled();
    expect(fetchMock.mock.calls.some(([url]) => String(url).includes("payroll-workpaper-reviews"))).toBe(false);
  });

  it("requires an explicit XLSX row and sends it with the arithmetic preview", async () => {
    const xlsxFiles = sourceFiles.map((file) => file.kind === "timesheet"
      ? { ...file, filename: "sheet.xlsx", content_type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" }
      : file);
    const checkedResult = {
      ...result, timesheet_numeric_hours_verified: true, timesheet_name_matches_binding: true,
      timesheet_identifier_matches_binding: true,
      basis: { ...result.basis, timesheet_row: 11, timesheet_uninterpreted_code_days: 1 },
    };
    const fetchMock = vi.fn((input: string) => {
      if (input.includes("timesheet-preflight")) return Promise.resolve(response({
        file_id: 72, organization_id: 7, employment_binding_id: 12, period: "2026-10",
        source_sha256: "d".repeat(64), status: "structure_checked", structure_ok: true,
        employee_row_numbers: [11, 12], document_facts_verified: false, issues: [],
      }));
      if (input.includes("payroll-rule-sets/current")) return Promise.resolve(response(rules));
      if (input.includes("payroll-workpaper-access")) return Promise.resolve(response(access));
      if (input.includes("payroll-employments")) return Promise.resolve(response(employment));
      if (input.includes("payroll-evidence-files")) return Promise.resolve(response(xlsxFiles.filter(
        (file) => file.kind === new URL(input, "http://localhost").searchParams.get("kind"))));
      if (input.includes("payroll-workpaper-preview")) return Promise.resolve(response(checkedResult));
      if (input.includes("payroll-arithmetic-summary")) return Promise.resolve(response(summary));
      throw new Error(`Unexpected request: ${input}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    render(<AccountingPayrollWorkpaper org="7" month="2026-10" disabled={false} />);
    await screen.findByText(/Набор правил № 41/);
    fireEvent.change(screen.getByLabelText("Договор работника"), { target: { value: "12" } });
    await screen.findByRole("option", { name: /timesheet-10/ });
    fireEvent.change(screen.getByLabelText("Файл договора"), { target: { value: "71" } });
    fireEvent.change(screen.getByLabelText("Файл табеля"), { target: { value: "72" } });
    fireEvent.change(screen.getByLabelText("Файл графика работы"), { target: { value: "74" } });
    await screen.findByLabelText("Строка работника в XLSX");
    expect(screen.getByRole("button", { name: "Проверить арифметику" })).toBeDisabled();
    fireEvent.change(screen.getByLabelText("Строка работника в XLSX"), { target: { value: "11" } });
    fireEvent.change(screen.getByLabelText("Оклад по договору"), { target: { value: "1500.00" } });
    fireEvent.change(screen.getByLabelText("Норма часов"), { target: { value: "160.00" } });
    fireEvent.change(screen.getByLabelText("Отработано часов"), { target: { value: "8.00" } });
    fireEvent.change(screen.getByLabelText("Основание оклада"), { target: { value: "Строка оклада в договоре" } });
    fireEvent.change(screen.getByLabelText("Основание часов"), { target: { value: "Первая строка в подписанном табеле" } });
    fireEvent.change(screen.getByLabelText("Основание нормы часов"), { target: { value: "Утверждённая норма в графике" } });
    fireEvent.change(screen.getByLabelText("Корректировка SYNTHETIC-EMPLOYER"), { target: { value: "0.00" } });
    fireEvent.change(screen.getByLabelText("Файл корректировки SYNTHETIC-EMPLOYER"), { target: { value: "73" } });
    fireEvent.change(screen.getByLabelText("Основание корректировки SYNTHETIC-EMPLOYER"), { target: { value: "Проверена корректировка базы" } });
    fireEvent.click(screen.getByRole("button", { name: "Проверить арифметику" }));
    await screen.findByText("Предварительный результат");
    const previewPost = fetchMock.mock.calls.find(([url]) => String(url).includes("payroll-workpaper-preview"));
    expect(previewPost).toBeDefined();
    expect(JSON.parse(previewPost![1].body as string)).toMatchObject({ timesheet_row: 11, worked_hours: "8.00" });
    expect(screen.getByText(/Числовые часы проверены по строке 11/)).toHaveTextContent("не интерпретированы");
    expect(screen.getByText(/ФИО и табельный номер строки совпали/)).toHaveTextContent("подлинность источника подтверждает бухгалтер");
    expect(fetchMock.mock.calls.some(([url]) => String(url).includes("payroll-workpaper-reviews"))).toBe(false);
  });

  it("blocks XLSX payroll when the employer binding has no personnel number", async () => {
    const xlsxFiles = sourceFiles.map((file) => file.kind === "timesheet"
      ? { ...file, filename: "sheet.xlsx", content_type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" }
      : file);
    let registered = false;
    const fetchMock = vi.fn((input: string, init: RequestInit) => {
      if (input.includes("timesheet-preflight")) return Promise.resolve(response({
        file_id: 72, organization_id: 7, employment_binding_id: 12, period: "2026-10",
        source_sha256: "d".repeat(64), status: "structure_checked", structure_ok: true,
        employee_row_numbers: [11], document_facts_verified: false, issues: [],
      }));
      if (input.includes("payroll-rule-sets/current")) return Promise.resolve(response(rules));
      if (input.includes("payroll-workpaper-access")) return Promise.resolve(response(access));
      if (input.includes("payroll-employments") && init.method === "POST") {
        registered = true;
        return Promise.resolve(response({ ...employment[0], binding_id: 19, effective_from: "2026-10-01" }));
      }
      if (input.includes("payroll-employments")) return Promise.resolve(response([
        registered ? { ...employment[0], binding_id: 19, effective_from: "2026-10-01" }
          : { ...employment[0], personnel_identifier: null },
      ]));
      if (input.includes("payroll-evidence-files")) return Promise.resolve(response(
        input.includes("employment_binding_id=19") ? [] : xlsxFiles.filter(
        (file) => file.kind === new URL(input, "http://localhost").searchParams.get("kind"))));
      throw new Error(`Unexpected request: ${input}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    render(<AccountingPayrollWorkpaper org="7" month="2026-10" disabled={false} />);
    await screen.findByText(/Набор правил № 41/);
    fireEvent.change(screen.getByLabelText("Договор работника"), { target: { value: "12" } });
    await screen.findByRole("option", { name: /timesheet-10/ });
    fireEvent.change(screen.getByLabelText("Файл табеля"), { target: { value: "72" } });
    expect(await screen.findByRole("alert")).toHaveTextContent("табельный номер");
    expect(screen.getByRole("button", { name: "Проверить арифметику" })).toBeDisabled();
    expect(fetchMock.mock.calls.some(([url]) => String(url).includes("payroll-workpaper-preview"))).toBe(false);
    fireEvent.change(screen.getByLabelText("Табельный номер работника"), { target: { value: "worker-a" } });
    fireEvent.change(screen.getByLabelText("Основание табельного номера"), { target: { value: "Номер проверен по кадровому реестру" } });
    fireEvent.click(screen.getByRole("button", { name: "Сохранить новую редакцию договора" }));
    expect(await screen.findByText(/Новая редакция привязки сохранена/)).toBeInTheDocument();
    const post = fetchMock.mock.calls.find(([url, init]) => String(url).includes("payroll-employments") && init.method === "POST");
    expect(post).toBeDefined();
    expect(JSON.parse(post![1].body as string)).toMatchObject({
      request_key: expect.any(String), employee_id: 27, effective_from: "2026-10-01",
      personnel_identifier: "worker-a", personnel_identifier_evidence: "Номер проверен по кадровому реестру",
    });
    expect(screen.getByLabelText("Договор работника")).toHaveValue("19");
  });
});
