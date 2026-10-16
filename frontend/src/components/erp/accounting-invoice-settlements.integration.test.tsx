import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";

import { AccountingView } from "./accounting-view";

afterEach(() => vi.unstubAllGlobals());

it("opens invoice settlements from the accountant home and resets the invoice on organization change", async () => {
  const fetchMock = vi.fn((url: string) => {
    let data: unknown;
    if (url === "/api/accounting/organizations") data = [{ id: 7, name: "Компания A", unp: "111" }, { id: 8, name: "Компания B", unp: "222" }];
    else if (url.includes("/reports?")) data = { pending_documents: 0 };
    else if (url.includes("/accounts?") || url.endsWith("/policies")) data = [];
    else if (url === "/api/sales/organizations/7/invoices/77/settlements") data = { received: "0", refunded: "0", net_received: "0", cancellation_authorized: false, reconciliation_required: true, items: [] };
    else throw new Error(`Unexpected request: ${url}`);
    return Promise.resolve({ ok: true, status: 200, json: async () => data });
  });
  vi.stubGlobal("fetch", fetchMock);
  render(<AccountingView />);
  await screen.findByText(/включительно: 0\./);
  fireEvent.click(screen.getByRole("button", { name: "Банк и платежи" }));
  fireEvent.click(screen.getByRole("button", { name: "Оплаты счетов" }));
  fireEvent.change(screen.getByLabelText("ID счёта"), { target: { value: "77" } });
  fireEvent.click(screen.getByRole("button", { name: "Открыть расчёты счёта" }));
  await screen.findByLabelText("Итоги расчётов");
  expect(screen.getByText("Счёт ID 77 · юрлицо 7")).toBeInTheDocument();
  fireEvent.change(screen.getByLabelText("Организация"), { target: { value: "8" } });
  expect(screen.getByLabelText("ID счёта")).toHaveValue("");
  expect(screen.queryByLabelText("Итоги расчётов")).not.toBeInTheDocument();
  expect(fetchMock.mock.calls.filter(([url]) => url.includes("/api/sales/"))).toHaveLength(1);
});

it("locks organization and workspace navigation throughout an uncertain allocation", async () => {
  let rejectPost!: (reason: Error) => void;
  const pending = new Promise((_, reject) => { rejectPost = reject; });
  vi.stubGlobal("fetch", vi.fn((url: string, options?: RequestInit) => {
    if (options?.method === "POST") return pending;
    let data: unknown = [];
    if (url === "/api/accounting/organizations") data = [{ id: 7, name: "Компания A", unp: "111" }, { id: 8, name: "Компания B", unp: "222" }];
    else if (url.includes("/reports?")) data = { pending_documents: 0 };
    else if (url.endsWith("/settlements")) data = { received: "0", refunded: "0", net_received: "0", cancellation_authorized: false, reconciliation_required: true, items: [] };
    return Promise.resolve({ ok: true, status: 200, json: async () => data });
  }));
  render(<AccountingView />);
  await screen.findByText(/включительно: 0\./);
  fireEvent.click(screen.getByRole("button", { name: "Банк и платежи" }));
  fireEvent.click(screen.getByRole("button", { name: "Оплаты счетов" }));
  fireEvent.change(screen.getByLabelText("ID счёта"), { target: { value: "77" } });
  fireEvent.click(screen.getByRole("button", { name: "Открыть расчёты счёта" }));
  await screen.findByLabelText("Сумма распределения");
  for (const [label, value] of [["ID банковской проводки", "31"], ["Сумма распределения", "10.00"], ["Ключ распределения", "K1"], ["Первичное основание", "Выписка"]]) {
    fireEvent.change(screen.getByLabelText(label), { target: { value } });
  }
  fireEvent.click(screen.getByRole("button", { name: "Подтвердить распределение" }));
  expect(screen.getByLabelText("Организация")).toBeDisabled();
  expect(screen.getByRole("button", { name: "Рабочее место" })).toBeDisabled();
  await act(async () => rejectPost(new Error("Connection lost")));
  expect(screen.getByLabelText("Организация")).toBeDisabled();
  expect(screen.getByRole("button", { name: "Рабочее место" })).toBeDisabled();
  expect(screen.getByLabelText("Ключ распределения")).toHaveValue("K1");
});
