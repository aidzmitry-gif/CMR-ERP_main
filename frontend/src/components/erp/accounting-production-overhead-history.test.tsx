import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { AccountingProductionOverheadHistory } from "./accounting-production-overhead-history";
afterEach(() => vi.unstubAllGlobals());
const history = { organization_id: 1, month: "2026-10", allocations: [{ organization_id: 1, month: "2026-10", entry_id: 7,
  actor: "original-accountant", posted: true, final_cost_certified: false, source_state: "changed", command: { posting_date: "2026-10-31", evidence: "Исходное основание распределения", review: { policy_id: 2 } },
  posting: { lines: [{ account: "20", side: "debit", amount: "30.00", dimensions: { department: "Цех", order: "A" } },
    { account: "25", side: "credit", amount: "30.00", dimensions: { department: "Цех" } }] } }] };
it("shows immutable amounts and an explicit changed-source warning, drills down, and clears failed refresh", async () => {
  let fail = false; const onEntry = vi.fn();
  vi.stubGlobal("fetch", vi.fn(async () => fail ? new Response("{}", { status: 503 }) : Response.json(history)));
  render(<AccountingProductionOverheadHistory org="1" month="2026-10" disabled={false} onEntry={onEntry} />);
  fireEvent.click(screen.getByText("Загрузить историю распределения"));
  expect(await screen.findByRole("alert")).toHaveTextContent("Требуется проверка и корректировка");
  expect(screen.getByText(/Дт 20 · 30.00 BYN/)).toHaveTextContent("Заказ: A");
  fireEvent.click(screen.getByText("Открыть историческую проводку №7")); expect(onEntry).toHaveBeenCalledWith(7);
  fail = true; fireEvent.click(screen.getByText("Загрузить историю распределения"));
  expect(await screen.findByRole("alert")).toHaveTextContent("История распределения недоступна");
  expect(screen.queryByText(/Дт 20 · 30.00 BYN/)).toBeNull();
});
it("rejects history from another organization even if the outer response scope matches", async () => {
  vi.stubGlobal("fetch", vi.fn(async () => Response.json({ ...history, allocations: [{ ...history.allocations[0], organization_id: 2 }] })));
  render(<AccountingProductionOverheadHistory org="1" month="2026-10" disabled={false} />);
  fireEvent.click(screen.getByText("Загрузить историю распределения"));
  expect(await screen.findByRole("alert")).toHaveTextContent("История не соответствует");
  expect(screen.queryByText(/30.00 BYN/)).toBeNull();
});
it.each(["valid", "foreign", "broken-chain"])("reads monetary and zero revisions with a validated chain: %s", async mode => {
  const onEntry = vi.fn();
  const first = { id: 11, sequence: 1, previous_id: null, organization_id: 1, month: "2026-10", original_entry_id: 7,
    entry_id: 8, actor: "accountant", posting_date: "2026-10-31", evidence: "Дополнительные расходы проверены",
    lines: history.allocations[0].posting.lines.map(line => ({ ...line, amount: "1.00" })) };
  const second = { ...first, id: 12, sequence: 2, previous_id: mode === "broken-chain" ? 99 : 11,
    organization_id: mode === "foreign" ? 2 : 1, entry_id: null, lines: [] };
  vi.stubGlobal("fetch", vi.fn(async () => Response.json({ ...history,
    allocations: [{ ...history.allocations[0], source_state: "unchanged", corrections: [first, second] }] })));
  render(<AccountingProductionOverheadHistory org="1" month="2026-10" disabled={false} onEntry={onEntry} />);
  fireEvent.click(screen.getByText("Загрузить историю распределения"));
  if (mode !== "valid") {
    expect(await screen.findByRole("alert")).toHaveTextContent("История не соответствует");
    expect(screen.queryByText(/Версия 2/)).toBeNull(); return;
  }
  expect(await screen.findByRole("status")).toHaveTextContent("последней подтверждённой версии");
  expect(screen.getByText(/Дт 20 · 30.00 BYN/)).toBeVisible();
  expect(screen.getByText(/Дт 20 · 1.00 BYN/)).toHaveTextContent("Заказ: A");
  expect(screen.getByText(/Подтверждено без денежной проводки/)).toBeVisible();
  fireEvent.click(screen.getByText("Открыть исправление №8")); expect(onEntry).toHaveBeenCalledWith(8);
});
