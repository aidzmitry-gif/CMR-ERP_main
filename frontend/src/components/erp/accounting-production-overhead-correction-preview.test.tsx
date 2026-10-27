import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { AccountingProductionOverheadCorrectionPreview } from "./accounting-production-overhead-correction-preview";
import type { PreparedOverhead } from "./accounting-production-overhead-confirmation";
afterEach(() => vi.unstubAllGlobals());
const prepared: PreparedOverhead = { digest: "b".repeat(64), earliestDate: "2026-10-02", review: {
  policy_id: 2, expected_source_digest: "a".repeat(64), classifications: [{ line_id: 1, role: "direct_cost", evidence: "Сверено по документу" }],
  orders: [{ analytical_order: "A", order_id: 7, evidence: "Сверено по наряду" }] } };
it.each(["delta", "zero", "foreign", "unavailable"])("requires explicit method/date/evidence and invalidates confirmation on edits: %s", async mode => {
  const onPrepared = vi.fn();
  const request = vi.fn(async (_url: RequestInfo | URL, init?: RequestInit) => Response.json({ digest: "c".repeat(64), snapshot: {
    organization_id: mode === "foreign" ? 2 : 1, month: "2026-10", original_entry_id: 7, command: JSON.parse(String(init?.body)),
    status: "correction_preview", posted: false, confirmation_available: mode !== "unavailable", final_cost_certified: false,
    creates_entry: mode !== "zero", correction_lines: mode === "zero" ? [] : [{ account: "20", side: "debit", amount: "1.00", dimensions: { order: "A" } },
      { account: "25", side: "credit", amount: "1.00", dimensions: {} }] } }));
  vi.stubGlobal("fetch", request);
  render(<AccountingProductionOverheadCorrectionPreview org="1" month="2026-10" target={{ entryId: 7, policyId: 2, postingDate: "2026-10-31" }} prepared={prepared} disabled={false} onPrepared={onPrepared} />);
  const calculate = screen.getByText("Рассчитать разницу для исправления");
  expect(calculate).toBeDisabled();
  fireEvent.change(screen.getByLabelText("Основание исправления"), { target: { value: "Проверены дополнительные затраты" } });
  fireEvent.change(screen.getByLabelText("Дата исправления"), { target: { value: "2026-10-31" } });
  expect(calculate).toBeDisabled();
  fireEvent.change(screen.getByLabelText("Метод исправления"), { target: { value: "delta" } });
  fireEvent.click(calculate);
  if (mode === "foreign") expect(await screen.findByRole("alert")).toHaveTextContent("не соответствует");
  else {
    expect(await screen.findByRole("status")).toHaveTextContent(mode === "zero" ? "Разница равна нулю" : "Дт 20 · 1.00 BYN");
    expect(screen.getByRole("status")).toHaveTextContent("В бухгалтерский учёт не записано");
  }
  expect(request).toHaveBeenCalledTimes(1); expect(String(request.mock.calls[0][0])).toMatch(/correction-preview$/);
  if (mode === "foreign" || mode === "unavailable") expect(onPrepared).toHaveBeenLastCalledWith(null);
  else expect(onPrepared).toHaveBeenLastCalledWith({ command: JSON.parse(String(request.mock.calls[0][1]?.body)), digest: "c".repeat(64), createsEntry: mode !== "zero" });
  fireEvent.change(screen.getByLabelText("Дата исправления"), { target: { value: "2026-10-30" } });
  expect(calculate).toBeDisabled(); expect(screen.queryByRole("status")).toBeNull();
  expect(onPrepared).toHaveBeenLastCalledWith(null);
});
