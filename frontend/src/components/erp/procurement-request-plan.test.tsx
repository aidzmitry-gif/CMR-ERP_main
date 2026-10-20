import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import { ProcurementRequestPlan } from "@/components/erp/procurement-request-plan";

const organizations = [
  { id: 1, name: "Первая", unp: "111111111" },
  { id: 2, name: "Вторая", unp: "222222222" },
];
const json = (body: unknown, status = 200) => ({ ok: status >= 200 && status < 300, status, json: async () => body, text: async () => JSON.stringify(body) });
const requestKey = "10000000-0000-4000-8000-000000000001";
const journalKey = (org: number) => `procurement-request:v1:${org}:tester`;
const command = { request_key: requestKey, document: { supplier: "Учебный поставщик", item: "Учебный товар", qty: 3, amount: "120.00", due_date: null }, ownership_evidence: "Подтверждённый источник" };
const pending = (org: number) => JSON.stringify({ version: 1, org, principal: "tester", nonce: "20000000-0000-4000-8000-000000000002", state: "pending", body: JSON.stringify(command) });
const receipt = (key = requestKey) => ({ organization_id: 1, request_key: key, request_id: 10, ownership_id: 20, number: "REQ-010", stage: "need" });

beforeEach(() => {
  sessionStorage.clear();
  vi.stubGlobal("fetch", vi.fn(async (url: string) => {
    if (url === "/api/system/instance-organization") return json({ configuration: "AIOS_SELLER_UNP", organization: organizations[0] });
    const match = /organizations\/(\d+)\//.exec(url);
    const org = Number(match?.[1]);
    if (url.endsWith("request-plan-context")) return json({ organization_id: org, principal: "tester", can_manage: false });
    if (url.includes("owned-sources")) return json({ organization_id: org, items: [], next_after_id: null });
    throw new Error(`Unexpected request ${url}`);
  }));
});
afterEach(() => vi.unstubAllGlobals());

it("использует настроенную организацию даже при указании другой в ссылке", async () => {
  render(<ProcurementRequestPlan suggestedOrg="2" />);
  expect(await screen.findByText("Доступен просмотр. Для изменения нужен главный бухгалтер этого юрлица с доступом к закупкам.")).toBeInTheDocument();
  expect(screen.getByRole("alert")).toHaveTextContent("другому юрлицу");
  expect(screen.queryByLabelText("Юрлицо плана закупок")).not.toBeInTheDocument();
  expect(vi.mocked(fetch).mock.calls.some(([url]) => String(url).includes("/organizations/2/") || String(url).includes("receipt-organizations"))).toBe(false);
});

it.each(["0", "abc", "3", "2147483648"])("игнорирует недоступный или некорректный org %s", async (suggestedOrg) => {
  render(<ProcurementRequestPlan suggestedOrg={suggestedOrg} />);
  await screen.findByText("Доступен просмотр. Для изменения нужен главный бухгалтер этого юрлица с доступом к закупкам.");
  expect(screen.queryByLabelText("Юрлицо плана закупок")).not.toBeInTheDocument();
  expect(screen.queryByText("Проверка доступа…")).toBeNull();
});

it("ожидает подтверждение компании до запросов плана", async () => {
  const original = vi.mocked(fetch).getMockImplementation()!;
  let resolve!: (value: Response) => void;
  vi.mocked(fetch).mockImplementation((url, options) => String(url).includes("instance-organization") ? new Promise<Response>(done => { resolve = done; }) : original(url, options));
  render(<ProcurementRequestPlan />);
  await screen.findByText("Загрузка юрлица установки…");
  expect(vi.mocked(fetch).mock.calls).toHaveLength(1);
  await act(async () => resolve(json({ configuration: "AIOS_SELLER_UNP", organization: organizations[0] }) as Response));
  await screen.findByRole("button", { name: "Создать заявку" });
});

it("ошибка доступа и её повтор не вызывают запросов к плану", async () => {
  vi.mocked(fetch).mockResolvedValue(json({}, 403) as Response);
  render(<ProcurementRequestPlan />);
  await screen.findByRole("alert");
  fireEvent.click(screen.getByRole("button", { name: "Повторить загрузку юрлица" }));
  await screen.findByRole("alert");
  expect(vi.mocked(fetch).mock.calls).toHaveLength(2);
  expect(vi.mocked(fetch).mock.calls.every(([url]) => url === "/api/system/instance-organization")).toBe(true);
});

it("повторяет ожидающую команду своей компании с теми же bytes и ключом", async () => {
  const original = vi.mocked(fetch).getMockImplementation()!;
  sessionStorage.setItem(journalKey(1), pending(1));
  vi.mocked(fetch).mockImplementation(async (url, options) => {
    if (String(url).endsWith("request-plan-context")) return json({ organization_id: 1, principal: "tester", can_manage: true }) as Response;
    if (options?.method === "POST") return json(receipt()) as Response;
    return original(url, options);
  });
  render(<ProcurementRequestPlan />);
  fireEvent.click(await screen.findByRole("button", { name: "Повторить сохранённый запрос" }));
  await screen.findByText("Создание подтверждено: REQ-010.");
  const posts = vi.mocked(fetch).mock.calls.filter(([, options]) => options?.method === "POST");
  expect(posts).toHaveLength(1);
  expect(posts[0][0]).toBe("/api/procurement/organizations/1/requests");
  expect(posts[0][1]).toMatchObject({ body: JSON.stringify(command), headers: { "X-Expected-Principal": "tester" } });
  expect(JSON.parse(sessionStorage.getItem(journalKey(1))!).state).toBe("done");
});

