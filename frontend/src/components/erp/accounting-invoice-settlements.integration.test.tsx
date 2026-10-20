import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";

import { AccountingView } from "./accounting-view";

afterEach(() => vi.unstubAllGlobals());

it("opens invoice settlements for the configured company and ignores a foreign organization hint", async () => {
  const fetchMock = vi.fn((url: string) => {
    let data: unknown;
    if (url === "/api/system/instance-organization") data = { configuration: "AIOS_SELLER_UNP", organization: { id: 7, name: "Компания A", unp: "111111111" } };
    else if (url.includes("/reports?")) data = { pending_documents: 0 };
    else if (url.includes("/accounts?") || url.endsWith("/policies")) data = [];
    else if (url === "/api/sales/organizations/7/invoices/77/settlements") data = { received: "0", refunded: "0", net_received: "0", cancellation_authorized: false, reconciliation_required: true, items: [] };
    else throw new Error(`Unexpected request: ${url}`);
    return Promise.resolve({ ok: true, status: 200, json: async () => data });
  });
  vi.stubGlobal("fetch", fetchMock);
  const view = render(<AccountingView />);
  await screen.findByText(/включительно: 0\./);
  fireEvent.click(screen.getByRole("button", { name: "Банк и платежи" }));
  fireEvent.click(screen.getByRole("button", { name: "Оплаты счетов" }));
  fireEvent.change(screen.getByLabelText("ID счёта"), { target: { value: "77" } });
  fireEvent.click(screen.getByRole("button", { name: "Открыть расчёты счёта" }));
  await screen.findByLabelText("Итоги расчётов");
  expect(screen.getByText("Счёт ID 77 · юрлицо 7")).toBeInTheDocument();
  view.rerender(<AccountingView suggestedOrg="8" suggestedEntry="5" />);
  expect(screen.getByRole("alert")).toHaveTextContent("Ссылка относится к другому юрлицу");
  expect(screen.queryByLabelText("Организация")).not.toBeInTheDocument();
  expect(screen.getByText("Компания A · УНП 111111111")).toBeInTheDocument();
  expect(screen.getByLabelText("ID счёта")).toHaveValue("77");
  expect(screen.getByLabelText("Итоги расчётов")).toBeInTheDocument();
  expect(fetchMock.mock.calls.some(([url]) => /\/organizations\/8\/|\/entries\/5/.test(url))).toBe(false);
  expect(fetchMock.mock.calls.filter(([url]) => url.includes("/api/sales/"))).toHaveLength(1);
});

it("locks organization and workspace navigation throughout an uncertain allocation", async () => {
  let rejectPost!: (reason: Error) => void;
  const pending = new Promise((_, reject) => { rejectPost = reject; });
  vi.stubGlobal("fetch", vi.fn((url: string, options?: RequestInit) => {
    if (options?.method === "POST") return pending;
    let data: unknown = [];
    if (url === "/api/system/instance-organization") data = { configuration: "AIOS_SELLER_UNP", organization: { id: 7, name: "Компания A", unp: "111111111" } };
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
  expect(screen.queryByLabelText("Организация")).not.toBeInTheDocument(); expect(screen.getByLabelText("Начало периода")).toBeDisabled(); expect(screen.getByLabelText("Конец периода")).toBeDisabled();
  expect(screen.getByRole("button", { name: "Рабочее место" })).toBeDisabled();
  await act(async () => rejectPost(new Error("Connection lost")));
  expect(screen.queryByLabelText("Организация")).not.toBeInTheDocument(); expect(screen.getByLabelText("Начало периода")).toBeDisabled(); expect(screen.getByLabelText("Конец периода")).toBeDisabled();
  expect(screen.getByRole("button", { name: "Рабочее место" })).toBeDisabled();
  expect(screen.getByLabelText("Ключ распределения")).toHaveValue("K1");
});
