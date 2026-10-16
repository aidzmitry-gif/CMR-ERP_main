import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";

import { AccountingPayrollRuleSet } from "./accounting-payroll-rule-set";

const key = "123e4567-e89b-42d3-a456-426614174000";
const rate = {
  requirement_id: 31, organization_id: 7, kind: "rate", code: "SYNTHETIC-RATE", title: "Учебная ставка",
  effective_from: "2026-10-01", revision: 2, source_reference: "rate-source", evidence: "Проверенный учебный источник",
  form_version: null, electronic_format_version: null, rate_value: "13", rate_unit: "percent", rate_basis: "начислено",
  request_key: "123e4567-e89b-42d3-a456-426614174001", digest: "a".repeat(64), actor: "chief",
};
const source = {
  file_id: 61, organization_id: 7, employment_binding_id: null, kind: "payroll_policy", month: null,
  reference: "payroll-policy-2026", filename: "policy.pdf", sha256: "b".repeat(64), size_bytes: 123,
  request_key: "123e4567-e89b-42d3-a456-426614174002",
};
const policies = [{ id: 5, effective_from: "2026-01-01", reference: "Учётная политика 2026", normative_verified: true }];
const reply = (data: unknown, status = 200) => ({ ok: status < 400, status, json: async () => data });

function fetcher(options?: { chief?: boolean; files?: typeof source[]; lostPost?: boolean; wrongOrg?: boolean; lookupDenied?: boolean }) {
  let command: Record<string, unknown> | null = null;
  const fetchMock = vi.fn((url: string, init?: RequestInit) => {
    if (url.endsWith("/payroll-workpaper-access")) return Promise.resolve(reply({ organization_id: 7, can_review: options?.chief !== false, can_upload: true }));
    if (url.endsWith("/periods/2026-10/statutory-requirements")) return Promise.resolve(reply([rate]));
    if (url.endsWith("/payroll-evidence-files?kind=payroll_policy")) return Promise.resolve(reply(options?.files ?? [source]));
    if (url.includes("/payroll-rule-sets/current")) return Promise.resolve(reply({ detail: "No rule set" }, 404));
    if (url.endsWith("/payroll-rule-sets") && init?.method === "POST") {
      command = JSON.parse(String(init.body));
      if (options?.lostPost) return Promise.reject(new Error("connection lost"));
      return Promise.resolve(reply({ ...command, rule_set_id: 71, organization_id: options?.wrongOrg ? 8 : 7,
        revision: 1, rate_versions: command?.expected_rate_versions,
        source_document_verified: false, statutory_completeness_verified: false }));
    }
    if (url.endsWith(`/payroll-rule-sets/by-request/${key}`) && options?.lookupDenied) return Promise.resolve(reply({ detail: "Access changed" }, 403));
    if (url.endsWith(`/payroll-rule-sets/by-request/${key}`) && command) return Promise.resolve(reply({
      ...command, rule_set_id: 71, organization_id: options?.wrongOrg ? 8 : 7, revision: 1,
      rate_versions: command.expected_rate_versions, source_document_verified: false,
      statutory_completeness_verified: false,
    }));
    throw new Error(`Unexpected request ${url}`);
  });
  vi.stubGlobal("fetch", fetchMock);
  vi.stubGlobal("crypto", { randomUUID: () => key });
  return fetchMock;
}

async function fill() {
  await screen.findByText("На выбранный месяц набор правил ещё не задан.");
  for (const [label, value] of [
    ["Учётная политика для зарплаты", "5"], ["Файл правил", "61"],
    ["Метод начисления", "monthly_salary_by_hours"], ["Округление зарплаты", "half_up_cent"],
    ["Ставка 1", "SYNTHETIC-RATE"], ["Вид суммы 1", "employee_deduction"], ["База 1", "gross"],
    ["Обязательство 1", "period_income_tax_withholding_rule"],
    ["Основание классификации 1", "Подтверждено главбухом как удержание"],
    ["Основание правил", "Проверены выбранные ставки и метод"],
  ]) fireEvent.change(screen.getByLabelText(label), { target: { value } });
}

afterEach(() => { vi.unstubAllGlobals(); vi.clearAllMocks(); });

