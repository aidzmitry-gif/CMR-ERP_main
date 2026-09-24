import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { AccountingPayrollOrganizationReview } from "@/components/erp/accounting-payroll-organization-review";

vi.mock("@/components/erp/accounting-payroll-evidence-upload", () => ({
  AccountingPayrollEvidenceUpload: () => null,
}));

const key = "123e4567-e89b-42d3-a456-426614174000";
const source = {
  file_id: 87, organization_id: 7, employment_binding_id: null,
  kind: "payroll_organization_rule", month: "2026-10", reference: "rules-2026-10",
  sha256: "a".repeat(64),
};
const minimumSource = { ...source, file_id: 88, reference: "minimum-wage-2026-10", sha256: "c".repeat(64) };
const ruleCodes = [
  "period_fszn_rules_and_limits",
  "period_income_tax_withholding_rule",
  "period_work_injury_insurance_tariff",
] as const;
function response(value: unknown, status = 200) {
  return { ok: status < 400, status, json: async () => value };
}
function savedReceipt(command: Record<string, unknown>, revision = 1) {
  return {
    ...command, review_id: 21, organization_id: 7, month: "2026-10", revision,
    digest: "b".repeat(64), source_file_bytes_verified_now: false,
    statutory_payroll_certified: false, posting_available: false,
  };
}
function fillFacts() {
  for (const code of ruleCodes) {
    fireEvent.change(screen.getByLabelText(`Решение ${code}`), { target: { value: code === ruleCodes[0] ? "not_applicable" : "applicable" } });
    fireEvent.change(screen.getByLabelText(`Вывод ${code}`), { target: { value: `Synthetic factual finding for ${code}` } });
    fireEvent.change(screen.getByLabelText(`Место ${code}`), { target: { value: `page 2, ${code}` } });
  }
  fireEvent.change(screen.getByLabelText("Пояснение проверки правил организации"), {
    target: { value: "Главбух проверил указанные пункты документа" },
  });
}

afterEach(() => { vi.unstubAllGlobals(); vi.clearAllMocks(); });

