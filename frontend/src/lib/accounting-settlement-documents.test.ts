import { afterEach, expect, it, vi } from "vitest";

import { searchAccountingSettlementDocuments } from "@/lib/accounting-settlement-documents";

afterEach(() => vi.unstubAllGlobals());

it("rejects a settlement document page for another counterparty", async () => {
  vi.stubGlobal("fetch", vi.fn(async () => ({ ok: true, json: async () => ({
    organization_id: 7, counterparty_id: 99, items: [],
  }) })));
  await expect(searchAccountingSettlementDocuments("7", "17", "ТН-1"))
    .rejects.toThrow("другого юрлица или контрагента");
  vi.stubGlobal("fetch", vi.fn(async () => ({ ok: true, json: async () => ({
    organization_id: 7, counterparty_id: 17, items: [{ source: "procurement", id: 2,
      number: "ТН-1", version: 3, reference: "procurement:receipt:2:1" }],
  }) })));
  await expect(searchAccountingSettlementDocuments("7", "17", "ТН-1"))
    .rejects.toThrow("некорректные записи");
  expect(await searchAccountingSettlementDocuments("7", "17", " ")).toEqual([]);
});
