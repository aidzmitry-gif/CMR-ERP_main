import { LogisticsReadError } from "@/lib/logistics-api";

export type CostOrganization = { id: number; name: string; unp: string };
export type CostCatalog = { version: 1; principal: string; items: CostOrganization[] };
export type CostSelection = { organization_id: number; principal: string };
export type ImportFreight = {
  status: "known" | "partial" | "unknown";
  qualified_import_count: number; warehouse_import_count: number; known_count: number;
  unpriced_count: number; excluded_nonwarehouse_count: number;
  known_total: string | null; total: string | null; known_average: string | null;
};
export type OwnedCostReview = CostSelection & {
  version: 1; status: "partial"; complete_cost_coverage: false;
  source: "explicit_own_logistics_imports"; posting_status: "not_verified";
  unavailable_sections: ("tariffs" | "tenders" | "audit")[]; import_freight: ImportFreight;
};

function invalid(): never { throw new LogisticsReadError(502); }
function object(v: unknown): v is Record<string, unknown> { return v !== null && typeof v === "object" && !Array.isArray(v); }
function principal(v: unknown): v is string { return typeof v === "string" && v.trim().length > 0 && v.length <= 4096; }
function id(v: unknown): v is number { return Number.isSafeInteger(v) && Number(v) > 0; }
function count(v: unknown): v is number { return Number.isSafeInteger(v) && Number(v) >= 0; }
function money(v: unknown): v is string { return typeof v === "string" && v.length <= 64 && /^(0|[1-9]\d*)\.\d{2}$/.test(v); }
function cents(v: string): bigint { const [whole, fraction] = v.split("."); return BigInt(whole) * 100n + BigInt(fraction); }
function unavailable(v: unknown): boolean {
  if (!Array.isArray(v)) return false;
  const values: unknown[] = v;
  return values.length === 3 && new Set(values).size === 3 && ["tariffs", "tenders", "audit"].every(key => values.includes(key));
}

export function parseCostCatalog(v: unknown): CostCatalog {
  if (!object(v) || v.version !== 1 || !principal(v.principal) || !Array.isArray(v.items)) invalid();
  const seen = new Set<number>();
  for (const item of v.items) {
    if (!object(item) || !id(item.id) || seen.has(item.id) || typeof item.name !== "string" || !item.name.trim()
      || typeof item.unp !== "string") invalid();
    seen.add(item.id);
  }
  return v as unknown as CostCatalog;
}

export function parseOwnedCostReview(v: unknown, selected: CostSelection): OwnedCostReview {
  if (!object(v) || v.version !== 1 || v.organization_id !== selected.organization_id || v.principal !== selected.principal
    || !id(selected.organization_id) || !principal(selected.principal) || v.status !== "partial" || v.complete_cost_coverage !== false
    || v.source !== "explicit_own_logistics_imports" || v.posting_status !== "not_verified"
    || !unavailable(v.unavailable_sections)
    || !object(v.import_freight)) invalid();
  const f = v.import_freight;
  for (const key of ["qualified_import_count", "warehouse_import_count", "known_count", "unpriced_count", "excluded_nonwarehouse_count"]) {
    if (!count(f[key])) invalid();
  }
  const { qualified_import_count: qualified, warehouse_import_count: warehouse, known_count: known,
    unpriced_count: unpriced, excluded_nonwarehouse_count: excluded } = f as unknown as ImportFreight;
  if (qualified !== warehouse + excluded || warehouse !== known + unpriced || !Number.isSafeInteger(warehouse + excluded)
    || !Number.isSafeInteger(known + unpriced) || f.status !== (!known ? "unknown" : unpriced ? "partial" : "known")) invalid();
  if (!known) {
    if (f.known_total !== null || f.total !== null || f.known_average !== null) invalid();
  } else {
    if (!money(f.known_total) || cents(f.known_total) < BigInt(known) || !money(f.known_average)
      || cents(f.known_average) !== (cents(f.known_total) * 2n + BigInt(known)) / (2n * BigInt(known))
      || f.total !== (unpriced ? null : f.known_total)) invalid();
  }
  return v as unknown as OwnedCostReview;
}

async function read(path: string, signal?: AbortSignal): Promise<unknown> {
  const response = await fetch(path, { cache: "no-store", signal });
  if (!response.ok) throw new LogisticsReadError(response.status);
  try { return await response.json(); } catch { return invalid(); }
}

export async function fetchCostCatalog(signal?: AbortSignal): Promise<CostCatalog> {
  return parseCostCatalog(await read("/api/logistics/cost-organizations", signal));
}

export async function fetchOwnedCostReview(selected: CostSelection, signal?: AbortSignal): Promise<OwnedCostReview> {
  if (!id(selected.organization_id) || !principal(selected.principal)) invalid();
  return parseOwnedCostReview(await read(`/api/logistics/organizations/${selected.organization_id}/cost-insights`, signal), selected);
}

export function formatFreightByn(value: string | null): string {
  if (value === null) return "Не определён";
  if (!money(value)) invalid();
  const [whole, fraction] = value.split(".");
  return `${BigInt(whole).toLocaleString("ru-RU")},${fraction} Br`;
}
