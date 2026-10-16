import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { AccountingClosingHistory } from "./accounting-closing-history";
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });
it("separates reopened history from current state and opens reversal entry", async () => {
  const data = { organization_id: 7, month: "2026-10", period_closed: false, receipts: [{ id: 1, actor: "Бухгалтер", created_at: "2026-11-01", policy_id: 3, monthly_entry_id: 12, annual_entry_id: null, evidence: { stock: "Сверка склада" }, reopening: { id: 2, actor: "Главбух", created_at: "2026-11-02", reason: "Уточнение стоимости", monthly_entry_id: 13, annual_entry_id: null } }] };
  const fetcher = vi.fn().mockResolvedValue({ ok: true, json: async () => data });
  vi.stubGlobal("fetch", fetcher);
  const onEntry = vi.fn();
  render(<AccountingClosingHistory org="7" month="2026-10" onEntry={onEntry} />);
  expect(fetcher).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: "Загрузить историю закрытия" }));
  expect(await screen.findByText("Сейчас месяц открыт.")).toBeInTheDocument();
  expect(screen.getByText(/отменено открытием периода/)).toBeInTheDocument();
  expect(screen.getByText("Уточнение стоимости")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Месячная операция № 13" }));
  expect(onEntry).toHaveBeenCalledWith(13);
});
it("rejects foreign history without showing its receipts", async () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true, json: async () => ({ organization_id: 8, month: "2026-10", period_closed: true, receipts: [] }) }));
  render(<AccountingClosingHistory org="7" month="2026-10" />);
  fireEvent.click(screen.getByRole("button"));
  expect(await screen.findByRole("alert")).toHaveTextContent("другого юрлица");
  expect(screen.queryByText("Сейчас месяц закрыт.")).not.toBeInTheDocument();
});
