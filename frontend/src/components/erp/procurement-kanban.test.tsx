import { configureCompany,render,resetCompany,waitForCompany } from "@/test/installation-company";
import { fireEvent,screen,waitFor,within } from "@testing-library/react";
import { afterEach,beforeEach,beforeEach as configureBeforeEach,expect,it,vi } from "vitest";
vi.mock("@/lib/instance-organization", async () => {
 const fixture = await import("@/test/installation-company");
 return { fetchInstanceOrganization: fixture.fetchTestInstanceOrganization };
});

import { ProcurementKanban } from "@/components/erp/procurement-kanban";

const json = (body: unknown, status = 200) => ({ ok: status >= 200 && status < 300, status, text: async () => JSON.stringify(body) });
const organizations = [{ id: 1, name: "Первая", unp: "111111111" }];
const requests = [
  { id: 1, number: "REQ-001", supplier: "А", item: "Потребность", quantity: "1", planned_amount: "10.00", due_date: null, stage: "need" },
  { id: 2, number: "REQ-002", supplier: "Б", item: "Поиск", quantity: "2", planned_amount: "20.00", due_date: null, stage: "sourcing" },
  { id: 3, number: "REQ-003", supplier: "В", item: "Переговоры", quantity: "3", planned_amount: "30.00", due_date: null, stage: "nego" },
  { id: 4, number: "REQ-004", supplier: "Г", item: "Анализ", quantity: "4", planned_amount: "40.00", due_date: null, stage: "analysis" },
  { id: 5, number: "REQ-005", supplier: "Д", item: "Согласование", quantity: "5", planned_amount: "50.00", due_date: null, stage: "approval" },
  { id: 6, number: "REQ-006", supplier: "Е", item: "Связана с заказом", quantity: "6", planned_amount: "60.00", due_date: null, stage: "po" },
];
const orders = [
  { id: 10, number: "PO-010", supplier: "Е", status: "draft", eta_date: null, freight_byn: "0.00" },
  { id: 11, number: "PO-011", supplier: "Ж", status: "shipped", eta_date: "2026-10-01", freight_byn: "0.00" },
  { id: 12, number: "PO-012", supplier: "З", status: "received", eta_date: "2026-09-20", freight_byn: "0.00" },
  { id: 13, number: "PO-013", supplier: "И", status: "received", eta_date: "2026-09-19", freight_byn: "0.00" },
  { id: 14, number: "PO-014", supplier: "К", status: "cancelled", eta_date: null, freight_byn: "0.00" },
];

beforeEach(() => {
  vi.stubGlobal("fetch", vi.fn(async (url: string) => {
    if (url === "/api/procurement/receipt-organizations") return json(organizations);
    if (url.endsWith("request-plan-context")) return json({ organization_id: 1, principal: "tester", can_manage: false });
    if (url.includes("owned-sources?kind=request")) return json({ organization_id: 1, items: requests, next_after_id: null });
    if (url.includes("owned-sources?kind=order")) return json({ organization_id: 1, items: orders, next_after_id: null });
    const match = /orders\/(\d+)\/chain$/.exec(url);
    if (match) {
      const id = Number(match[1]);
      return json({ organization_id: 1, order: { id }, request_links: id === 10 ? [{ request_id: 6 }] : [], status: id === 13 ? "complete" : "partial", blockers: id === 12 ? ["warehouse_receipt_not_accepted"] : [] });
    }
    throw new Error(`Unexpected request ${url}`);
  }));
});
afterEach(() => vi.unstubAllGlobals());

