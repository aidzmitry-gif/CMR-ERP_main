import type { StockRow } from "./api";

export const PICKER_COLUMNS = [
  { id: "title", label: "Наименование", width: 280, min: 180, max: 560, required: true },
  { id: "code", label: "Код", width: 105, min: 80, max: 240, required: false },
  { id: "warehouse", label: "Склад", width: 140, min: 100, max: 300, required: false },
  { id: "on", label: "Остаток", width: 82, min: 72, max: 160, required: false },
  { id: "reserved", label: "Резерв", width: 82, min: 72, max: 160, required: false },
  { id: "free", label: "Свободно", width: 88, min: 72, max: 160, required: false },
  { id: "price", label: "Цены", width: 135, min: 105, max: 260, required: false },
  { id: "quantity", label: "В подбор", width: 96, min: 88, max: 180, required: true },
] as const;
export type PickerColumnId = typeof PICKER_COLUMNS[number]["id"];
export type PickerColumnSettings = Record<PickerColumnId, { width: number; visible: boolean; order: number }>;
export const PICKER_COLUMNS_KEY = "erp.catalog-picker.columns.v1";

export function pickerColumnDefaults(): PickerColumnSettings {
  return Object.fromEntries(PICKER_COLUMNS.map((c, order) => [c.id, {
    width: c.width, visible: c.id !== "code", order,
  }])) as PickerColumnSettings;
}

/** Only allow known layout numbers/flags; no SKU, price or customer data is persisted. */
export function readPickerColumns(raw: string | null): PickerColumnSettings {
  const defaults = pickerColumnDefaults();
  try {
    const saved: unknown = JSON.parse(raw ?? "null");
    if (!saved || typeof saved !== "object") return defaults;
    const positions: number[] = [];
    for (const c of PICKER_COLUMNS) {
      const item = (saved as Record<string, unknown>)[c.id];
      if (!item || typeof item !== "object") continue;
      const { width, visible, order } = item as { width?: unknown; visible?: unknown; order?: unknown };
      if (typeof width === "number" && Number.isFinite(width)) {
        defaults[c.id].width = Math.round(Math.max(c.min, Math.min(c.max, width)));
      }
      if (!c.required && typeof visible === "boolean") defaults[c.id].visible = visible;
      if (typeof order === "number" && Number.isInteger(order) && order >= 0 && order < PICKER_COLUMNS.length) positions.push(order);
    }
    // Older saved layouts have no order. Reject incomplete/duplicate positions together.
    if (positions.length === PICKER_COLUMNS.length && new Set(positions).size === PICKER_COLUMNS.length) {
      PICKER_COLUMNS.forEach((c, index) => { defaults[c.id].order = positions[index]; });
    }
  } catch { /* Corrupt or blocked storage uses the compact default. */ }
  return defaults;
}

export function orderedPickerColumns(settings: PickerColumnSettings) {
  return [...PICKER_COLUMNS].sort((a, b) => settings[a.id].order - settings[b.id].order);
}

export function movePickerColumn(settings: PickerColumnSettings, id: PickerColumnId, direction: -1 | 1): PickerColumnSettings {
  const ordered = orderedPickerColumns(settings);
  const index = ordered.findIndex(c => c.id === id);
  const neighbor = ordered[index + direction];
  if (index < 0 || !neighbor) return settings;
  return { ...settings,
    [id]: { ...settings[id], order: settings[neighbor.id].order },
    [neighbor.id]: { ...settings[neighbor.id], order: settings[id].order },
  };
}

export function compactSkuCode(code: string): string {
  return code.length > 18 ? `${code.slice(0, 7)}…${code.slice(-6)}` : code;
}

export interface PickerWarehouseView {
  warehouse: string;
  on: number | null;
  reserved: number | null;
  free: number | null;
  prices: number[];
}

const quantity = (value: unknown): number | null =>
  typeof value === "number" && Number.isFinite(value) ? value : null;
const nonnegative = (value: unknown): number | null => {
  const parsed = quantity(value);
  return parsed != null && parsed >= 0 ? parsed : null;
};

/** Duplicate warehouse price rows never multiply stock. Conflicting stock is unknown. */
export function pickerWarehouseViews(rows: StockRow[]): Record<string, PickerWarehouseView[]> {
  const grouped = new Map<string, Map<string, PickerWarehouseView>>();
  for (const row of rows) {
    if (!row || typeof row.sku_code !== "string" || !row.sku_code
      || typeof row.warehouse !== "string" || !row.warehouse.trim()) continue;
    const warehouses = grouped.get(row.sku_code) ?? new Map<string, PickerWarehouseView>();
    grouped.set(row.sku_code, warehouses);
    const on = quantity(row.qty_available), reserved = nonnegative(row.qty_reserved);
    const price = nonnegative(row.price);
    const prior = warehouses.get(row.warehouse);
    if (prior) {
      if (prior.on !== on) prior.on = null;
      if (prior.reserved !== reserved) prior.reserved = null;
      prior.free = prior.on == null || prior.reserved == null ? null : Math.max(0, prior.on - prior.reserved);
      if (price != null && !prior.prices.includes(price)) prior.prices.push(price);
    } else warehouses.set(row.warehouse, {
      warehouse: row.warehouse, on, reserved,
      free: on == null || reserved == null ? null : Math.max(0, on - reserved),
      prices: price == null ? [] : [price],
    });
  }
  return Object.fromEntries([...grouped].map(([code, warehouses]) => [code, [...warehouses.values()]]));
}