it("не читает и не изменяет журнал другой компании", async () => {
  const raw = pending(2);
  sessionStorage.setItem(journalKey(2), raw);
  render(<ProcurementRequestPlan suggestedOrg="2" />);
  await screen.findByText("Доступен просмотр. Для изменения нужен главный бухгалтер этого юрлица с доступом к закупкам.");
  expect(sessionStorage.getItem(journalKey(2))).toBe(raw);
  expect(screen.queryByRole("button", { name: "Повторить сохранённый запрос" })).not.toBeInTheDocument();
  expect(vi.mocked(fetch).mock.calls.some(([, options]) => options?.method)).toBe(false);
});

it("поздний ответ после ухода оставляет точный ожидающий журнал для сверки", async () => {
  const original = vi.mocked(fetch).getMockImplementation()!;
  const raw = pending(1);
  sessionStorage.setItem(journalKey(1), raw);
  let resolve!: (value: Response) => void;
  vi.mocked(fetch).mockImplementation((url, options) => {
    if (String(url).endsWith("request-plan-context")) return Promise.resolve(json({ organization_id: 1, principal: "tester", can_manage: true }) as Response);
    if (options?.method === "POST") return new Promise<Response>(done => { resolve = done; });
    return original(url, options);
  });
  const view = render(<ProcurementRequestPlan />);
  fireEvent.click(await screen.findByRole("button", { name: "Повторить сохранённый запрос" }));
  await waitFor(() => expect(resolve).toBeTypeOf("function"));
  view.unmount();
  await act(async () => resolve(json(receipt()) as Response));
  expect(sessionStorage.getItem(journalKey(1))).toBe(raw);
});

it("не повторяет команду если текущий сотрудник изменился", async () => {
  const original = vi.mocked(fetch).getMockImplementation()!;
  const raw = pending(1); sessionStorage.setItem(journalKey(1), raw);
  let calls = 0;
  vi.mocked(fetch).mockImplementation(async (url, options) => String(url).endsWith("request-plan-context") ? json({ organization_id: 1, principal: ++calls === 1 ? "tester" : "other", can_manage: true }) as Response : original(url, options));
  render(<ProcurementRequestPlan />);
  fireEvent.click(await screen.findByRole("button", { name: "Повторить сохранённый запрос" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("Учётная запись или права изменились");
  expect(vi.mocked(fetch).mock.calls.some(([, options]) => options?.method === "POST")).toBe(false);
  expect(sessionStorage.getItem(journalKey(1))).toBe(raw);
});

it("создаёт заявку в настроенной компании после заполнения подтверждённых данных", async () => {
  const original = vi.mocked(fetch).getMockImplementation()!;
  vi.mocked(fetch).mockImplementation(async (url, options) => {
    if (String(url).endsWith("request-plan-context")) return json({ organization_id: 1, principal: "tester", can_manage: true }) as Response;
    if (options?.method === "POST") return json(receipt(JSON.parse(String(options.body)).request_key)) as Response;
    return original(url, options);
  });
  render(<ProcurementRequestPlan suggestedOrg="2" />);
  const create = await screen.findByRole("button", { name: "Создать заявку" });
  await waitFor(() => expect(create).toBeEnabled());
  for (const [label, value] of [["Поставщик", "Учебный поставщик"], ["Позиция", "Учебный товар"], ["Количество", "3"], ["Плановая сумма (валюта не задана)", "120.00"], ["Основание выбора юрлица", "Подтверждённый источник"]]) fireEvent.change(screen.getByLabelText(label, { exact: true }), { target: { value } });
  fireEvent.click(create);
  await screen.findByText("Создание подтверждено: REQ-010.");
  const posts = vi.mocked(fetch).mock.calls.filter(([, options]) => options?.method === "POST");
  expect(posts).toHaveLength(1);
  expect(posts[0][0]).toBe("/api/procurement/organizations/1/requests");
  expect(JSON.parse(String(posts[0][1]?.body)).document).toEqual(command.document);
});

it("не показывает документы с несовпадающей организацией в ответе", async () => {
  const original = vi.mocked(fetch).getMockImplementation()!;
  vi.mocked(fetch).mockImplementation(async (url, options) => String(url).includes("owned-sources") ? json({ organization_id: 2, items: [{ id: 1, number: "OTHER-REQ" }], next_after_id: null }) as Response : original(url, options));
  render(<ProcurementRequestPlan />);
  expect(await screen.findByRole("alert")).toHaveTextContent("Некорректная страница документов");
  expect(screen.queryByText("OTHER-REQ")).not.toBeInTheDocument();
});
