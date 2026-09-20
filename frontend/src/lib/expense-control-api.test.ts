import { webcrypto } from "node:crypto";

import { afterEach, beforeEach, expect, it, vi } from "vitest";

import { getUnmatchedActuals, hash } from "./expense-control-api";

beforeEach(() => vi.stubGlobal("crypto", webcrypto));
afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); });

it("accepts a signed unmatched row with an empty analytics string", async () => {
  const unsigned = {
    organization_id: 7,
    principal: "chief",
    year: 2026,
    month: 1,
    currency: "BYN",
    basis: "accrual",
    items: [{
      entry_id: 10,
      line_id: 12,
      posting_date: "2026-01-02",
      source: "expense-api",
      operation: "manual",
      account_code: "90.4",
      side: "debit",
      amount: "2.00",
      dimensions: { analytics: "" },
      reason: "нет статьи",
    }],
    next_after_line_id: 12,
  };
  const response = { ...unsigned, digest: await hash(unsigned) };
  const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => response });
  vi.stubGlobal("fetch", fetchMock);

  const result = await getUnmatchedActuals({ org: 7, principal: "chief" }, 2026, 1, "accrual", 12);

  expect(result.items[0].dimensions).toEqual({ analytics: "" });
  expect(fetchMock).toHaveBeenCalledWith(
    "/api/accounting/organizations/7/expense-actuals/unmatched?year=2026&month=1&currency=BYN&basis=accrual&after_line_id=12",
    { cache: "no-store" },
  );
});