describe("AccountingPayrollOrganizationReview", () => {
  it("can review only the FSZN wage source without claiming the other two rules", async () => {
    let saved: Record<string, unknown> | null = null;
    const fetchMock = vi.fn((url: string, init?: RequestInit) => {
      if (url.endsWith("/payroll-workpaper-access")) return Promise.resolve(response({ organization_id: 7, can_review: true }));
      if (url.includes("/payroll-evidence-files?")) return Promise.resolve(response([source, minimumSource]));
      if (url.endsWith("/payroll-organization-reviews/current")) return Promise.resolve(saved ? response({ ...saved, source_file_bytes_verified_now: true }) : response({}, 404));
      if (url.endsWith("/payroll-organization-reviews") && init?.method === "POST") {
        const command = JSON.parse(String(init.body));
        saved = savedReceipt({ ...command, facts: command.facts.map((fact: Record<string, unknown>) =>
          fact.reference_wage_byn === undefined ? fact : { ...fact, reference_wage_byn: "3135.90" }) });
        return Promise.resolve(response(saved));
      }
      throw new Error(`Unexpected request: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    vi.stubGlobal("crypto", { randomUUID: () => key });
    render(<AccountingPayrollOrganizationReview org="7" month="2026-10" onReviewed={vi.fn()} />);
    await screen.findByLabelText("Файл правил организации для обзора");
    fireEvent.change(screen.getByLabelText("Файл правил организации для обзора"), { target: { value: "87" } });
    fireEvent.change(screen.getByLabelText(`Решение ${ruleCodes[0]}`), { target: { value: "applicable" } });
    fireEvent.change(screen.getByLabelText(`Вывод ${ruleCodes[0]}`), { target: { value: "Synthetic wage finding for this employer" } });
    fireEvent.change(screen.getByLabelText(`Место ${ruleCodes[0]}`), { target: { value: "page 1, country value" } });
    fireEvent.change(screen.getByLabelText("Месяц средней зарплаты Белстата"), { target: { value: "2026-09" } });
    fireEvent.change(screen.getByLabelText("Средняя зарплата Белстата BYN"), { target: { value: "003135.90" } });
    fireEvent.change(screen.getByLabelText("Дата публикации Белстата"), { target: { value: "2026-10-24" } });
    fireEvent.change(screen.getByLabelText("Ссылка на источник Белстата"), { target: { value: "https://www.belstat.gov.by/example/wage.pdf" } });
    fireEvent.change(screen.getByLabelText("Месяц МЗП ФСЗН"), { target: { value: "2026-10" } });
    fireEvent.change(screen.getByLabelText("МЗП ФСЗН BYN"), { target: { value: "000858" } });
    fireEvent.change(screen.getByLabelText("Дата публикации МЗП ФСЗН"), { target: { value: "2026-07-13" } });
    fireEvent.change(screen.getByLabelText("Ссылка на источник МЗП ФСЗН"), { target: { value: "https://nalog.gov.by/news/36005/" } });
    fireEvent.change(screen.getByLabelText("Файл источника МЗП ФСЗН"), { target: { value: "88" } });
    fireEvent.change(screen.getByLabelText("Место МЗП ФСЗН"), { target: { value: "page 1, amount" } });
    fireEvent.change(screen.getByLabelText("Пояснение проверки правил организации"), { target: { value: "Проверен отдельный источник месячной средней зарплаты" } });
    fireEvent.click(screen.getByRole("button", { name: "Сохранить фактический обзор" }));
    expect(await screen.findByText(/Текущая редакция № 1, квитанция № 21/)).toBeInTheDocument();
    const post = fetchMock.mock.calls.find(([url, init]) => String(url).endsWith("/payroll-organization-reviews") && init?.method === "POST");
    expect(JSON.parse(String(post?.[1]?.body)).facts).toMatchObject([{
      reference_wage_byn: "3135.90", minimum_wage_byn: "858.00",
      minimum_wage_source_file_id: 88, minimum_wage_source_file_sha256: minimumSource.sha256,
    }]);
  });

  it("saves sorted factual rule decisions as an organization and month scoped revision", async () => {
    let saved: Record<string, unknown> | null = {
      review_id: 20, organization_id: 7, month: "2026-10", revision: 3, supersedes_id: 19,
      source_file_id: 87, source_document: "rules-2026-10",
      facts: ruleCodes.map((code) => ({ code, decision: "unresolved", finding: `Previous finding for ${code}`, source_locator: `page 1, ${code}` })),
      evidence: "Previous reviewed values saved with factual source references",
      request_key: "old-review-key", digest: "c".repeat(64), source_file_bytes_verified_now: true,
      statutory_payroll_certified: false, posting_available: false,
    };
    const onReviewed = vi.fn();
    const fetchMock = vi.fn((url: string, init?: RequestInit) => {
      if (url.endsWith("/payroll-workpaper-access")) return Promise.resolve(response({ organization_id: 7, can_review: true, can_upload: true }));
      if (url.includes("/payroll-evidence-files?")) return Promise.resolve(response([source]));
      if (url.endsWith("/payroll-organization-reviews/current")) {
        return Promise.resolve(saved ? response({ ...saved, source_file_bytes_verified_now: true }) : response({ detail: "not found" }, 404));
      }
      if (url.endsWith("/payroll-organization-reviews") && init?.method === "POST") {
        const command = JSON.parse(String(init.body));
        saved = savedReceipt(command, 4);
        return Promise.resolve(response(saved));
      }
      throw new Error(`Unexpected request: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    vi.stubGlobal("crypto", { randomUUID: () => key });
    render(<AccountingPayrollOrganizationReview org="7" month="2026-10" onReviewed={onReviewed} />);
    await screen.findByLabelText("Файл правил организации для обзора");
    fireEvent.change(screen.getByLabelText("Файл правил организации для обзора"), { target: { value: "87" } });
    fillFacts();
    fireEvent.change(screen.getByLabelText(`Решение ${ruleCodes[0]}`), { target: { value: "applicable" } });
    fireEvent.change(screen.getByLabelText("Месяц средней зарплаты Белстата"), { target: { value: "2026-09" } });
    fireEvent.change(screen.getByLabelText("Средняя зарплата Белстата BYN"), { target: { value: "3135.9" } });
    fireEvent.change(screen.getByLabelText("Дата публикации Белстата"), { target: { value: "2026-10-24" } });
    fireEvent.change(screen.getByLabelText("Ссылка на источник Белстата"), { target: { value: "https://www.belstat.gov.by/example/wage.pdf" } });
    fireEvent.click(screen.getByRole("button", { name: "Сохранить исправление обзора" }));

    expect(await screen.findByText(/Текущая редакция № 4, квитанция № 21/)).toBeInTheDocument();
    expect(onReviewed).toHaveBeenCalledTimes(1);
    const post = fetchMock.mock.calls.find(([url, init]) => String(url).endsWith("/payroll-organization-reviews") && init?.method === "POST");
    const sent = JSON.parse(String(post?.[1]?.body));
    expect(String(post?.[0])).toContain("/organizations/7/periods/2026-10/payroll-organization-reviews");
    expect(sent).toMatchObject({
      request_key: key, source_file_id: 87, source_document: "rules-2026-10",
      supersedes_id: 20, evidence: "Главбух проверил указанные пункты документа",
      facts: [
        { code: ruleCodes[0], decision: "applicable", source_locator: `page 2, ${ruleCodes[0]}`,
          reference_wage_month: "2026-09", reference_wage_byn: "3135.90",
          reference_wage_published_on: "2026-10-24",
          reference_wage_url: "https://www.belstat.gov.by/example/wage.pdf" },
        { code: ruleCodes[1], decision: "applicable", source_locator: `page 2, ${ruleCodes[1]}` },
        { code: ruleCodes[2], decision: "applicable", source_locator: `page 2, ${ruleCodes[2]}` },
      ],
    });
    expect(sent.facts.map((fact: { code: string }) => fact.code)).toEqual([...ruleCodes].sort());
    expect(screen.getByText(/не подтверждает полноту законодательства/)).toBeInTheDocument();
    expect(fetchMock.mock.calls.some(([url]) => String(url).includes("/payroll/accrue") || String(url).includes("/payroll/pay"))).toBe(false);
  });

  it("retries the same idempotent command after a lost response", async () => {
    let posts = 0;
    let saved: Record<string, unknown> | null = null;
    const fetchMock = vi.fn((url: string, init?: RequestInit) => {
      if (url.endsWith("/payroll-workpaper-access")) return Promise.resolve(response({ organization_id: 7, can_review: true }));
      if (url.includes("/payroll-evidence-files?")) return Promise.resolve(response([source]));
      if (url.endsWith("/payroll-organization-reviews/current")) return Promise.resolve(saved ? response({ ...saved, source_file_bytes_verified_now: true }) : response({}, 404));
      if (url.endsWith(`/payroll-organization-reviews/by-request/${key}`)) return Promise.resolve(saved ? response(saved) : response({}, 404));
      if (url.endsWith("/payroll-organization-reviews") && init?.method === "POST") {
        posts += 1;
        const command = JSON.parse(String(init.body)) as Record<string, unknown>;
        if (posts === 1) return Promise.reject(new Error("connection lost"));
        saved = savedReceipt(command);
        return Promise.resolve(response(saved));
      }
      throw new Error(`Unexpected request: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    vi.stubGlobal("crypto", { randomUUID: () => key });
    render(<AccountingPayrollOrganizationReview org="7" month="2026-10" onReviewed={vi.fn()} />);
    await screen.findByLabelText("Файл правил организации для обзора");
    fireEvent.change(screen.getByLabelText("Файл правил организации для обзора"), { target: { value: "87" } });
    fillFacts();
    fireEvent.click(screen.getByRole("button", { name: "Сохранить фактический обзор" }));
    expect(await screen.findByText(/Повторите тот же сохранённый запрос/)).toBeInTheDocument();
    const firstBody = (fetchMock.mock.calls.find(([url, init]) => String(url).endsWith("/payroll-organization-reviews") && init?.method === "POST")?.[1] as RequestInit).body;
    fireEvent.click(screen.getByRole("button", { name: "Проверить или повторить сохранение" }));
    await waitFor(() => expect(screen.getByText(/Текущая редакция № 1/)).toBeInTheDocument());
    const postsSent = fetchMock.mock.calls.filter(([url, init]) => String(url).endsWith("/payroll-organization-reviews") && init?.method === "POST");
    expect(postsSent).toHaveLength(2);
    expect(postsSent[1][1]?.body).toBe(firstBody);
  });

  it("loads a valid partial review without hiding the accountant workspace", async () => {
    const partial = {
      review_id: 21, organization_id: 7, month: "2026-10", revision: 1,
      supersedes_id: null, source_file_id: 87, source_document: "rules-2026-10",
      facts: [{ code: ruleCodes[0], decision: "unresolved", finding: "Source leaves this rule unresolved",
        source_locator: "page 1, paragraph 2" }],
      evidence: "Only one rule was reviewed against the source", request_key: key,
      digest: "b".repeat(64), source_file_bytes_verified_now: true,
      statutory_payroll_certified: false, posting_available: false,
    };
    vi.stubGlobal("fetch", vi.fn((url: string) => {
      if (url.endsWith("/payroll-workpaper-access")) return Promise.resolve(response({ organization_id: 7, can_review: true }));
      if (url.includes("/payroll-evidence-files?")) return Promise.resolve(response([source]));
      if (url.endsWith("/payroll-organization-reviews/current")) return Promise.resolve(response(partial));
      throw new Error(`Unexpected request: ${url}`);
    }));
    render(<AccountingPayrollOrganizationReview org="7" month="2026-10" onReviewed={vi.fn()} />);
    expect(await screen.findByText(/Текущая редакция № 1, квитанция № 21/)).toBeInTheDocument();
    expect(screen.getByLabelText(`Решение ${ruleCodes[0]}`)).toHaveValue("unresolved");
    expect(screen.getByLabelText(`Решение ${ruleCodes[1]}`)).toHaveValue("");
  });

  it("rejects cross-organization files and keeps the review chief-only", async () => {
    const fetchMock = vi.fn((url: string) => {
      if (url.endsWith("/payroll-workpaper-access")) return Promise.resolve(response({ organization_id: 8, can_review: true }));
      if (url.includes("/payroll-evidence-files?")) return Promise.resolve(response([source]));
      if (url.endsWith("/payroll-organization-reviews/current")) return Promise.resolve(response({}, 404));
      throw new Error(`Unexpected request: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    const view = render(<AccountingPayrollOrganizationReview org="7" month="2026-10" onReviewed={vi.fn()} />);
    expect(await screen.findByRole("alert")).toHaveTextContent("другому юридическому лицу");
    view.unmount();

    vi.stubGlobal("fetch", vi.fn((url: string) => {
      if (url.endsWith("/payroll-workpaper-access")) return Promise.resolve(response({ organization_id: 7, can_review: false }));
      if (url.includes("/payroll-evidence-files?")) return Promise.resolve(response([source]));
      if (url.endsWith("/payroll-organization-reviews/current")) return Promise.resolve(response({}, 404));
      throw new Error(`Unexpected request: ${url}`);
    }));
    render(<AccountingPayrollOrganizationReview org="7" month="2026-10" onReviewed={vi.fn()} />);
    expect(await screen.findByText("Сохранить обзор может только главный бухгалтер.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Сохранить фактический обзор" })).not.toBeInTheDocument();
  });
});
