import { render,resetCompany,waitForCompany } from "@/test/installation-company";
import { fireEvent,screen,waitFor } from "@testing-library/react";
import { afterEach,beforeEach,beforeEach as configureBeforeEach,expect,it,vi } from "vitest";
vi.mock("@/lib/instance-organization", async () => {
 const fixture = await import("@/test/installation-company");
 return { fetchInstanceOrganization: fixture.fetchTestInstanceOrganization };
});

import { ProcurementRequestPlan } from "@/components/erp/procurement-request-plan";

const organizations = [
  { id: 1, name: "Первая", unp: "111111111" },
  { id: 2, name: "Вторая", unp: "222222222" },
];
const json = (body: unknown) => ({ ok: true, json: async () => body });

beforeEach(() => {
  sessionStorage.clear();
  vi.stubGlobal("fetch", vi.fn(async (url: string) => {
    if (url === "/api/procurement/receipt-organizations") return json(organizations);
    const match = /organizations\/(\d+)\//.exec(url);
    const org = Number(match?.[1]);
    if (url.endsWith("request-plan-context")) return json({ organization_id: org, principal: "tester", can_manage: false });
    if (url.includes("owned-sources")) return json({ organization_id: org, items: [], next_after_id: null });
    throw new Error(`Unexpected request ${url}`);
  }));
});
afterEach(() => vi.unstubAllGlobals());

it("предвыбирает только доступное юрлицо после загрузки списка", async () => {
  render(<ProcurementRequestPlan suggestedOrg="2" />);
  await waitForCompany();
  await waitFor(() => expect(screen.getAllByText(new RegExp(`Юрлицо установки ${"2"} ·`)).length).toBeGreaterThan(0));
  expect(await screen.findByText("Доступен просмотр. Для изменения нужен главный бухгалтер этого юрлица с доступом к закупкам.")).toBeInTheDocument();
});

it.each(["0", "abc", "3", "2147483648"])("игнорирует недоступный или некорректный org %s", async (suggestedOrg) => {
  render(<ProcurementRequestPlan suggestedOrg={suggestedOrg} />);
  await waitForCompany();
  expect(await screen.findByRole("alert")).toHaveTextContent("не совпадает");
  expect(fetch).not.toHaveBeenCalled();
  expect(screen.queryByRole("combobox", { name: /Юрлицо|Организация|Компания ячеек|Юридическое лицо/ })).not.toBeInTheDocument();
  expect(screen.queryByText("Проверка доступа…")).toBeNull();
});

configureBeforeEach(() => resetCompany(2));


it.each(["403", "500", "network", "json"])("не показывает внутренние подробности при сбое %s", async mode => {
  const privateDetail = "PRIVATE_PLAN_INTERNAL_DETAILS";
  vi.stubGlobal("fetch", vi.fn(async (url: string) => {
    if (url.endsWith("request-plan-context")) return json({ organization_id: 2, principal: "tester", can_manage: false });
    if (mode === "network") throw new Error(privateDetail);
    if (mode === "json") return { ok: true, json: async () => { throw new Error(privateDetail); } };
    return { ok: false, status: Number(mode), text: async () => privateDetail };
  }));
  render(<ProcurementRequestPlan />);
  await waitForCompany();
  const alert = await screen.findByRole("alert");
  expect(alert).not.toHaveTextContent(privateDetail);
  expect(alert).toHaveTextContent(/доступ|загрузить|связаться|подтверждён/i);
  expect(screen.queryByText("На загруженной странице заявок нет.")).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Создать заявку", exact: true })).toBeDisabled();
});

it("после неизвестного результата сохраняет журнал и повторяет точное тело до подтверждения", async () => {
  const command = { request_key: "00000000-0000-4000-8000-000000000270", document: { supplier: "Учебный поставщик", item: "Учебная позиция", qty: 2, amount: "15.00", due_date: null }, ownership_evidence: "Учебное основание" };
  const key = "procurement-request:v1:2:tester";
  const raw = JSON.stringify({ version: 1, org: 2, principal: "tester", nonce: "00000000-0000-4000-8000-000000000271", state: "pending", body: JSON.stringify(command) });
  sessionStorage.setItem(key, raw);
  const sent: string[] = [];
  vi.stubGlobal("fetch", vi.fn(async (url: string, options?: RequestInit) => {
    if (url.endsWith("request-plan-context")) return json({ organization_id: 2, principal: "tester", can_manage: true });
    if (url.includes("owned-sources")) return json({ organization_id: 2, items: [], next_after_id: null });
    if (url.endsWith("/requests") && options?.method === "POST") {
      sent.push(String(options.body));
      if (sent.length === 1) return { ok: false, status: 502, text: async () => "PRIVATE_POST_INTERNAL_DETAILS" };
      return json({ organization_id: 2, request_key: command.request_key, request_id: 270, ownership_id: 271, number: "REQ-270", stage: "need" });
    }
    throw new Error("Unexpected request");
  }));
  render(<ProcurementRequestPlan />);
  await waitForCompany();
  const retry = await screen.findByRole("button", { name: "Повторить сохранённый запрос", exact: true });
  await waitFor(() => expect(retry).toBeEnabled());
  fireEvent.click(retry);
  expect(await screen.findByRole("alert")).not.toHaveTextContent("PRIVATE_POST_INTERNAL_DETAILS");
  expect(sessionStorage.getItem(key)).toBe(raw);
  expect(screen.getByRole("button", { name: "Создать заявку", exact: true })).toBeDisabled();
  await waitFor(() => expect(retry).toBeEnabled());
  fireEvent.click(retry);
  expect(await screen.findByRole("status")).toHaveTextContent("Создание подтверждено: REQ-270");
  expect(sent).toEqual([JSON.stringify(command), JSON.stringify(command)]);
  const done = JSON.parse(sessionStorage.getItem(key)!);
  expect(done.state).toBe("done");
  expect(done.body).toBe(JSON.stringify(command));
});
