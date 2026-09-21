import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

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
  fireEvent.change(await screen.findByLabelText("Юрлицо канбана закупок"), { target: { value: "1" } });
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
