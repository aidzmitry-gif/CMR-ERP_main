import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { AccountingProductionCorrectionConfirmation } from "./accounting-production-correction-confirmation";
import type { PreparedCorrection } from "@/lib/production-correction-journal";
import { resolveCorrection, type PendingCorrection } from "@/lib/production-correction-journal";

beforeEach(() => {
  const values = new Map<string, string>();
  vi.stubGlobal("localStorage", { getItem: (k: string) => values.get(k) ?? null, setItem: (k: string, v: string) => values.set(k, v),
    removeItem: (k: string) => values.delete(k), get length() { return values.size; } });
});
afterEach(() => vi.unstubAllGlobals());
it("recovers a lost withdrawal after remount and never retries confirmation", async () => {
  const item: PendingCorrection = { org: "1", month: "2026-10", principal: "chief", command: {
    request_key: "12345678-1234-4234-8234-123456789abc", expected_preview_digest: "c".repeat(64), preview: {
      original_entry_id: 7, method: "delta", posting_date: "2026-10-31", evidence: "Проверены исходные документы",
      expected_review_digest: "b".repeat(64), review: { policy_id: 2, expected_source_digest: "a".repeat(64),
        classifications: [{ line_id: 1, role: "excluded", evidence: "Строка исключена по документам" }], orders: [] } } } };
  let outcome: unknown = null;
  const request = vi.fn(async (url: RequestInfo | URL, init?: RequestInit) => {
    if (String(url).endsWith("/production-overhead-access")) return Response.json({ organization_id: 1, principal: "chief", can_confirm: true });
    if (init?.method === "POST") {
      expect(String(url)).toMatch(/correction-withdraw$/);
      const body = JSON.parse(String(init.body));
      outcome = { organization_id: 1, month: "2026-10", actor: "chief", request_key: item.command.request_key,
        command: body.command, reason: body.reason, confirmed: false, withdrawn: true, posted: false, final_cost_certified: false };
      throw new TypeError("lost withdrawal response");
    }
    return outcome ? Response.json(outcome) : new Response("{}", { status: 404 });
  });
  await resolveCorrection(localStorage, item, false, request);
  vi.stubGlobal("fetch", request);
  const onWithdrawn = vi.fn(), onConfirmed = vi.fn();
  const props = { org: "1", month: "2026-10", disabled: false, prepared: null, onWithdrawn, onConfirmed };
  const view = render(<AccountingProductionCorrectionConfirmation {...props} />);
  fireEvent.click(screen.getByText("Проверить сохранённое исправление"));
  await screen.findByRole("region", { name: "Сохранённое исправление" });
  fireEvent.change(screen.getByLabelText("Основание отзыва исправления"), { target: { value: "Устаревший расчёт нужно заменить" } });
  fireEvent.click(screen.getByText("Отозвать неподтверждённое исправление"));
  expect(await screen.findByRole("alert")).toHaveTextContent("Связь прервалась");
  expect(screen.queryByText("Повторить сохранённое исправление")).toBeNull();
  view.unmount(); render(<AccountingProductionCorrectionConfirmation {...props} />);
  fireEvent.click(screen.getByText("Проверить сохранённое исправление"));
  await waitFor(() => expect(onWithdrawn).toHaveBeenCalledTimes(1));
  expect(onConfirmed).not.toHaveBeenCalled();
  expect(localStorage.length).toBe(0);
  expect(request.mock.calls.filter(([, init]) => init?.method === "POST")).toHaveLength(1);
});
it.each([true, false])("recovers a lost confirmation after remount without posting again; monetary=%s", async posted => {
  const prepared: PreparedCorrection = { digest: "c".repeat(64), createsEntry: posted, command: {
    original_entry_id: 7, method: "delta", posting_date: "2026-10-31", evidence: "Проверены исходные документы",
    expected_review_digest: "b".repeat(64), review: { policy_id: 2, expected_source_digest: "a".repeat(64),
      classifications: [{ line_id: 1, role: "excluded", evidence: "Строка исключена по документам" }], orders: [] } } };
  let saved: unknown = null;
  const request = vi.fn(async (url: RequestInfo | URL, init?: RequestInit) => {
    if (String(url).endsWith("/production-overhead-access")) return Response.json({ organization_id: 1, principal: "chief", can_confirm: true });
    if (init?.method === "POST") {
      const command = JSON.parse(String(init.body));
      saved = { organization_id: 1, month: "2026-10", actor: "chief", request_key: command.request_key, command,
        final_cost_certified: false, confirmed: true, withdrawn: false, posted, id: 11, sequence: 2, original_entry_id: 7,
        entry_id: posted ? 8 : null, preview: { digest: prepared.digest, snapshot: { command: prepared.command, creates_entry: posted } } };
      throw new TypeError("lost response");
    }
    return saved ? Response.json(saved) : new Response("{}", { status: 404 });
  });
  vi.stubGlobal("fetch", request);
  const onConfirmed = vi.fn(), onEntry = vi.fn(), onLock = vi.fn();
  const props = { org: "1", month: "2026-10", disabled: false, onConfirmed, onEntry, onLock, onWithdrawn: vi.fn() };
  const view = render(<AccountingProductionCorrectionConfirmation {...props} prepared={prepared} />);
  expect(request).not.toHaveBeenCalled();
  fireEvent.click(screen.getByText("Подтвердить проверенное исправление"));
  expect(await screen.findByRole("alert")).toHaveTextContent("Связь прервалась");
  expect(screen.getByRole("region", { name: "Сохранённое исправление" })).toBeVisible();
  expect(onConfirmed).not.toHaveBeenCalled();
  view.unmount(); const calls = request.mock.calls.length;
  render(<AccountingProductionCorrectionConfirmation {...props} prepared={null} />);
  expect(request).toHaveBeenCalledTimes(calls);
  fireEvent.click(screen.getByText("Проверить сохранённое исправление"));
  await waitFor(() => expect(onConfirmed).toHaveBeenCalledTimes(1));
  expect(screen.getByText("Исправление подтверждено · версия 2.")).toBeVisible();
  if (posted) { fireEvent.click(screen.getByText("Открыть проводку исправления №8")); expect(onEntry).toHaveBeenCalledWith(8); }
  else expect(screen.getByText("Разница равна нулю. Денежная проводка не создавалась.")).toBeVisible();
  expect(request.mock.calls.filter(([, init]) => init?.method === "POST")).toHaveLength(1);
  expect(localStorage.length).toBe(0);
  expect(onLock).toHaveBeenLastCalledWith(false);
});
