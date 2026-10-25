import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import { ProcurementKanban } from "@/components/erp/procurement-kanban";

const json = (body: unknown, status = 200) => ({ ok: status >= 200 && status < 300, status, json: async () => body, text: async () => JSON.stringify(body) });
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
    if (url === "/api/system/instance-organization") return json({ configuration: "AIOS_SELLER_UNP", organization: organizations[0] });
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

it("не меняет компанию установки по чужому URL и не предлагает выбор компании", async () => {
  render(<ProcurementKanban suggestedOrg="2" />);
  await screen.findByText("REQ-001");
  expect(screen.getByRole("alert")).toHaveTextContent("другому юрлицу");
  expect(screen.queryByRole("combobox")).not.toBeInTheDocument();
  expect(vi.mocked(fetch).mock.calls.some(([url]) => String(url).includes("/organizations/2/") || String(url).includes("receipt-organizations"))).toBe(false);
});

it("невалидный URL не мешает загрузке настроенной организации", async () => {
  render(<ProcurementKanban suggestedOrg="invalid" />);
  await screen.findByText("REQ-001");
  expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  expect(screen.getByRole("link", { name: "Открыть план закупок" })).toHaveAttribute("href", "/erp/procurement/planning?org=1");
});

it("не загружает закупки при ошибке настройки, повторяет только настройку и затем загружает данные", async () => {
  const original = vi.mocked(fetch).getMockImplementation()!;
  vi.mocked(fetch).mockImplementation(async (url, options) => String(url).includes("instance-organization") ? json({}, 503) as Response : original(url, options));
  render(<ProcurementKanban />);
  await screen.findByRole("alert");
  expect(vi.mocked(fetch).mock.calls.map(([url]) => url)).toEqual(["/api/system/instance-organization"]);
  vi.mocked(fetch).mockImplementation(original);
  fireEvent.click(screen.getByRole("button", { name: "Повторить загрузку юрлица" }));
  await screen.findByText("REQ-001");
});

it("проверяет текущего сотрудника перед сменой стадии и запрещает запрос при изменении прав", async () => {
  const original = vi.mocked(fetch).getMockImplementation()!;
  let contextCalls = 0;
  vi.mocked(fetch).mockImplementation(async (url, options) => {
    if (String(url).endsWith("request-plan-context")) return json({ organization_id: 1, principal: ++contextCalls === 1 ? "tester" : "other", can_manage: true }) as Response;
    return original(url, options);
  });
  render(<ProcurementKanban />);
  const next = await screen.findByRole("button", { name: "Далее: Поиск поставщика" });
  await waitFor(() => expect(next).toBeEnabled());
  fireEvent.click(next);
  expect(await screen.findByRole("alert")).toHaveTextContent("Права или пользователь изменились");
  expect(vi.mocked(fetch).mock.calls.some(([, options]) => options?.method === "PATCH")).toBe(false);
});

it("дозагружает заявки своей компании без дубликатов и пересчитывает счётчики", async () => {
  const original = vi.mocked(fetch).getMockImplementation()!;
  vi.mocked(fetch).mockImplementation(async (url, options) => {
    if (String(url).includes("owned-sources?kind=request")) return json({ organization_id: 1, items: String(url).includes("after_id=6") ? [requests[0], { ...requests[0], id: 7, number: "REQ-007" }] : requests, next_after_id: String(url).includes("after_id=6") ? null : 6 }) as Response;
    return original(url, options);
  });
  render(<ProcurementKanban />);
  const more = await screen.findByRole("button", { name: "Загрузить ещё заявки" });
  await waitFor(() => expect(more).toBeEnabled());
  fireEvent.click(more);
  await screen.findByText("REQ-007");
  expect(screen.getAllByText("REQ-001")).toHaveLength(1);
  expect(within(screen.getByLabelText("Оперативный обзор закупок")).getByText("Заявки в работе").nextElementSibling).toHaveTextContent("6");
});


it("сохраняет порядок колонок и переносит ту же заявку после обновления без выдуманного балла", async () => {
  const original = vi.mocked(fetch).getMockImplementation()!;
  let stage = "need";
  const request = { ...requests[0], id: 101, number: "REQ-UNBOUND", supplier: "Synthetic supplier", item: "Болты", quantity: "100", planned_amount: "0.00" };
  vi.mocked(fetch).mockImplementation(async (url, options) => {
    if (String(url).includes("owned-sources?kind=request")) return json({ organization_id: 1, items: [{ ...request, stage }], next_after_id: null }) as Response;
    if (String(url).includes("owned-sources?kind=order")) return json({ organization_id: 1, items: [], next_after_id: null }) as Response;
    return original(url, options);
  });
  render(<ProcurementKanban />);
  await screen.findByText("REQ-UNBOUND");
  const board = within(screen.getByLabelText("Канбан закупок"));
  expect(board.getAllByRole("heading", { level: 2 }).map(heading => heading.textContent)).toEqual([
    "Потребность", "Поиск поставщика", "Переговоры", "Анализ", "Согласование",
    "Заказ поставщику", "Поставка", "Приёмка", "Завершено",
  ]);
  const need = within(screen.getByLabelText("Колонка Потребность"));
  expect(need.getByText("1", { exact: true })).toBeInTheDocument();
  const first = within(need.getByRole("article"));
  expect(first.getByRole("link", { name: "REQ-UNBOUND" })).toHaveAttribute("href", "/erp/procurement/planning?org=1");
  expect(first.getByText("Болты")).toBeInTheDocument();
  expect(first.getByText("Synthetic supplier · 100 шт. · 0.00")).toBeInTheDocument();
  expect(first.queryByText(/score|балл поставщика|оценка поставщика|8[.,]7/i)).not.toBeInTheDocument();
  stage = "nego";
  const refresh = screen.getByRole("button", { name: "Обновить канбан" });
  await waitFor(() => expect(refresh).toBeEnabled());
  fireEvent.click(refresh);
  const nego = within(screen.getByLabelText("Колонка Переговоры"));
  await nego.findByText("REQ-UNBOUND");
  expect(need.queryByText("REQ-UNBOUND")).not.toBeInTheDocument();
  expect(need.getByText("0", { exact: true })).toBeInTheDocument();
  expect(nego.getByText("1", { exact: true })).toBeInTheDocument();
  const moved = within(nego.getByRole("article"));
  expect(moved.getByText("Болты")).toBeInTheDocument();
  expect(moved.queryByText(/score|балл поставщика|оценка поставщика|8[.,]7/i)).not.toBeInTheDocument();
  expect(screen.getAllByText("REQ-UNBOUND")).toHaveLength(1);
  expect(vi.mocked(fetch).mock.calls.filter(([url]) => String(url).includes("owned-sources?kind=request"))).toHaveLength(2);
});
