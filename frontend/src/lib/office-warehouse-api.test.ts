import { webcrypto } from "node:crypto";

import { afterEach, beforeEach, expect, it, vi } from "vitest";

import { fetchWarehouseProgress, reconcileWarehouseProgress, type WarehouseSnapshot } from "@/lib/office-shipping-api";
import { shippingFixture } from "@/test/office-shipping-fixtures";
import { warehouseFixture } from "@/test/office-warehouse-fixtures";

beforeEach(() => vi.stubGlobal("crypto", webcrypto));
afterEach(() => vi.unstubAllGlobals());

it("reads exact warehouse quantities and both accepted execution modes without caching or mutation", async () => {
  const context = await shippingFixture({ associated: true });
  const expected = warehouseFixture(context, { released: true, documentMode: true });
  const fetcher = vi.fn<typeof fetch>().mockResolvedValue(Response.json(expected)); vi.stubGlobal("fetch", fetcher);
  expect(await fetchWarehouseProgress(context)).toEqual(expected);
  expect(fetcher).toHaveBeenCalledWith("/api/office/docs/15/warehouse-progress", expect.objectContaining({ cache: "no-store" }));
  expect(fetcher.mock.calls[0][1]?.method).toBeUndefined();
});

const invalid: [string, (v: WarehouseSnapshot) => unknown][] = [
  ["other Office document", v => ({ ...v, office_document_id: 16 })],
  ["other session principal", v => ({ ...v, principal: "other-reviewer" })],
  ["other invoice revision", v => ({ ...v, progress: { ...v.progress, exact_invoice: { ...v.progress!.exact_invoice, expected_version: 99 } } })],
  ["missing server capability", v => ({ ...v, can_reconcile: undefined })],
  ["invented global coverage", v => ({ ...v, progress: { ...v.progress, coverage_complete: true } })],
  ["negative quantity", v => ({ ...v, progress: { ...v.progress, lines: [{ ...v.progress!.lines[0], shipped_qty: "-1.00" }] } })],
  ["unknown act execution mode", v => ({ ...v, progress: { ...v.progress, acts: [{ ...v.progress!.acts[0], execution_mode: "physical" }] } })],
  ["duplicate warehouse source", v => ({ ...v, progress: { ...v.progress, lines: [v.progress!.lines[0], v.progress!.lines[0]] } })],
  ["quantity not conserved", v => ({ ...v, progress: { ...v.progress, lines: [{ ...v.progress!.lines[0], expected_qty: "9.00" }] } })],
  ["partial quantities marked complete", v => ({ ...v, progress: { ...v.progress, state: "complete" } })],
  ["issued quantity without any act", v => ({ ...v, progress: { ...v.progress, state: "none_recorded", acts: [] } })],
  ["act without issued quantity", v => ({ ...v, progress: { ...v.progress, lines: v.progress!.lines.map(row => ({ ...row, shipped_qty: "0.00", reserved_qty: row.expected_qty })) } })],
];
it.each(invalid)("rejects %s rather than showing an empty or authorized state", async (_name, change) => {
  const context = await shippingFixture({ associated: true });
  vi.stubGlobal("fetch", vi.fn<typeof fetch>().mockResolvedValue(Response.json(change(warehouseFixture(context)))));
  await expect(fetchWarehouseProgress(context)).rejects.toThrow(/не прошли сверку/);
});

it("accepts explicit unassociated only without an expected association or action capability", async () => {
  const context = await shippingFixture();
  const data = { office_document_id: 15, principal: context.principal, document_stage: "ready", wms_ref: "", can_reconcile: false, state: "unassociated", progress: null };
  vi.stubGlobal("fetch", vi.fn<typeof fetch>().mockResolvedValue(Response.json(data)));
  expect((await fetchWarehouseProgress(context)).progress).toBeNull();
});

it("addresses only the selected document when reconciling and sends no quantity or stock command body", async () => {
  const context = await shippingFixture({ associated: true });
  const fetcher = vi.fn<typeof fetch>().mockResolvedValue(Response.json(warehouseFixture(context))); vi.stubGlobal("fetch", fetcher);
  await reconcileWarehouseProgress(context);
  expect(fetcher).toHaveBeenCalledTimes(1);
  expect(fetcher).toHaveBeenCalledWith("/api/office/docs/15/warehouse-progress/reconcile", { method: "POST", cache: "no-store" });
});

it("keeps a lost reconcile response uncertain without retrying the command", async () => {
  const context = await shippingFixture({ associated: true });
  const fetcher = vi.fn<typeof fetch>().mockRejectedValue(new TypeError("synthetic connection loss")); vi.stubGlobal("fetch", fetcher);
  await expect(reconcileWarehouseProgress(context)).rejects.toMatchObject({ uncertain: true });
  expect(fetcher).toHaveBeenCalledTimes(1);
});
