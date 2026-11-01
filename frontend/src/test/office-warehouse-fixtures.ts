import type { ShippingContext, WarehouseSnapshot } from "@/lib/office-shipping-api";

export function warehouseFixture(context: ShippingContext, options: { state?: "none_recorded" | "partial" | "complete"; released?: boolean; documentMode?: boolean; canReconcile?: boolean } = {}): WarehouseSnapshot {
  const state = options.state ?? "partial", complete = state === "complete", none = state === "none_recorded";
  return { office_document_id: context.source_snapshot.document_id, principal: context.principal, document_stage: context.document_stage,
    can_reconcile: options.canReconcile ?? true, wms_ref: "", state: "observed", progress: {
      schema_version: 1, exact_invoice: context.association!.exact_invoice, scope: "canonical_invoice_reservation", coverage_complete: false, state,
      lines: [
        { source: "synthetic-source-W", line_no: 1, sku_code: "УЧ-ТОВАР-01", warehouse: "W", expected_qty: "2.00", shipped_qty: none ? "0.00" : "2.00", reserved_qty: none ? "2.00" : "0.00", released_qty: "0.00" },
        { source: "synthetic-source-W2", line_no: 1, sku_code: "УЧ-ТОВАР-01", warehouse: "W2", expected_qty: "3.00", shipped_qty: complete ? "3.00" : "0.00", reserved_qty: complete || options.released ? "0.00" : "3.00", released_qty: !complete && options.released ? "3.00" : "0.00" },
      ],
      acts: none ? [] : [{ act_id: 1, source_key: "11111111-1111-4111-8111-111111111111", digest: "a".repeat(64), operation_date: "2026-11-01", execution_mode: options.documentMode ? "document" : "wms" }],
      releases: options.released ? [{ release_id: 1, digest: "b".repeat(64) }] : [], basis_digest: "d".repeat(64),
    } };
}
