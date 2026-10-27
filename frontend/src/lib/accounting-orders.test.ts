import { afterEach, expect, it, vi } from "vitest";

import { searchAccountingProductionOrders } from "@/lib/accounting-orders";

afterEach(() => vi.unstubAllGlobals());

const order = {
  order: "ПР-17", order_source: "production", order_id: "17", order_number: "ПР-17",
  order_product: "Насос", order_quantity: "3", order_created_at: "2026-09-01T10:00:00",
  order_digest: "a".repeat(64), order_stage_at_ownership: "queue",
};

it("searches the selected organization's production ownership snapshots without caching", async () => {
  const fetcher = vi.fn().mockResolvedValue({ ok: true, json: async () => ({
    organization_id: 7, items: [order],
  }) });
  vi.stubGlobal("fetch", fetcher);
  expect(await searchAccountingProductionOrders("7", " ПР 17 ")).toEqual([order]);
  expect(fetcher.mock.calls[0][0]).toBe(
    "/api/accounting/organizations/7/manual-orders?q=%D0%9F%D0%A0%2017",
  );
  expect(fetcher.mock.calls[0][1]).toEqual({ cache: "no-store" });
  expect(await searchAccountingProductionOrders("7", " ")).toEqual([]);
  expect(await searchAccountingProductionOrders("2147483648", "17")).toEqual([]);
  expect(fetcher).toHaveBeenCalledTimes(1);
});

it("rejects order lists for another organization and malformed ownership snapshots", async () => {
  const fetcher = vi.fn().mockResolvedValue({ ok: true, json: async () => ({
    organization_id: 8, items: [order],
  }) });
  vi.stubGlobal("fetch", fetcher);
  await expect(searchAccountingProductionOrders("7", "17"))
    .rejects.toThrow("другой организации");

  fetcher.mockResolvedValue({ ok: true, json: async () => ({
    organization_id: 7, items: [{ ...order, order_source: "sales" }],
  }) });
  await expect(searchAccountingProductionOrders("7", "17"))
    .rejects.toThrow("неполную или некорректную запись");

  fetcher.mockResolvedValue({ ok: true, json: async () => ({
    organization_id: 7, items: [{ ...order, order_quantity: "2147483648" }],
  }) });
  await expect(searchAccountingProductionOrders("7", "17"))
    .rejects.toThrow("неполную или некорректную запись");

  fetcher.mockResolvedValue({ ok: true, json: async () => ({
    organization_id: 7, items: Array(51).fill(order),
  }) });
  await expect(searchAccountingProductionOrders("7", "17"))
    .rejects.toThrow("слишком много записей");
});
