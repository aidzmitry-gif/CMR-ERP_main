import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { AccountingShipmentPackage } from "./accounting-shipment-package";

const saved = { organization_id: 1, source: "wms:physical-shipment:1:00000000-0000-4000-8000-000000000001", actor: "Бухгалтер", created_at: "2026-09-10T12:00:00Z", command: { recognition_basis: "Отгрузка по договору", unit_basis: "Штуки" }, snapshot: {
  act: { snapshot: { lines: [{ source: "line1", line_no: 7 }] } }, pages: [{ entry_id: 5 }, { entry_id: 6 }],
  mapping: [{ line_source: "line1", account: "41.2", lot: "Партия А", quantity: "0.000001", cost_byn: "0.00", expense_account: "90.4", expense_dimensions: { order: "Заказ 1" } }],
  commercial: [{ line_no: 7, net_byn: "20.00", vat_byn: "4.00", gross_byn: "24.00" }],
} };
afterEach(() => vi.unstubAllGlobals());

it("loads exact strings on demand and opens another page", async () => {
  const fetcher = vi.fn().mockResolvedValue({ ok: true, json: async () => saved });
  vi.stubGlobal("fetch", fetcher);
  const onEntry = vi.fn();
  render(<AccountingShipmentPackage org="1" entryId={5} onEntry={onEntry} />);
  expect(fetcher).not.toHaveBeenCalled();
  fireEvent.click(screen.getByText("Показать пакет отгрузки"));
  expect(await screen.findByText("0.000001")).toBeInTheDocument();
  expect(screen.getByText("0.00")).toBeInTheDocument();
  expect(screen.getByText("24.00")).toBeInTheDocument();
  expect(screen.getByText("Открыть внутренний акт отгрузки")).toHaveAttribute("href", "/api/accounting/organizations/1/shipments/00000000-0000-4000-8000-000000000001/document");
  fireEvent.click(screen.getByText("Страница 2 · операция № 6"));
  expect(onEntry).toHaveBeenCalledWith(6);
  expect(fetcher.mock.calls[0][0]).toBe("/api/accounting/organizations/1/entries/5/shipment-package");
});

it("does not display another book's data and allows retry", async () => {
  const fetcher = vi.fn().mockResolvedValueOnce({ ok: true, json: async () => ({ ...saved, organization_id: 2 }) })
    .mockResolvedValueOnce({ ok: false, status: 409 });
  vi.stubGlobal("fetch", fetcher);
  render(<AccountingShipmentPackage org="1" entryId={5} onEntry={vi.fn()} />);
  fireEvent.click(screen.getByText("Показать пакет отгрузки"));
  expect(await screen.findByRole("alert")).toHaveTextContent("другой операции");
  expect(screen.queryByText("Партия А")).not.toBeInTheDocument();
  fireEvent.click(screen.getByText("Повторить загрузку"));
  await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("не прошёл проверку"));
});

it("ignores a response after the user closes the package", async () => {
  let resolve!: (value: unknown) => void;
  vi.stubGlobal("fetch", vi.fn(() => new Promise(done => { resolve = done; })));
  render(<AccountingShipmentPackage org="1" entryId={5} onEntry={vi.fn()} />);
  fireEvent.click(screen.getByText("Показать пакет отгрузки"));
  fireEvent.click(screen.getByText("Скрыть пакет отгрузки"));
  await act(async () => resolve({ ok: true, json: async () => saved }));
  expect(screen.queryByText("Партия А")).not.toBeInTheDocument();
});
