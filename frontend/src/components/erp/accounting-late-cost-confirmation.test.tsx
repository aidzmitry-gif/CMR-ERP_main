import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { AccountingLateCostConfirmation } from "./accounting-late-cost-confirmation";
import { pendingLateCost, rememberLateCost } from "@/lib/late-cost-journal";

const data = { allocation: { expected_version: 1, policy_id: 2, posting_date: "2026-09-12", capitalizable_amount_byn: "100.00", excluded_amount_byn: "0.00", classification_evidence: "Reviewed source costs" }, accounts: { settlement_account: "60", excluded_costs: [] }, request_key: "00000000-0000-4000-8000-000000000001", expected_digest: "a".repeat(64), expected_basis_digest: "b".repeat(64) };
const command = { org: "1", expenseId: 7, principal: "accountant", body: JSON.stringify(data) };
const receipt = { organization_id: 1, expense_id: 7, source_version: 1, entry_id: 9, request_key: data.request_key, digest: data.expected_digest, basis_digest: data.expected_basis_digest, posted: true };
afterEach(() => { vi.unstubAllGlobals(); sessionStorage.clear(); });
it("persists before sending and retries exactly after a lost response", async () => {
  const onPosted = vi.fn(), onLock = vi.fn();
  const fetcher = vi.fn().mockImplementationOnce(() => { expect(pendingLateCost(sessionStorage, "1", "accountant")).toEqual(command); throw new Error("Lost response"); })
    .mockResolvedValueOnce({ ok: true, json: async () => receipt });
  vi.stubGlobal("fetch", fetcher);
  render(<AccountingLateCostConfirmation org="1" principal="accountant" prepared={command} onPosted={onPosted} onLock={onLock} />);
  await waitFor(() => expect(screen.getByText("Подтвердить проводки")).toBeEnabled());
  fireEvent.click(screen.getByText("Подтвердить проводки")); await screen.findByText("Lost response");
  fireEvent.click(screen.getByText("Повторить проведение без дубля")); await screen.findByText("Проведение подтверждено.");
  expect(fetcher.mock.calls[0]).toEqual(fetcher.mock.calls[1]); expect(onPosted).toHaveBeenCalledWith(7);
  expect(pendingLateCost(sessionStorage, "1", "accountant")).toBeNull();
});
it("recovers without auto-send and resolves using verified readback", async () => {
  rememberLateCost(sessionStorage, command);
  const fetcher = vi.fn().mockResolvedValue({ ok: true, json: async () => receipt }); vi.stubGlobal("fetch", fetcher);
  render(<AccountingLateCostConfirmation org="1" principal="accountant" prepared={null} onPosted={vi.fn()} onLock={vi.fn()} />);
  await screen.findByText("Повторить проведение без дубля"); expect(fetcher).not.toHaveBeenCalled();
  fireEvent.click(screen.getByText("Проверить результат проведения")); await screen.findByText("Проведение подтверждено.");
  expect(fetcher).toHaveBeenCalledWith("/api/accounting/organizations/1/additional-expenses/7/posting", { cache: "no-store" });
});
it.each([false, true])("definitive rejection clears only a first attempt (recovered=%s)", async recovered => {
  if (recovered) rememberLateCost(sessionStorage, command);
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: false, status: 409, json: async () => ({ detail: "Changed basis" }) }));
  render(<AccountingLateCostConfirmation org="1" principal="accountant" prepared={command} onPosted={vi.fn()} onLock={vi.fn()} />);
  const label = recovered ? "Повторить проведение без дубля" : "Подтвердить проводки";
  await waitFor(() => expect(screen.getByText(label)).toBeEnabled()); fireEvent.click(screen.getByText(label));
  await screen.findByText("Changed basis");
  expect(pendingLateCost(sessionStorage, "1", "accountant")).toEqual(recovered ? command : null);
});
