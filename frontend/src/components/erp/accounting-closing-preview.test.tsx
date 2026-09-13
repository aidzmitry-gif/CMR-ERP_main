import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { AccountingClosingPreview } from "./accounting-closing-preview";
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });
const result = { organization_id: 7, month: "2026-09", policy_id: 3, status: "preview_only", confirmation_available: false, monthly_lines: [{ account: "90.9", side: "debit", amount: "123.45", dimensions: {} }, { account: "99", side: "credit", amount: "123.45", dimensions: {} }], annual_lines: [] };
it("loads the selected month on demand and renders all transfers without a write action", async () => {
  const fetcher = vi.fn().mockResolvedValue({ ok: true, json: async () => result });
  vi.stubGlobal("fetch", fetcher);
  render(<AccountingClosingPreview org="7" month="2026-09" />);
  expect(fetcher).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button"));
  expect(await screen.findByText("90.9")).toBeInTheDocument();
  expect(screen.getByText("99")).toBeInTheDocument();
  expect(screen.getAllByText("123.45")).toHaveLength(2);
  expect(fetcher).toHaveBeenCalledWith("/api/accounting/organizations/7/periods/2026-09/financial-closing-preview", expect.objectContaining({ cache: "no-store" }));
  expect(screen.getAllByRole("button")).toHaveLength(1);
});
it("rejects a response for another month", async () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true, json: async () => ({ ...result, month: "2026-10" }) }));
  render(<AccountingClosingPreview org="7" month="2026-09" />);
  fireEvent.click(screen.getByRole("button"));
  expect(await screen.findByRole("alert")).toHaveTextContent("не соответствует");
  expect(screen.queryByText("90.9")).not.toBeInTheDocument();
});

it("requires a fresh reviewed calculation after control evidence changes", async () => {
  const evidence = Object.fromEntries(["documents","bank","settlements","stock","costing","depreciation","fx","tax","financial_result","trial_balance"].map(key => [key,"Checked"]));
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true, json: async () => ({ ...result, confirmation_available: true, basis_digest: "a".repeat(64), period_generation: 2 }) }));
  const props = { org: "7", month: "2026-09", evidence, onClosed: vi.fn(), onLock: vi.fn() };
  const view = render(<AccountingClosingPreview {...props} />);
  fireEvent.click(screen.getByRole("button"));
  expect(await screen.findByText("Подтвердить переносы и закрыть месяц")).toBeInTheDocument();
  view.rerender(<AccountingClosingPreview {...props} evidence={{ ...evidence, bank: "Revised" }} />);
  expect(screen.queryByText("Подтвердить переносы и закрыть месяц")).toBeNull();
  expect(screen.getByRole("status")).toHaveTextContent("Основания проверок изменены");
  view.rerender(<AccountingClosingPreview {...props} />);
  expect(screen.queryByText("Подтвердить переносы и закрыть месяц")).toBeNull();
});
