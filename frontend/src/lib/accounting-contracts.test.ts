import { afterEach, expect, it, vi } from "vitest";

import { searchAccountingContracts } from "@/lib/accounting-contracts";

afterEach(() => vi.unstubAllGlobals());

it("rejects a contract page for another counterparty", async () => {
  vi.stubGlobal("fetch", vi.fn(async () => ({ ok: true, json: async () => ({
    organization_id: 7, counterparty_id: 99, items: [],
  }) })));
  await expect(searchAccountingContracts("7", "17", "Д-1")).rejects.toThrow("другого юрлица или контрагента");
  expect(await searchAccountingContracts("7", "17", " ")).toEqual([]);
});
