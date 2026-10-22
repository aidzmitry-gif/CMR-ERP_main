import { describe, expect, it } from "vitest";
import type { StockRow } from "./api";
import { compactSkuCode, movePickerColumn, orderedPickerColumns, pickerColumnDefaults, pickerWarehouseViews, readPickerColumns } from "./catalog-picker-table";

const row = (overrides: Partial<StockRow> = {}): StockRow => ({
  sku_code: "A", warehouse: "Склад 1", qty_available: 10, qty_reserved: 3,
  qty_forecast: 0, price: 120, ...overrides,
});

describe("product picker table presentation", () => {
  it("keeps stocks and distinct prices per warehouse, including zero stock", () => {
    expect(pickerWarehouseViews([row(), row({ price: 140 }), row({ warehouse: "Склад 2", qty_available: 0, qty_reserved: 0, price: 135 })]).A)
      .toEqual([{ warehouse: "Склад 1", on: 10, reserved: 3, free: 7, prices: [120, 140] },
        { warehouse: "Склад 2", on: 0, reserved: 0, free: 0, prices: [135] }]);
  });
  it("never double counts duplicate warehouse/price rows", () => {
    expect(pickerWarehouseViews([row(), row()]).A).toHaveLength(1);
    expect(pickerWarehouseViews([row(), row()]).A[0]).toMatchObject({ on: 10, reserved: 3, free: 7, prices: [120] });
  });
  it("marks conflicting quantities unknown rather than summing price rows", () => {
    expect(pickerWarehouseViews([row(), row({ qty_available: 20 })]).A[0]).toMatchObject({ on: null, reserved: 3, free: null });
  });
  it("missing/invalid numbers stay unknown, never become zero or NaN prices", () => {
    const raw = { ...row(), qty_available: null, qty_reserved: "3", price: NaN } as unknown as StockRow;
    expect(pickerWarehouseViews([raw]).A[0]).toMatchObject({ on: null, reserved: null, free: null, prices: [] });
    expect(pickerWarehouseViews([])).toEqual({});
  });
  it("retains confirmed zero price, clamps over-reserved free to zero", () => {
    expect(pickerWarehouseViews([row({ price: 0, qty_reserved: 12 })]).A[0]).toMatchObject({ free: 0, prices: [0] });
  });
  it("shows a confirmed negative on-hand from the source without allowing negative price", () => {
    expect(pickerWarehouseViews([row({ qty_available: -2, qty_reserved: 0, price: -10 })]).A[0])
      .toMatchObject({ on: -2, reserved: 0, free: 0, prices: [] });
  });
  it("does not assign unknown warehouse data to a made-up main warehouse", () => {
    expect(pickerWarehouseViews([row({ warehouse: "" })])).toEqual({});
  });
  it("bounds widths, ignores foreign layout fields, keeps required columns visible", () => {
    expect(readPickerColumns(JSON.stringify({ title: { width: 1, visible: false }, price: { width: 9999, visible: false }, skuData: "discard" })))
      .toEqual({ ...pickerColumnDefaults(), title: { ...pickerColumnDefaults().title, width: 180, visible: true }, price: { ...pickerColumnDefaults().price, width: 260, visible: false } });
  });
  it.each([null, "{broken", "[]", '"bad"'])("uses defaults for corrupt storage %s", (raw) => {
    expect(readPickerColumns(raw)).toEqual(pickerColumnDefaults());
  });
  it("shortens only the display code, preserving readable codes", () => {
    expect(compactSkuCode("SRC-123456789012345678901234567890")).toBe("SRC-123…567890");
    expect(compactSkuCode("6СТ-190")).toBe("6СТ-190");
  });
});

describe("product picker column order", () => {
  const defaultIds = ["title", "code", "warehouse", "on", "reserved", "free", "price", "quantity"];
  it("retains old v1 widths and visibility while supplying default order", () => {
    const legacy = Object.fromEntries(Object.entries(pickerColumnDefaults()).map(([id, settings]) => [id, { width: settings.width + 10, visible: id === "price" ? false : settings.visible }]));
    const restored = readPickerColumns(JSON.stringify(legacy));
    expect(orderedPickerColumns(restored).map(c => c.id)).toEqual(defaultIds);
    expect(restored.title.width).toBe(290);
    expect(restored.price).toMatchObject({ width: 145, visible: false });
  });
  it("moves price before title and preserves every width and visibility", () => {
    let settings = pickerColumnDefaults();
    settings.price.width = 210;
    settings.code.visible = true;
    for (let i = 0; i < 6; i++) settings = movePickerColumn(settings, "price", -1);
    expect(orderedPickerColumns(settings).map(c => c.id)).toEqual(["price", ...defaultIds.filter(id => id !== "price")]);
    expect(settings.price).toEqual({ width: 210, visible: true, order: 0 });
    expect(settings.code.visible).toBe(true);
    expect(readPickerColumns(JSON.stringify({ ...settings, customer: "discard", priceData: 200 }))).toEqual(settings);
  });
  it.each(["duplicate", "missing", "fraction", "foreign"])('rejects %s order without losing widths or visibility', (kind) => {
    const settings = pickerColumnDefaults();
    settings.title.width = 400; settings.price.visible = false;
    const raw = JSON.parse(JSON.stringify(settings));
    if (kind === "duplicate") raw.price.order = 0;
    if (kind === "missing") delete raw.price.order;
    if (kind === "fraction") raw.price.order = 2.5;
    if (kind === "foreign") raw.price.order = 8;
    expect(readPickerColumns(JSON.stringify(raw))).toEqual(settings);
  });
  it("does not wrap the first or last column at order boundaries", () => {
    const settings = pickerColumnDefaults();
    expect(movePickerColumn(settings, "title", -1)).toBe(settings);
    expect(movePickerColumn(settings, "quantity", 1)).toBe(settings);
  });
});
