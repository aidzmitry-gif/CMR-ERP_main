import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { AccountingShipmentProfit } from "./accounting-shipment-profit";

afterEach(() => vi.unstubAllGlobals());
const amounts = { revenue_net_byn: "40.00", cogs_byn: "10.00", gross_profit_byn: "30.00", margin_percent: "75.00" };
const report = { organization_id: 1, start: "2026-09-01", end: "2026-09-30", basis: "at_posting", offset: 0, has_more: false,
  rows: [{ ...amounts, receipt_id: 7, entry_id: 15, document_id: 9, operation_date: "2026-09-15", posting_date: "2026-09-15", items: [{ sku: "SKU", quantity: "3" }] }],
  page_subtotal: amounts };
const props = { org: "1", start: "2026-09-01", end: "2026-09-30", onEntry: vi.fn() };

it("renders only recognized shipment profit with a link to source and scope label", async () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true, json: async () => report }));
  const onEntry = vi.fn();
  render(<AccountingShipmentProfit {...props} onEntry={onEntry} />);
  fireEvent.click(await screen.findByText("Отгрузка № 7"));
  expect(onEntry).toHaveBeenCalledWith(15);
  expect(screen.getAllByText("30.00")).toHaveLength(2);
  expect(screen.getByText(/последующие корректировки затрат и возвраты здесь не учтены/)).toBeInTheDocument();
  expect(screen.getByText("Далее")).toBeDisabled();
});

it("never turns a backend failure into zero profit or an empty report", async () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: false, json: async () => ({ detail: "Ошибка проверки отгрузки" }) }));
  render(<AccountingShipmentProfit {...props} />);
  expect(await screen.findByRole("alert")).toHaveTextContent("Ошибка проверки отгрузки");
  expect(screen.queryByText(/проведённых отгрузок нет/)).not.toBeInTheDocument();
});

it("rejects another organization's response", async () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true, json: async () => ({ ...report, organization_id: 2 }) }));
  render(<AccountingShipmentProfit {...props} />);
  expect(await screen.findByRole("alert")).toHaveTextContent("не соответствует");
  expect(screen.queryByText("30.00")).not.toBeInTheDocument();
});

it("does not publish a delayed response after the period changes", async () => {
  let resolve!: (value: unknown) => void;
  vi.stubGlobal("fetch", vi.fn().mockImplementationOnce(() => new Promise(done => { resolve = done; }))
    .mockResolvedValue({ ok: true, json: async () => ({ ...report, end: "2026-09-10", rows: [] }) }));
  const view = render(<AccountingShipmentProfit {...props} />);
  view.rerender(<AccountingShipmentProfit {...props} end="2026-09-10" />);
  await act(async () => resolve({ ok: true, json: async () => report }));
  expect(await screen.findByText("За выбранный период проведённых отгрузок нет.")).toBeInTheDocument();
  expect(screen.queryByText("Отгрузка № 7")).not.toBeInTheDocument();
});

it.each(["empty", "error"])("keeps Back available after a %s second page", async outcome => {
  const fetcher = vi.fn().mockResolvedValueOnce({ ok: true, json: async () => ({ ...report, has_more: true }) })
    .mockResolvedValueOnce({ ok: outcome === "empty", json: async () => outcome === "empty" ? { ...report, offset: 100, rows: [] } : { detail: "503" } })
    .mockResolvedValue({ ok: true, json: async () => report });
  vi.stubGlobal("fetch", fetcher);
  render(<AccountingShipmentProfit {...props} />);
  await screen.findByText("Отгрузка № 7");
  fireEvent.click(screen.getByRole("button", { name: "Далее" }));
  if (outcome === "empty") await screen.findByText(/На этой странице отгрузок нет/);
  else await screen.findByRole("alert");
  expect(screen.queryByText("За выбранный период проведённых отгрузок нет.")).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Назад" }));
  expect(await screen.findByText("Отгрузка № 7")).toBeInTheDocument();
  expect(fetcher.mock.calls[2][0]).toContain("offset=0");
});
