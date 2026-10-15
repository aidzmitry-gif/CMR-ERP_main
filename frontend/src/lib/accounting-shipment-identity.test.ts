import { afterEach, expect, it, vi } from "vitest";
import { shipmentIdentity } from "./invoice-physical-shipment-api";
afterEach(() => vi.unstubAllGlobals());
it("loads exact accounting identity after actual CRM HTTP403 without mocking the document API", async () => {
  const scope={organization_id:1,deal_id:2,document_id:3};
  const identity={...scope,document_version:4,content_sha256:"a".repeat(64)};
  const fetcher=vi.fn().mockResolvedValueOnce({ok:false,status:403,json:async()=>({})})
    .mockResolvedValueOnce({ok:true,status:200,json:async()=>identity});
  vi.stubGlobal("fetch",fetcher);
  expect(await shipmentIdentity(scope)).toEqual({organization_id:1,document_id:3,document_version:4,content_sha256:"a".repeat(64)});
  expect(fetcher.mock.calls[0][0]).toContain("/api/sales/");
  expect(fetcher.mock.calls[1][0]).toBe("/api/accounting/organizations/1/deals/2/stock-issue-invoices/3");
});
