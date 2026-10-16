import { afterEach, expect, it, vi } from "vitest";

import { searchAccountingBuyers } from "@/lib/accounting-buyers";

afterEach(() => vi.unstubAllGlobals());

it("rejects buyer options from another legal entity", async () => {
  const fetcher = vi.fn().mockResolvedValue({ ok: true, json: async () => ({
    organization_id: 8, items: [{ id: 1, name: "Other", unp: "", revision: 1 }],
  }) });
  vi.stubGlobal("fetch", fetcher);
  await expect(searchAccountingBuyers("7", "Buyer")).rejects.toThrow("другого юрлица");
  expect(fetcher.mock.calls[0][0]).toBe("/api/accounting/organizations/7/sales/buyers?q=Buyer");
  expect(await searchAccountingBuyers("7", " ")).toEqual([]);
  expect(fetcher).toHaveBeenCalledTimes(1);
});