it("строит девять живых этапов из scoped заявок, заказов и первичных документов", async () => {
  render(<ProcurementKanban />);
  await waitForCompany();
  await configureCompany("1");
  await screen.findByText("REQ-001");
  await waitFor(() => expect(within(screen.getByLabelText("Колонка Завершено")).getByText("PO-013")).toBeInTheDocument());

  expect(within(screen.getByLabelText("Колонка Потребность")).getByText("REQ-001")).toBeInTheDocument();
  expect(within(screen.getByLabelText("Колонка Поиск поставщика")).getByText("REQ-002")).toBeInTheDocument();
  expect(within(screen.getByLabelText("Колонка Переговоры")).getByText("REQ-003")).toBeInTheDocument();
  expect(within(screen.getByLabelText("Колонка Анализ")).getByText("REQ-004")).toBeInTheDocument();
  expect(within(screen.getByLabelText("Колонка Согласование")).getByText("REQ-005")).toBeInTheDocument();
  expect(within(screen.getByLabelText("Колонка Заказ поставщику")).getByText("PO-010")).toBeInTheDocument();
  expect(within(screen.getByLabelText("Колонка Поставка")).getByText("PO-011")).toBeInTheDocument();
  expect(within(screen.getByLabelText("Колонка Приёмка")).getByText("PO-012")).toBeInTheDocument();
  expect(screen.queryByText("REQ-006")).toBeNull();
  const overview = screen.getByLabelText("Оперативный обзор закупок");
  expect(within(overview).getByText("Заявки в работе").nextElementSibling).toHaveTextContent("5");
  expect(within(overview).getByText("Заказы поставщикам").nextElementSibling).toHaveTextContent("1");
  expect(within(overview).getByText("Поставка").nextElementSibling).toHaveTextContent("1");
  expect(within(overview).getByText("Приёмка").nextElementSibling).toHaveTextContent("1");
  expect(within(overview).getByText("Завершено").nextElementSibling).toHaveTextContent("1");
  expect(screen.getByText("Отменённых заказов вне канбана: 1. Их можно проверить в разделе заказов поставщикам.")).toBeInTheDocument();
  expect(vi.mocked(fetch).mock.calls.flat().join(" ")).not.toContain("/procurement/board");
});


it("показывает источник дефицита только у подтверждённой автоматической заявки", async () => {
  const original = vi.mocked(fetch).getMockImplementation()!;
  vi.mocked(fetch).mockImplementation(async (input, init) => {
    if (String(input).includes("owned-sources?kind=request")) return json({
      organization_id: 1,
      items: requests.map((request, index) => ({ ...request, origin: index === 0 ? "deficit" : index === 1 ? "" : "unknown" })),
      next_after_id: null,
    }) as Response;
    return original(input, init);
  });
  render(<ProcurementKanban suggestedOrg="1" />);
  await waitForCompany();
  const automatic = (await screen.findByText("REQ-001")).closest("article")!;
  expect(within(automatic).getByText("Авто: дефицит склада")).toBeInTheDocument();
  const manual = screen.getByText("REQ-002").closest("article")!;
  expect(within(manual).queryByText("Авто: дефицит склада")).toBeNull();
  expect(screen.getAllByText("Авто: дефицит склада")).toHaveLength(1);
});

configureBeforeEach(() => resetCompany(1));

it.each([401, 403, 409, 502, 503])("conceals private response details on HTTP %s", async status => {
  vi.mocked(fetch).mockResolvedValue(json({ detail: "PRIVATE_BOARD_SENTINEL: internal upstream diagnostics" }, status) as Response);
  render(<ProcurementKanban />);
  const alert = await screen.findByRole("alert");
  expect(alert).toHaveTextContent(String(status));
  expect(alert).not.toHaveTextContent("PRIVATE_BOARD_SENTINEL");
  expect(screen.queryByText("Нет документов на этом этапе.")).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Обновить канбан" })).not.toBeDisabled();
});

it("conceals transport exception details when the board request fails", async () => {
  vi.mocked(fetch).mockRejectedValue(new Error("PRIVATE_BOARD_SENTINEL: transport diagnostics"));
  render(<ProcurementKanban />);
  const alert = await screen.findByRole("alert");
  expect(alert).toHaveTextContent("Не удалось связаться с сервисом закупок");
  expect(alert).not.toHaveTextContent("PRIVATE_BOARD_SENTINEL");
});

it("conceals response stream exception details", async () => {
  vi.mocked(fetch).mockResolvedValue({ ok: true, status: 200, text: async () => { throw new Error("PRIVATE_BOARD_SENTINEL: stream diagnostics"); } } as Response);
  render(<ProcurementKanban />);
  const alert = await screen.findByRole("alert");
  expect(alert).toHaveTextContent("Не удалось прочитать ответ сервиса закупок");
  expect(alert).not.toHaveTextContent("PRIVATE_BOARD_SENTINEL");
});

