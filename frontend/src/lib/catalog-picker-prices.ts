import type { PickerPrices } from "./api";

const object = (value: unknown): value is Record<string, unknown> =>
  value !== null && typeof value === "object" && !Array.isArray(value);
const string = (value: unknown, max: number): value is string =>
  typeof value === "string" && value.trim().length > 0 && value.length <= max;
const guid = (value: unknown) => typeof value === "string"
  && /^[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}$/.test(value);
const count = (value: unknown): value is number =>
  typeof value === "number" && Number.isInteger(value) && value >= 0 && value <= 10000;
const date = (value: unknown, zoned = false): value is string => typeof value === "string"
  && (zoned ? /^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d{1,6})?(?:Z|[+-]\d\d:\d\d)$/
    : /^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d{1,6})?$/).test(value)
  && Number.isFinite(Date.parse(value));

/** Validate this endpoint's DTO before it enters render state; preserve decimal strings. */
export function readPickerPrices(value: unknown): PickerPrices | null {
  if (!object(value) || !Array.isArray(value.rows) || value.rows.length > 10000) return null;
  if (value.status === "unavailable") {
    return value.snapshot === null && value.rows.length === 0 ? value as unknown as PickerPrices : null;
  }
  const s = value.snapshot;
  if (value.status !== "reference" || !object(s) || !guid(s.id) || !string(s.kind, 255)
    || !date(s.source_as_of) || !date(s.observed_at, true) || s.response_complete !== true
    || s.full_coverage !== false || s.activity_verified !== false
    || !count(s.row_count) || !count(s.mapped) || !count(s.held) || !count(s.unmapped)
    || s.mapped + s.held + s.unmapped !== s.row_count || value.rows.length !== s.mapped) return null;
  const keys = new Set<string>();
  for (const row of value.rows) {
    if (!object(row) || !Number.isSafeInteger(row.sku_id) || (row.sku_id as number) <= 0
      || !string(row.sku_code, 64) || !string(row.unit, 255) || !string(row.currency, 32)
      || row.kind !== s.kind || typeof row.price_includes_vat !== "boolean"
      || row.application_status !== "reference_only" || !guid(row.characteristic_guid)
      || !guid(row.package_guid) || !date(row.effective_at) || !string(row.price, 80)
      || !/^-?\d+(?:\.\d+)?(?:[Ee][+-]?\d+)?$/.test(row.price)
      || !Number.isFinite(Number(row.price)) || Number(row.price) < 0) return null;
    const key = JSON.stringify([row.sku_id, row.characteristic_guid, row.package_guid, row.currency]);
    if (keys.has(key)) return null;
    keys.add(key);
  }
  return value as unknown as PickerPrices;
}
