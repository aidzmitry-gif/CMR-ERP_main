import {
  type InventoryConfirmation, type InventoryDetail, type InventoryProvenance,
  inventoryJson, inventoryRequest, organizationQuery,
} from "@/lib/wms-inventory";

const BASE = process.env.BACKEND_URL ?? "http://127.0.0.1:8000";

export interface CyclePlan extends InventoryProvenance {
  id: number;
  warehouse: string;
  zone: string | null;
  cadence_days: number;
  next_due_date: string | null;
  last_run_at: string | null;
  active: boolean;
  abc_class: string | null;
}

export interface CyclePlanCreate extends InventoryConfirmation {
  organization_id: number;
  warehouse: string;
  zone?: string | null;
  cadence_days: number;
  next_due_date: string;
}

export function fetchCyclePlansServer(headers: Record<string, string>, organizationId?: number | null) {
  return inventoryRequest<CyclePlan[]>(`${BASE}/wms/cycle-plans${organizationQuery(organizationId)}`, { cache: "no-store", headers });
}

export function createCyclePlan(body: CyclePlanCreate) {
  return inventoryRequest<CyclePlan>("/api/wms/cycle-plans", inventoryJson("POST", body));
}

export function fetchCyclePlans(organizationId: number) {
  return inventoryRequest<CyclePlan[]>(`/api/wms/cycle-plans${organizationQuery(organizationId)}`, { cache: "no-store" });
}

export function runCyclePlan(id: number, confirmation: InventoryConfirmation) {
  return inventoryRequest<InventoryDetail>(`/api/wms/cycle-plans/${id}/run`, inventoryJson("POST", confirmation));
}
