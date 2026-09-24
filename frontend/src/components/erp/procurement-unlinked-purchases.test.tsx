import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";

import { ProcurementUnlinkedPurchases } from "./procurement-unlinked-purchases";

afterEach(() => vi.unstubAllGlobals());

it("shows accounting postings separately from supplier invoices and pages without duplicates", async () => {
  const fetcher = vi.fn(async (url: string) => ({ ok: true, json: async () =>
    url.includes("after_id=8")
      ? { rows: [{ entry_id: 7, document_date: "2026-07-01", posting_date: "2026-07-02", source: "legacy-7", source_version: 1 }], next_after_id: null }
      : { rows: [{ entry_id: 8, document_date: "2026-08-01", posting_date: "2026-08-03", source: "legacy-8", source_version: 2 }], next_after_id: 8 },
  }));
  vi.stubGlobal("fetch", fetcher);
  render(<ProcurementUnlinkedPurchases org="7" />);

  expect(await screen.findByRole("link", { name: "Проводка № 8" })).toHaveAttribute("href", "/erp/accounting?org=7&entry=8");
  expect(screen.getByText(/не сохранённые накладные поставщика/)).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Показать ещё" }));
  expect(await screen.findByRole("link", { name: "Проводка № 7" })).toHaveAttribute("href", "/erp/accounting?org=7&entry=7");
  expect(screen.getAllByRole("link", { name: /Проводка №/ })).toHaveLength(2);
  expect(screen.queryByRole("button", { name: "Показать ещё" })).not.toBeInTheDocument();
  expect(fetcher).toHaveBeenCalledTimes(2);
});

it("does not retain another organization's postings after switching the selected book", async () => {
  const fetcher = vi.fn(async (url: string) => ({ ok: true, json: async () => ({
    rows: [{ entry_id: url.includes("/7/") ? 8 : 9, document_date: "2026-08-01", posting_date: "2026-08-02", source: "old", source_version: 1 }],
    next_after_id: null,
  }) }));
  vi.stubGlobal("fetch", fetcher);
  const view = render(<ProcurementUnlinkedPurchases key="7" org="7" />);
  await screen.findByRole("link", { name: "Проводка № 8" });
  view.rerender(<ProcurementUnlinkedPurchases key="8" org="8" />);
  expect(await screen.findByRole("link", { name: "Проводка № 9" })).toHaveAttribute("href", "/erp/accounting?org=8&entry=9");
  expect(screen.queryByRole("link", { name: "Проводка № 8" })).not.toBeInTheDocument();
});

it("shows access denial instead of an empty reconciliation result", async () => {
  vi.stubGlobal("fetch", vi.fn(async () => ({ ok: false, status: 403 })));
  render(<ProcurementUnlinkedPurchases org="7" />);
  await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("Нет доступа к бухгалтерским поступлениям этого юрлица."));
  expect(screen.queryByText("Поступлений без связанной первички не найдено.")).not.toBeInTheDocument();
});
