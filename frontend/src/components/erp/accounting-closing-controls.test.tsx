import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";

import { AccountingClosingControls } from "./accounting-closing-controls";

const snapshot = (overrides: Record<string, unknown> = {}) => ({
  organization_id: 7,
  month: "2026-10",
  status: "review_only",
  period: { closed: false, generation: 2 },
  policy: { id: 3, effective_from: "2026-01-01", status: "verified", normative_verified: true, technical_preview_available: true, confirmation_available: true },
  close_blocked_by_queues: true,
  close_blocked_by_policy: false,
  blockers: [{ code: "inbox", count: 2, message: "Документы ожидают проведения" }],
  review_items: [{ code: "vat_input", count: 1, message: "Входной НДС без регистрации" }],
  documents: { pending_inbox: 2, pending_source_controls: 0 },
  vat: { input_lines: 1, input_registered: 0, input_unregistered: 1, input_unresolved: 0, output_lines: 0, output_registered: 0, output_unregistered: 0, output_unresolved: 0, statutory_certified: false },
  fixed_assets: { assets_due_by_date: 0, depreciation_receipts: 0, assets_without_month_receipt: 0, statutory_certified: false },
  production: {
    postings: 3,
    material_issues: 1,
    material_issue_receipts: 1,
    labor_imports: 1,
    labor_receipts: 1,
    overhead_allocations: 1,
    overhead_receipts: 1,
    output_transfers: 0,
    output_transfer_receipts: 0,
    receipt_gap: 0,
    final_cost_certified: false,
  },
  payroll: {
    gross_accruals: 0,
    receipts: 0,
    receipt_gap: 0,
    statutory_payroll_certified: false,
    deductions_and_contributions_available: false,
  },
  repairs: { posted: 1, final_cost_certified: false },
  inventory: { late_cost_postings: 1, late_cost_receipts: 1, final_cost_certified: false },
  foreign_trade: { entries: 2, unresolved: 1, statutory_certified: false },
  statutory_certified: false,
  ...overrides,
});

afterEach(() => vi.unstubAllGlobals());

it("loads a scoped read-only snapshot and shows blockers and review items", async () => {
  const fetcher = vi.fn().mockResolvedValue({ ok: true, json: async () => snapshot() });
  vi.stubGlobal("fetch", fetcher);
  render(<AccountingClosingControls org="7" month="2026-10" />);
  expect(fetcher).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: "Проверить регистры" }));
  expect(await screen.findByRole("status")).toHaveTextContent("Месяц 2026-10");
  expect(screen.getByText(/Документы ожидают проведения/)).toBeInTheDocument();
  expect(screen.getByText(/Входной НДС без регистрации/)).toBeInTheDocument();
  expect(screen.getByText("Проводки производства:")).toBeInTheDocument();
  expect(screen.getByText("Материалы:")).toBeInTheDocument();
  expect(screen.getByText(/Нормативная база подтверждена/)).toBeInTheDocument();
  expect(fetcher).toHaveBeenCalledWith("/api/accounting/organizations/7/periods/2026-10/closing-controls", { cache: "no-store" });
});

it("rejects a response for another organization or month", async () => {
  const fetcher = vi.fn().mockResolvedValue({ ok: true, json: async () => snapshot({ organization_id: 8 }) });
  vi.stubGlobal("fetch", fetcher);
  render(<AccountingClosingControls org="7" month="2026-10" />);
  fireEvent.click(screen.getByRole("button", { name: "Проверить регистры" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("не соответствует выбранной организации или месяцу");
  expect(screen.queryByRole("status")).not.toBeInTheDocument();
});
