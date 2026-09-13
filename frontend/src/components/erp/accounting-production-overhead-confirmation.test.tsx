import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { AccountingProductionOverheadConfirmation, type PreparedOverhead } from "./accounting-production-overhead-confirmation";
import { pendingOverhead, resolveOverhead, type PendingOverhead } from "@/lib/production-overhead-journal";
beforeEach(() => {
  const values = new Map<string, string>();
  vi.stubGlobal("localStorage", { getItem: (k: string) => values.get(k) ?? null,
    setItem: (k: string, v: string) => values.set(k, v), removeItem: (k: string) => values.delete(k) });
});
it("recovers a withdrawal after reload without sending the original allocation again", async () => {
  let receipt: unknown = null; const onWithdrawn = vi.fn(), onConfirmed = vi.fn();
  const item: PendingOverhead = { org: "1", month: "2026-10", principal: "chief", command: {
    request_key: "00000000-0000-4000-8000-000000000007", expected_review_digest: prepared.digest, review: prepared.review,
    posting_date: "2026-10-31", evidence: "Проверено бухгалтером" } };
  const request = vi.fn(async (url: RequestInfo | URL, init?: RequestInit) => {
    if (String(url).endsWith("-access")) return Response.json({ organization_id: 1, principal: "chief", can_confirm: true });
    if (init?.method === "POST") {
      expect(String(url)).toMatch(/production-overhead-withdraw$/);
      const body = JSON.parse(String(init.body));
      receipt = { organization_id: 1, month: "2026-10", actor: "chief", request_key: item.command.request_key,
        command: body.command, reason: body.reason, posted: false, withdrawn: true, final_cost_certified: false };
      throw new Error("Ответ об отзыве потерян");
    }
    return receipt ? Response.json(receipt) : new Response("{}", { status: 404 });
  });
  vi.stubGlobal("fetch", request);
  await resolveOverhead(localStorage, item, false, request);
  const props = { org: "1", month: "2026-10", disabled: false, prepared: null, onConfirmed, onWithdrawn };
  const first = render(<AccountingProductionOverheadConfirmation {...props} />);
  fireEvent.click(screen.getByText("Проверить сохранённое проведение"));
  await screen.findByLabelText("Основание отзыва запроса");
  expect(screen.getByText("Отозвать непроведённый запрос")).toBeDisabled();
  fireEvent.change(screen.getByLabelText("Основание отзыва запроса"), { target: { value: "Добавлены новые затраты в месяц" } });
  fireEvent.click(screen.getByText("Отозвать непроведённый запрос"));
  await screen.findByText("Ответ об отзыве потерян");
  expect(screen.queryByText("Повторить сохранённое проведение")).toBeNull();
  expect(screen.getByText("Повторить отзыв запроса")).toBeVisible();
  first.unmount();
  render(<AccountingProductionOverheadConfirmation {...props} />);
  fireEvent.click(screen.getByText("Проверить сохранённое проведение"));
  await screen.findByText(/Запрос отозван и больше не может создать проводку/);
  expect(onWithdrawn).toHaveBeenCalledTimes(1); expect(onConfirmed).not.toHaveBeenCalled();
  expect(pendingOverhead(localStorage, "1", "chief", "2026-10")).toBeNull();
  expect(request.mock.calls.filter(([, init]) => init?.method === "POST")).toHaveLength(1);
});
afterEach(() => vi.unstubAllGlobals());
const prepared: PreparedOverhead = { digest: "b".repeat(64), earliestDate: "2026-10-02", review: {
  policy_id: 2, expected_source_digest: "a".repeat(64), classifications: [{ line_id: 1, role: "direct_cost", evidence: "Документ затрат" }, { line_id: 2, role: "overhead", evidence: "Накладные затраты" }],
  orders: [{ analytical_order: "A", order_id: 7, evidence: "Проверенный наряд" }] } };
it("recovers a lost response after remount without source preview or a second POST, then opens the entry", async () => {
  let receipt: unknown = null; const onConfirmed = vi.fn(), onEntry = vi.fn();
  const request = vi.fn(async (url: RequestInfo | URL, init?: RequestInit) => {
    if (String(url).endsWith("-access")) return Response.json({ organization_id: 1, principal: "chief", can_confirm: true });
    if (init?.method === "POST") {
      const command = JSON.parse(String(init.body));
      receipt = { organization_id: 1, month: "2026-10", actor: "chief", entry_id: 91, request_key: command.request_key, command, posted: true, final_cost_certified: false };
      throw new Error("Ответ потерян");
    }
    return receipt ? Response.json(receipt) : new Response("{}", { status: 404 });
  });
  vi.stubGlobal("fetch", request);
  const props = { org: "1", month: "2026-10", disabled: false, onConfirmed, onEntry };
  const first = render(<AccountingProductionOverheadConfirmation {...props} prepared={prepared} />);
  expect(request).not.toHaveBeenCalled();
  expect(screen.getByText("Провести проверенное распределение")).toBeDisabled();
  fireEvent.change(screen.getByLabelText("Дата проведения распределения"), { target: { value: "2026-10-01" } });
  fireEvent.change(screen.getByLabelText("Основание проведения распределения"), { target: { value: "Проверено бухгалтером" } });
  expect(screen.getByText("Провести проверенное распределение")).toBeDisabled();
  fireEvent.change(screen.getByLabelText("Дата проведения распределения"), { target: { value: "2026-10-31" } });
  fireEvent.click(screen.getByText("Провести проверенное распределение"));
  await screen.findByText("Ответ потерян");
  expect(pendingOverhead(localStorage, "1", "chief", "2026-10")).not.toBeNull(); expect(onConfirmed).not.toHaveBeenCalled();
  first.unmount(); request.mockClear();
  render(<AccountingProductionOverheadConfirmation {...props} prepared={null} />);
  expect(request).not.toHaveBeenCalled();
  expect(screen.queryByText("Провести проверенное распределение")).toBeNull();
  fireEvent.click(screen.getByText("Проверить сохранённое проведение"));
  await screen.findByText(/Распределение проведено. Проводка №91/);
  expect(request.mock.calls.every(([, init]) => init?.method !== "POST")).toBe(true);
  expect(onConfirmed).toHaveBeenCalledTimes(1); expect(pendingOverhead(localStorage, "1", "chief", "2026-10")).toBeNull();
  await waitFor(() => expect(screen.getByText("Открыть проводку распределения")).not.toBeDisabled());
  fireEvent.click(screen.getByText("Открыть проводку распределения")); expect(onEntry).toHaveBeenCalledWith(91);
});
