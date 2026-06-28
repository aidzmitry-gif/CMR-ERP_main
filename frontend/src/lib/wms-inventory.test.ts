import { describe, expect, it } from "vitest";

import { inventoryStatusLabel, varianceTone } from "@/lib/wms-inventory";

describe("inventoryStatusLabel", () => {
  it("переводит статусы документа", () => {
    expect(inventoryStatusLabel("open")).toBe("Идёт пересчёт");
    expect(inventoryStatusLabel("done")).toBe("Проведена");
    expect(inventoryStatusLabel("canceled")).toBe("Отменена");
  });
});

describe("varianceTone", () => {
  it("нет факта → none", () => {
    expect(varianceTone(null)).toBe("none");
  });
  it("совпало → ok", () => {
    expect(varianceTone(0)).toBe("ok");
  });
  it("недостача → short, излишек → over", () => {
    expect(varianceTone(-3)).toBe("short");
    expect(varianceTone(2)).toBe("over");
  });
});
