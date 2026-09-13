import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { AccountingShipmentConfirm } from "./accounting-shipment-confirm";

afterEach(() => vi.unstubAllGlobals());
const digest = "a".repeat(64);
const props = { org: "1", sourceKey: "act", source: "source", body: JSON.stringify({ expected_basis_digest: digest }), onLock: vi.fn() };
const receipt = { organization_id: 1, source: "source", posted: true, basis_digest: digest, receipt_id: 1, entry_ids: [2] };

it("posts only after confirmation and retries identical body after lost response", async () => {
  const fetcher = vi.fn().mockRejectedValueOnce(new Error("lost"))
    .mockResolvedValueOnce({ ok: true, json: async () => receipt });
  vi.stubGlobal("fetch", fetcher);
  render(<AccountingShipmentConfirm {...props} />);
  expect(fetcher).not.toHaveBeenCalled();
  fireEvent.click(screen.getByText("Подтвердить проводки отгрузки"));
  fireEvent.click(await screen.findByText("Повторить подтверждение"));
  expect(await screen.findByRole("status")).toHaveTextContent("Отгрузка проведена");
  expect(fetcher.mock.calls[0]).toEqual(fetcher.mock.calls[1]);
});

it("requires recalculation after a stale basis rejection", async () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: false, status: 409, json: async () => ({ detail: "Basis changed" }) }));
  render(<AccountingShipmentConfirm {...props} />);
  fireEvent.click(screen.getByText("Подтвердить проводки отгрузки"));
  expect(await screen.findByRole("alert")).toHaveTextContent("новый расчёт");
  expect(screen.queryByRole("button")).toBeNull();
});

it("refreshes only after acknowledged posting and never retries a write for a refresh failure", async () => {
  const onPosted = vi.fn().mockRejectedValue(new Error("Report unavailable"));
  const fetcher = vi.fn().mockResolvedValue({ ok: true, json: async () => receipt });
  vi.stubGlobal("fetch", fetcher);
  render(<AccountingShipmentConfirm {...props} onPosted={onPosted} />);
  expect(onPosted).not.toHaveBeenCalled();
  fireEvent.click(screen.getByText("Подтвердить проводки отгрузки"));
  await waitFor(() => expect(onPosted).toHaveBeenCalledTimes(1));
  expect(await screen.findByRole("status")).toHaveTextContent("Отгрузка проведена. Не удалось обновить данные");
  expect(screen.queryByRole("button")).toBeNull();
  expect(fetcher).toHaveBeenCalledTimes(1);
});
