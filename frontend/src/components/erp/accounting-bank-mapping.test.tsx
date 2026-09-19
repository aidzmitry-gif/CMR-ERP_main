import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";

import { AccountingBankMapping } from "./accounting-bank-mapping";

afterEach(() => vi.unstubAllGlobals());

it("lists, creates, and closes a bank-account binding with the exact API bodies", async () => {
  const rows = [{ mapping_id: 4, provider: "bank-api", external_account: "BY00", currency: "BYN",
    valid_from: "2026-09-01", valid_to: null, version: 1, ledger_account_id: 51, dimensions: { department: "bank" } }];
  const fetchMock = vi.fn().mockImplementation((url: string, init?: RequestInit) => {
    if (url.includes("include_closed=true")) return Promise.resolve({ ok: true, json: async () => rows });
    if (url.endsWith("/accounts?on=2026-10-01")) return Promise.resolve({ ok: true, json: async () => [{ id: 51, code: "51", title: "Банк", cash: true, required_dimensions: ["department"] }] });
    if (url.endsWith("/bank-account-mappings") && init?.method === "POST") return Promise.resolve({ ok: true, json: async () => ({ mapping_id: 5 }) });
    if (url.endsWith("/bank-account-mappings/4/close")) return Promise.resolve({ ok: true, json: async () => ({ mapping_id: 4 }) });
    throw new Error(url);
  });
  vi.stubGlobal("fetch", fetchMock);
  const changed = vi.fn();
  render(<AccountingBankMapping org="1" accounts={[
    { id: 51, code: "51", title: "Банк", cash: true, valid_from: "2026-01-01", required_dimensions: ["department"] },
  ]} onChanged={changed} />);

  await screen.findByText("bank-api");
  expect(screen.getByText("department: bank")).toBeInTheDocument();
  fireEvent.change(screen.getByLabelText("Источник выписки"), { target: { value: "bank-api" } });
  fireEvent.change(screen.getByLabelText("Внешний счёт привязки"), { target: { value: "BY01" } });
  fireEvent.change(screen.getByLabelText("Дата начала привязки"), { target: { value: "2026-10-01" } });
  await waitFor(() => expect(screen.getByRole("option", { name: "51 · Банк" })).toBeInTheDocument());
  fireEvent.change(screen.getByLabelText("Денежный счёт привязки"), { target: { value: "51" } });
  fireEvent.change(screen.getByLabelText("Аналитика привязки: department"), { target: { value: "bank" } });
  fireEvent.change(screen.getByLabelText("Основание привязки"), { target: { value: "Synthetic documented bank binding" } });
  fireEvent.click(screen.getByRole("button", { name: "Создать привязку" }));
  await waitFor(() => expect(changed).toHaveBeenCalledTimes(1));
  const create = fetchMock.mock.calls.find(([, init]) => init?.method === "POST" && !String(init?.body).includes("valid_to"));
  expect(JSON.parse(String(create?.[1]?.body))).toEqual({ provider: "bank-api", external_account: "BY01", currency: "BYN",
    valid_from: "2026-10-01", ledger_account_id: 51, dimensions: { department: "bank" }, evidence: "Synthetic documented bank binding" });
  expect(fetchMock.mock.calls.some(([url]) => String(url).endsWith("/accounts?on=2026-10-01"))).toBe(true);

  fireEvent.click(screen.getByRole("button", { name: "Закрыть" }));
  fireEvent.change(screen.getByLabelText("Дата закрытия привязки"), { target: { value: "2026-11-01" } });
  fireEvent.change(screen.getByLabelText("Основание закрытия привязки"), { target: { value: "Synthetic controlled close" } });
  fireEvent.click(screen.getByRole("button", { name: "Подтвердить закрытие" }));
  await waitFor(() => expect(changed).toHaveBeenCalledTimes(2));
  const close = fetchMock.mock.calls.find(([url]) => String(url).endsWith("/bank-account-mappings/4/close"));
  expect(JSON.parse(String(close?.[1]?.body))).toEqual({ valid_to: "2026-11-01", evidence: "Synthetic controlled close" });
});
