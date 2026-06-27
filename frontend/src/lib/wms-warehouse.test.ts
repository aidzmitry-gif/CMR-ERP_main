import { describe, expect, it } from "vitest";

import {
  dueState,
  receiptStatusLabel,
  severityLabel,
  taskKindLabel,
  taskStatusLabel,
} from "@/lib/wms-warehouse";

describe("severityLabel", () => {
  it("переводит severity", () => {
    expect(severityLabel("out_of_stock")).toBe("Нет в наличии");
    expect(severityLabel("below_min")).toBe("Ниже минимума");
  });
});

describe("task labels", () => {
  it("kind/status", () => {
    expect(taskKindLabel("putaway")).toBe("Размещение");
    expect(taskKindLabel("pick")).toBe("Подбор");
    expect(taskStatusLabel("in_progress")).toBe("В работе");
    expect(taskStatusLabel("done")).toBe("Выполнена");
  });
});

describe("receiptStatusLabel", () => {
  it("статусы приёмки", () => {
    expect(receiptStatusLabel("pending_qc")).toBe("Ожидает QC");
    expect(receiptStatusLabel("accepted")).toBe("Принято");
  });
});

describe("dueState", () => {
  const today = "2026-06-28";
  it("просрочено / сегодня / предстоит / нет", () => {
    expect(dueState("2026-06-01", today)).toBe("overdue");
    expect(dueState(today, today)).toBe("today");
    expect(dueState("2026-07-10", today)).toBe("upcoming");
    expect(dueState(null, today)).toBe("none");
  });
});