it("conceals a stage refusal without moving the card or repeating the command", async () => {
  const original = vi.mocked(fetch).getMockImplementation()!;
  vi.mocked(fetch).mockImplementation(async (input, init) => {
    const url = String(input);
    if (url.endsWith("request-plan-context")) return json({ organization_id: 1, principal: "tester", can_manage: true }) as Response;
    if (url.endsWith("/requests/1/stage")) return json({ detail: "PRIVATE_BOARD_SENTINEL: conflicting record diagnostics" }, 409) as Response;
    return original(input, init);
  });
  render(<ProcurementKanban />);
  const card = (await screen.findByText("REQ-001")).closest("article")!;
  const advance = within(card).getByRole("button", { name: "Далее: Поиск поставщика" });
  await waitFor(() => expect(advance).not.toBeDisabled());
  fireEvent.click(advance);
  const alert = await screen.findByRole("alert");
  expect(alert).toHaveTextContent("409");
  expect(alert).not.toHaveTextContent("PRIVATE_BOARD_SENTINEL");
  expect(screen.queryByText("Стадия заявки обновлена.")).not.toBeInTheDocument();
  const refresh = screen.getByRole("button", { name: "Обновить канбан" });
  await waitFor(() => expect(refresh).not.toBeDisabled());
  fireEvent.click(refresh);
  expect(await within(screen.getByLabelText("Колонка Потребность")).findByText("REQ-001")).toBeInTheDocument();
  expect(within(screen.getByLabelText("Колонка Поиск поставщика")).queryByText("REQ-001")).not.toBeInTheDocument();
  const writes = vi.mocked(fetch).mock.calls.filter(([input]) => String(input).endsWith("/requests/1/stage"));
  expect(writes).toHaveLength(1);
  expect(writes[0][1]?.method).toBe("PATCH");
});

it("searches loaded documents without new requests and keeps the same cards in list view", async () => {
  render(<ProcurementKanban />);
  await screen.findByText("REQ-001");
  await waitFor(() => expect(screen.getByRole("button", { name: "Обновить канбан" })).not.toBeDisabled());
  const calls = vi.mocked(fetch).mock.calls.length;
  fireEvent.change(screen.getByRole("textbox", { name: "Поиск по закупкам, поставщикам, SKU" }), { target: { value: "REQ-003" } });
  expect(screen.getByText("REQ-003")).toBeInTheDocument();
  expect(screen.queryByText("REQ-001")).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Список", exact: true }));
  expect(screen.getByLabelText("Список закупок")).toContainElement(screen.getByText("REQ-003"));
  expect(vi.mocked(fetch).mock.calls).toHaveLength(calls);
  fireEvent.change(screen.getByRole("textbox", { name: "Поиск по закупкам, поставщикам, SKU" }), { target: { value: "" } });
  expect(screen.getByText("REQ-001")).toBeInTheDocument();
});

it("does not replace a failed load with empty stages or zero KPI values", async () => {
  vi.mocked(fetch).mockResolvedValue(json({ detail: "Недоступно" }, 503) as Response);
  render(<ProcurementKanban />);
  expect(await screen.findByRole("alert")).toHaveTextContent("503");
  expect(screen.queryByText("Нет документов на этом этапе.")).not.toBeInTheDocument();
  const summary = screen.getByLabelText("Оперативный обзор закупок");
  expect(within(summary).getByText("Заявки в работе").nextElementSibling).toHaveTextContent("—");
  expect(screen.getByRole("button", { name: "Обновить канбан" })).not.toBeDisabled();
});

it("marks partial counts and does not present prototype AI results as facts", async () => {
  const original = vi.mocked(fetch).getMockImplementation()!;
  vi.mocked(fetch).mockImplementation(async (input, init) => String(input).includes("owned-sources?kind=request")
    ? json({ organization_id: 1, items: requests, next_after_id: 6 }) as Response : original(input, init));
  render(<ProcurementKanban />);
  await screen.findByText("REQ-001");
  await waitFor(() => expect(within(screen.getByLabelText("Оперативный обзор закупок")).getByText("Заявки в работе").nextElementSibling).toHaveTextContent("5+"));
  expect(screen.getByRole("button", { name: "Загрузить ещё заявки" })).toBeInTheDocument();
  expect(screen.getAllByText("Нет подтверждённых данных")).toHaveLength(2);
  expect(screen.queryByText(/1,85|210 000|93%/)).not.toBeInTheDocument();
});
