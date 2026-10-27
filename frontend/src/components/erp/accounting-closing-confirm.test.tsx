import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { AccountingClosingConfirm } from "./accounting-closing-confirm";

afterEach(() => vi.unstubAllGlobals());
const command = { request_key: "00000000-0000-4000-8000-000000000001", expected_basis_digest: "a".repeat(64), expected_generation: 2, evidence: { bank: "checked" } };
const receipt = { organization_id: 1, month: "2026-10", request_key: command.request_key, closed: true, receipt_id: 4, digest: "b".repeat(64) };
it("retries the frozen command and keeps committed state when report refresh fails", async () => {
  const fetcher = vi.fn().mockRejectedValueOnce(new Error("lost"))
    .mockResolvedValueOnce({ ok: true, json: async () => receipt });
  vi.stubGlobal("fetch", fetcher);
  const onClosed = vi.fn().mockRejectedValue(new Error("refresh"));
  const props = { org: "1", month: "2026-10", command, onLock: vi.fn(), onClosed };
  const view = render(<AccountingClosingConfirm {...props} />);
  expect(fetcher).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button"));
  await screen.findByText("Проверить результат закрытия");
  view.rerender(<AccountingClosingConfirm {...props} command={{ ...command, expected_generation: 3 }} />);
  fireEvent.click(screen.getByRole("button"));
  expect(await screen.findByRole("status")).toHaveTextContent("Не удалось обновить отчёты");
  expect(fetcher.mock.calls[0]).toEqual(fetcher.mock.calls[1]);
  expect(onClosed).toHaveBeenCalledWith(4, true);
  expect(screen.queryByRole("button")).toBeNull();
});
