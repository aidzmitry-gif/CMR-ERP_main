import { webcrypto } from "node:crypto";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { lineKey, loadPending, parsePreview, prepare, savePending, type Preview } from "./invoice-physical-shipment-api";
const hash = "a".repeat(64);
const scope = { organization_id: 1, document_id: 2, deal_id: 3 };
const preview: Preview = { identity: { organization_id: 1, document_id: 2, document_version: 1, content_sha256: hash }, reservation_digest: hash, remaining_digest: hash, physical_digest: hash,
  lines: [{ line_no: 1, sku_code: "A", warehouse: "W", original_qty: "2.00", remaining_qty: "2.00", physical: "5.00", reserved: "2.00", free: "3.00", blocking_reason: null, execution_mode: "document", prohibit_negative_stock: true, stock_issue: null }] };
beforeEach(() => { vi.stubGlobal("crypto", webcrypto); sessionStorage.clear(); });
afterEach(() => vi.unstubAllGlobals());
it("freezes document mode for recovery of the same manually entered waybill", () => {
  const pending = prepare(scope, preview, { [lineKey(preview.lines[0])]: "1" }, "2026-01-01", "Накладная 17 от 01.01.2026");
  expect(pending.execution_mode).toBe("document");
  savePending(pending); expect(loadPending(scope)).toEqual(pending);
});
it("freezes WMS origin independently of document mode", () => {
  const p = structuredClone(preview); p.lines[0].execution_mode = "wms";
  expect(prepare(scope, p, { [lineKey(p.lines[0])]: "1" }, "2026-01-01", "Накладная 18").execution_mode).toBe("wms");
});
it("rejects a batch mixing warehouses with different execution modes", () => {
  const p = structuredClone(preview); p.lines.push({ ...p.lines[0], warehouse: "Other", execution_mode: "wms" });
  expect(() => prepare(scope, p, Object.fromEntries(p.lines.map(l => [lineKey(l), "1"])), "2026-01-01", "Накладная 19")).toThrow("отдельно");
});
it("unknown server mode cannot silently become document or WMS mode", () => {
  const p = structuredClone(preview); delete p.lines[0].execution_mode;
  expect(() => parsePreview(p, p.identity)).toThrow();
});
import { previewShipment, shipmentHistory } from "./invoice-physical-shipment-api";
vi.mock("./document-register-api", () => ({ fetchRegisterDocument: vi.fn(async () => ({ kind: "invoice", version: 1, content_sha256: "a".repeat(64) })) }));
it("accounting staff without WMS permission can obtain document preview", async () => {
  const fetcher = vi.fn().mockResolvedValueOnce({ ok: false, status: 403, json: async () => ({}) })
    .mockResolvedValueOnce({ ok: true, status: 200, json: async () => preview });
  vi.stubGlobal("fetch", fetcher);
  expect((await previewShipment(scope)).lines[0].execution_mode).toBe("document");
  expect(fetcher.mock.calls[1][0]).toContain("/document-shipments/preview");
});
it("accounting staff without WMS permission can read document history", async () => {
  const fetcher = vi.fn().mockResolvedValueOnce({ ok: false, status: 403, json: async () => ({}) })
    .mockResolvedValueOnce({ ok: true, status: 200, json: async () => ({ identity: preview.identity, items: [], next_after_id: null }) });
  vi.stubGlobal("fetch", fetcher);
  expect((await shipmentHistory(scope, preview.identity)).items).toEqual([]);
  expect(fetcher.mock.calls[1][0]).toContain("/document-shipments/history");
});
