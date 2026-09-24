import { afterEach, expect, it, vi } from "vitest";

import { createClaim, listClaims, type ClaimCommand } from "@/lib/procurement-scoped-claims";

afterEach(() => vi.unstubAllGlobals());

it("rejects a claim page or command receipt from another legal entity", async () => {
  const fetcher = vi.fn().mockResolvedValueOnce({ ok: true, json: async () => ({
    organization_id: 8, items: [], next_after_id: null, unassigned_claims_excluded: true,
  }) }).mockResolvedValueOnce({ ok: true, json: async () => ({
    organization_id: 8, claim: { id: 9 }, ownership: { actor: "tester" },
  }) });
  vi.stubGlobal("fetch", fetcher);
  await expect(listClaims(7)).rejects.toThrow("не соответствует выбранному юрлицу");
  const command = { claim_key: "e1c33b7a-1b4f-4601-90e7-f97df5475244",
    supplier_id: 3, supplier: "Vendor", supplier_unp: "299999001", order_id: null,
    item: "Battery", reason: "Defect", claim_type: "брак", qty_affected: 1,
    amount_byn: "20.00", ownership_evidence: "Act" } satisfies ClaimCommand;
  await expect(createClaim(7, "tester", command)).rejects.toThrow("не соответствует выбранному юрлицу");
  expect(fetcher.mock.calls[1][0]).toBe("/api/procurement/organizations/7/claims");
  expect(fetcher.mock.calls[1][1]).toMatchObject({ method: "POST",
    headers: { "X-Expected-Principal": "tester" } });
});
