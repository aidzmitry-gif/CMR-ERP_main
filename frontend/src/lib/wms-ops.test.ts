import { describe, expect, it } from "vitest";

import { locationLabel, reasonLabel } from "@/lib/wms-ops";

describe("reasonLabel", () => {
  it("переводит причины движения", () => {
    expect(reasonLabel("receipt")).toBe("Приёмка");
    expect(reasonLabel("shipment")).toBe("Отгрузка");
    expect(reasonLabel("transfer")).toBe("Перемещение");
    expect(reasonLabel("adjustment")).toBe("Коррекция");
    expect(reasonLabel("release")).toBe("Снятие резерва");
  });
  it("пустая строка возвращает «—»", () => {
    expect(reasonLabel("")).toBe("—");
  });
  it("неизвестная причина возвращается как есть", () => {
    expect(reasonLabel("weird")).toBe("weird");
  });
});

describe("locationLabel", () => {
  it("зона + код", () => {
    expect(locationLabel({ zone: "A", code: "A-01" })).toBe("A · A-01");
  });
  it("только код", () => {
    expect(locationLabel({ zone: "", code: "A-01" })).toBe("A-01");
  });
  it("нет кода → тире", () => {
    expect(locationLabel({ zone: "A", code: "" })).toBe("—");
  });
});
