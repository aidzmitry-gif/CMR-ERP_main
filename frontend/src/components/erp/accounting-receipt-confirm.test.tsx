import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { AccountingReceiptConfirm } from "./accounting-receipt-confirm";

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });
const command = { digest: "a".repeat(64), expected_version: 2 };
const response = { organization_id: 7, source: "procurement:receipt:9", source_version: 2, digest: command.digest, entry_id: 12 };
const source = { organization_id: 7, id: 9, version: 2, status: "posted", entry_id: 12 };
it("retries the same body after a lost response and verifies durable source", async () => {
  const fetcher = vi.fn().mockRejectedValueOnce(new Error("Lost response"))
    .mockResolvedValueOnce({ ok: true, json: async () => response })
    .mockResolvedValueOnce({ ok: true, json: async () => source });
  vi.stubGlobal("fetch", fetcher);
  const onLock = vi.fn(), onVerified = vi.fn();
  render(<AccountingReceiptConfirm org="7" receiptId={9} version={2} command={command} onLock={onLock} onVerified={onVerified} />);
  fireEvent.click(screen.getByRole("button"));
  expect(await screen.findByRole("alert")).toHaveTextContent("Параметры зафиксированы");
  expect(onVerified).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: "Повторить подтверждение" }));
  expect(await screen.findByRole("status")).toHaveTextContent("Операция № 12");
  expect(fetcher.mock.calls[0][1].body).toBe(fetcher.mock.calls[1][1].body);
  expect(fetcher.mock.calls[2][0]).toBe("/api/accounting/organizations/7/receipts/9/source");
  expect(onVerified).toHaveBeenCalledTimes(1);
});
it("does not announce success for a mismatched stored posting", async () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValueOnce({ ok: true, json: async () => response }).mockResolvedValueOnce({ ok: true, json: async () => ({ ...source, entry_id: 13 }) }));
  const onVerified = vi.fn();
  render(<AccountingReceiptConfirm org="7" receiptId={9} version={2} command={command} onLock={() => {}} onVerified={onVerified} />);
  fireEvent.click(screen.getByRole("button"));
  expect(await screen.findByRole("alert")).toHaveTextContent("не подтверждает");
  expect(onVerified).not.toHaveBeenCalled();
  expect(screen.queryByRole("status")).not.toBeInTheDocument();
});
