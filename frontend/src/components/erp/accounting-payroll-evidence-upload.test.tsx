import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { AccountingPayrollEvidenceUpload } from "@/components/erp/accounting-payroll-evidence-upload";

const key = "123e4567-e89b-42d3-a456-426614174000";
const response = (value: unknown) => ({ ok: true, status: 200, json: async () => value });
const receipt = (body: Record<string, unknown>) => ({
  file_id: 87, organization_id: 7, employment_binding_id: body.employment_binding_id,
  kind: body.kind, month: body.month, reference: body.reference,
  filename: body.filename, request_key: body.request_key, content_type: "application/pdf",
  sha256: "a".repeat(64), size_bytes: 42,
});

afterEach(() => vi.unstubAllGlobals());

describe("AccountingPayrollEvidenceUpload", () => {
  it("uploads a contract with the explicit employer binding and server receipt", async () => {
    vi.stubGlobal("crypto", { randomUUID: () => key });
    const onUploaded = vi.fn();
    const fetchMock = vi.fn((_url: string, init: RequestInit) => Promise.resolve(response(receipt(JSON.parse(init.body as string)))));
    vi.stubGlobal("fetch", fetchMock);
    render(<AccountingPayrollEvidenceUpload org="7" month="2026-10" bindingId={12} contractReference="signed-contract" disabled={false} onUploaded={onUploaded} />);
    fireEvent.change(screen.getByLabelText("Файл источника зарплаты"), { target: { files: [new File(["%PDF-1.7\nsynthetic"], "contract.pdf", { type: "application/pdf" })] } });
    fireEvent.change(screen.getByLabelText("Пояснение документа"), { target: { value: "Подписанный договор работника" } });
    fireEvent.click(screen.getByRole("button", { name: "Сохранить документ" }));
    expect(await screen.findByText(/Файл № 87 сохранён/)).toBeInTheDocument();
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toContain("/organizations/7/payroll-evidence-files");
    const body = JSON.parse(init.body as string);
    expect(body).toMatchObject({ request_key: key, kind: "employment_contract", employment_binding_id: 12, month: null, reference: "signed-contract", filename: "contract.pdf" });
    expect(body.data_url).toMatch(/^data:application\/pdf;base64,/);
    expect(onUploaded).toHaveBeenCalledWith(expect.objectContaining({ file_id: 87, organization_id: 7, request_key: key }));
  });

  it("recovers an accepted upload after its POST response is lost", async () => {
    vi.stubGlobal("crypto", { randomUUID: () => key });
    const onUploaded = vi.fn();
    let command: Record<string, unknown> | null = null;
    const fetchMock = vi.fn((url: string, init: RequestInit) => {
      if (init.method === "POST") {
        command = JSON.parse(init.body as string);
        return Promise.reject(new Error("connection lost"));
      }
      if (url.endsWith(`/by-request/${key}`) && command) return Promise.resolve(response(receipt(command)));
      throw new Error(`Unexpected request: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    render(<AccountingPayrollEvidenceUpload org="7" month="2026-10" bindingId={12} contractReference="signed-contract" disabled={false} onUploaded={onUploaded} />);
    fireEvent.change(screen.getByLabelText("Файл источника зарплаты"), { target: { files: [new File(["%PDF-1.7\nsynthetic"], "contract.pdf", { type: "application/pdf" })] } });
    fireEvent.change(screen.getByLabelText("Пояснение документа"), { target: { value: "Договор из кадрового архива" } });
    fireEvent.click(screen.getByRole("button", { name: "Сохранить документ" }));
    expect(await screen.findByText(/Файл № 87 сохранён/)).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(onUploaded).toHaveBeenCalledTimes(1);
  });

  it("stores a policy source at organization scope without an employee or month", async () => {
    vi.stubGlobal("crypto", { randomUUID: () => key });
    const onUploaded = vi.fn();
    const fetchMock = vi.fn((_url: string, init: RequestInit) => Promise.resolve(response(receipt(JSON.parse(init.body as string)))));
    vi.stubGlobal("fetch", fetchMock);
    render(<AccountingPayrollEvidenceUpload key="policy-7" org="7" policyOnly disabled={false} onUploaded={onUploaded} />);
    fireEvent.change(screen.getByLabelText("Номер документа"), { target: { value: "policy-2026" } });
    fireEvent.change(screen.getByLabelText("Файл правил зарплаты"), { target: { files: [new File(["%PDF-1.7\nsynthetic"], "policy.pdf", { type: "application/pdf" })] } });
    fireEvent.change(screen.getByLabelText("Пояснение документа"), { target: { value: "Утверждённые правила для юрлица" } });
    fireEvent.click(screen.getByRole("button", { name: "Сохранить документ" }));
    expect(await screen.findByText(/Файл № 87 сохранён/)).toBeInTheDocument();
    expect(JSON.parse(fetchMock.mock.calls[0][1].body as string)).toMatchObject({
      kind: "payroll_policy", employment_binding_id: null, month: null, reference: "policy-2026",
    });
    expect(onUploaded).toHaveBeenCalledWith(expect.objectContaining({ employment_binding_id: null, month: null }));
  });

  it("uploads a monthly work schedule for the selected employer binding", async () => {
    vi.stubGlobal("crypto", { randomUUID: () => key });
    const fetchMock = vi.fn((_url: string, init: RequestInit) => Promise.resolve(response(receipt(JSON.parse(init.body as string)))));
    vi.stubGlobal("fetch", fetchMock);
    render(<AccountingPayrollEvidenceUpload org="7" month="2026-10" bindingId={12} contractReference="signed-contract" disabled={false} onUploaded={vi.fn()} />);
    fireEvent.change(screen.getByLabelText("Вид документа"), { target: { value: "work_schedule" } });
    fireEvent.change(screen.getByLabelText("Номер документа"), { target: { value: "approved-schedule-10" } });
    fireEvent.change(screen.getByLabelText("Файл источника зарплаты"), { target: { files: [new File(["%PDF-1.7\nfictional"], "schedule.pdf", { type: "application/pdf" })] } });
    fireEvent.change(screen.getByLabelText("Пояснение документа"), { target: { value: "График и норма за октябрь" } });
    fireEvent.click(screen.getByRole("button", { name: "Сохранить документ" }));
    expect(await screen.findByText(/Файл № 87 сохранён/)).toBeInTheDocument();
    expect(JSON.parse(fetchMock.mock.calls[0][1].body as string)).toMatchObject({
      kind: "work_schedule", employment_binding_id: 12, month: "2026-10",
      reference: "approved-schedule-10", filename: "schedule.pdf",
    });
  });

  it("keeps an applicability dossier inside the selected employee and month", async () => {
    vi.stubGlobal("crypto", { randomUUID: () => key });
    const fetchMock = vi.fn((_url: string, init: RequestInit) => Promise.resolve(response(receipt(JSON.parse(init.body as string)))));
    vi.stubGlobal("fetch", fetchMock);
    render(<AccountingPayrollEvidenceUpload org="7" month="2026-10" bindingId={12} applicabilityOnly disabled={false} onUploaded={vi.fn()} />);
    fireEvent.change(screen.getByLabelText("Номер документа"), { target: { value: "facts-2026-10" } });
    fireEvent.change(screen.getByLabelText("Файл источника зарплаты"), {
      target: { files: [new File(["%PDF-1.7\nfictional"], "facts.pdf", { type: "application/pdf" })] },
    });
    fireEvent.change(screen.getByLabelText("Пояснение документа"), {
      target: { value: "Подтверждение условий сотрудника" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Сохранить документ" }));
    expect(await screen.findByText(/Файл № 87 сохранён/)).toBeInTheDocument();
    expect(JSON.parse(fetchMock.mock.calls[0][1].body as string)).toMatchObject({
      kind: "payroll_applicability", employment_binding_id: 12, month: "2026-10",
      reference: "facts-2026-10", filename: "facts.pdf",
    });
  });

  it("stores organization rules for the selected month without an employee binding", async () => {
    vi.stubGlobal("crypto", { randomUUID: () => key });
    const onUploaded = vi.fn();
    const fetchMock = vi.fn((_url: string, init: RequestInit) => Promise.resolve(response(receipt(JSON.parse(init.body as string)))));
    vi.stubGlobal("fetch", fetchMock);
    render(<AccountingPayrollEvidenceUpload org="7" month="2026-10" organizationRuleOnly disabled={false} onUploaded={onUploaded} />);
    fireEvent.change(screen.getByLabelText("Номер документа"), { target: { value: "rules-2026-10" } });
    fireEvent.change(screen.getByLabelText("Файл правил организации"), {
      target: { files: [new File(["%PDF-1.7\nfictional"], "rules.pdf", { type: "application/pdf" })] },
    });
    fireEvent.change(screen.getByLabelText("Пояснение документа"), {
      target: { value: "Основания правил для выбранного юридического лица и месяца" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Сохранить документ" }));
    expect(await screen.findByText(/Файл № 87 сохранён/)).toBeInTheDocument();
    expect(JSON.parse(fetchMock.mock.calls[0][1].body as string)).toMatchObject({
      request_key: key, kind: "payroll_organization_rule", employment_binding_id: null,
      month: "2026-10", reference: "rules-2026-10", filename: "rules.pdf",
    });
    expect(onUploaded).toHaveBeenCalledWith(expect.objectContaining({
      organization_id: 7, employment_binding_id: null, kind: "payroll_organization_rule", month: "2026-10",
    }));
  });
});