it("requires explicit policy, source, method, rate role and basis before creating a scoped rule revision", async () => {
  const fetchMock = fetcher();
  render(<AccountingPayrollRuleSet org="7" month="2026-10" policies={policies} disabled={false} />);
  await screen.findByText("На выбранный месяц набор правил ещё не задан.");
  fireEvent.click(screen.getByRole("button", { name: "Сохранить новую редакцию" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("Выберите действующую подтверждённую учётную политику");
  expect(fetchMock.mock.calls.some(([, init]) => init?.method === "POST")).toBe(false);
  await fill();
  fireEvent.change(screen.getByLabelText("Обязательство 1"), { target: { value: "" } });
  fireEvent.click(screen.getByRole("button", { name: "Сохранить новую редакцию" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("выберите уникальный код, вид, базу, обязательство");
  expect(fetchMock.mock.calls.some(([, init]) => init?.method === "POST")).toBe(false);
  fireEvent.change(screen.getByLabelText("Обязательство 1"), { target: { value: "period_fszn_rules_and_limits" } });
  fireEvent.click(screen.getByRole("button", { name: "Сохранить новую редакцию" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("выберите уникальный код, вид, базу, обязательство");
  fireEvent.change(screen.getByLabelText("Схема ФСЗН 1"), { target: { value: "general" } });
  fireEvent.click(screen.getByRole("button", { name: "Сохранить новую редакцию" }));
  expect(await screen.findByText(/Редакция 1 сохранена/)).toBeInTheDocument();
  const post = fetchMock.mock.calls.find(([url, init]) => url.endsWith("/payroll-rule-sets") && init?.method === "POST");
  const body = JSON.parse(String(post?.[1]?.body));
  expect(body).toMatchObject({ request_key: key, policy_id: 5, effective_from: "2026-10-01",
    source_reference: source.reference, source_digest: source.sha256, source_file_id: 61,
    gross_method: "monthly_salary_by_hours", rounding: "half_up_cent",
    rate_rules: [{ code: rate.code, role: "employee_deduction", base_mode: "gross",
      obligation_code: "period_fszn_rules_and_limits", fszn_scheme: "general" }],
    expected_rate_versions: [{ code: rate.code, requirement_id: 31, requirement_digest: rate.digest }],
  });
  expect(screen.getByText(/Проверка содержания источника и нормативной полноты: не выполнена/)).toBeInTheDocument();
});

it("recovers a lost save response by the same request key", async () => {
  const fetchMock = fetcher({ lostPost: true });
  render(<AccountingPayrollRuleSet org="7" month="2026-10" policies={policies} disabled={false} />);
  await fill();
  fireEvent.click(screen.getByRole("button", { name: "Сохранить новую редакцию" }));
  expect(await screen.findByText(/Редакция 1 сохранена/)).toBeInTheDocument();
  expect(fetchMock.mock.calls.some(([url]) => url.endsWith(`/payroll-rule-sets/by-request/${key}`))).toBe(true);
  expect(fetchMock.mock.calls.filter(([, init]) => init?.method === "POST")).toHaveLength(1);
});

it("retains the request identity when lookup is denied after a lost POST response", async () => {
  const fetchMock = fetcher({ lostPost: true, lookupDenied: true });
  render(<AccountingPayrollRuleSet org="7" month="2026-10" policies={policies} disabled={false} />);
  await fill();
  fireEvent.click(screen.getByRole("button", { name: "Сохранить новую редакцию" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("Access changed");
  expect(screen.getByRole("button", { name: "Проверить или повторить запрос" })).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Проверить или повторить запрос" }));
  const posts = fetchMock.mock.calls.filter(([, init]) => init?.method === "POST");
  expect(posts).toHaveLength(2);
  expect(posts[0][1]?.body).toBe(posts[1][1]?.body);
});

it("keeps accountant access read-only and rejects a cross-organization receipt", async () => {
  fetcher({ chief: false });
  const view = render(<AccountingPayrollRuleSet org="7" month="2026-10" policies={policies} disabled={false} />);
  expect(await screen.findByText("Новую редакцию настраивает главный бухгалтер.")).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Сохранить новую редакцию" })).not.toBeInTheDocument();
  view.unmount();
  fetcher({ wrongOrg: true });
  render(<AccountingPayrollRuleSet org="7" month="2026-10" policies={policies} disabled={false} />);
  await fill();
  fireEvent.click(screen.getByRole("button", { name: "Сохранить новую редакцию" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("Квитанция набора правил не совпадает");
  expect(screen.queryByText(/Редакция 1 сохранена/)).not.toBeInTheDocument();
});
