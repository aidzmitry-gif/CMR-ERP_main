import type { InventoryCount, InventoryDetail, InventoryOrganization } from "@/lib/wms-inventory";
import type { CyclePlan } from "@/lib/wms-cycle-count";

export const organizations: InventoryOrganization[] = [{ id: 1, name: "Компания А", unp: "111" }, { id: 2, name: "Компания Б", unp: "222" }];
export const confirmation = { expected_source: "wms_physical" as const, source_evidence: "Полнота проверена", journal_complete: true as const };
export const provenance = { organization_id: 1, expected_source: "wms_physical", source_evidence: "Акт пересчёта", journal_confirmed_by: "operator", journal_confirmed_at: "2026-09-09T12:00:00" };
export function inventory(overrides: Partial<InventoryCount> = {}): InventoryCount {
  return { ...provenance, id: 7, number: "ИНВ-7", warehouse: "Склад А", status: "open", note: "", created_at: null, completed_at: null,
    snapshot_version: "a".repeat(64), snapshot_cutoff: 31, snapshot_at: "2026-09-09T12:01:00", ...overrides };
}
export function detail(overrides: Partial<InventoryDetail> = {}): InventoryDetail {
  return { ...inventory(), lines: [{ id: 10, sku_code: "SKU", sku_title: "Товар", unit: "шт", expected_qty: 30, counted_qty: 27,
      unit_cost: null, variance: -3, variance_value: null, note: "" }],
    summary: { lines: 1, counted: 1, shortages: 1, surpluses: 0, shortage_value: null, surplus_value: null, net_value: null }, ...overrides };
}
export function plan(overrides: Partial<CyclePlan> = {}): CyclePlan {
  return { ...provenance, id: 3, warehouse: "Склад А", zone: null, cadence_days: 30, next_due_date: "2020-01-01", last_run_at: null, active: true, abc_class: null, ...overrides };
}
export const jsonResponse = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
export function deferred<T>() { let resolve!: (value: T) => void; let reject!: (reason: unknown) => void;
  const promise = new Promise<T>((yes, no) => { resolve = yes; reject = no; }); return { promise, resolve, reject }; }
