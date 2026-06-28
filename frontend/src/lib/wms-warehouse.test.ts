import { describe, expect, it } from "vitest";

import {
  type Alerts,
  alertsEmitMessage,
  canEmitAlerts,
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

describe("alertsEmitMessage", () => {
  it("русский плюрал позиции", () => {
    expect(alertsEmitMessage(1)).toBe("Сигнал отправлен в закупки, 1 позиция");
    expect(alertsEmitMessage(3)).toBe("Сигнал отправлен в закупки, 3 позиции");
    expect(alertsEmitMessage(5)).toBe("Сигнал отправлен в закупки, 5 позиций");
    expect(alertsEmitMessage(11)).toBe("Сигнал отправлен в закупки, 11 позиций");
    expect(alertsEmitMessage(21)).toBe("Сигнал отправлен в закупки, 21 позиция");
  });
});

describe("canEmitAlerts", () => {
  const row = {
    sku_code: "AKB-60", title: "АКБ", warehouse: "Минск",
    free_qty: 3, min_qty: 10, deficit: 7, reorder_qty: 20, severity: "below_min",
  };
  it("кнопка активна только при шлюзе и нарушенных порогах", () => {
    expect(canEmitAlerts({ rows: [row], gateway: true } as Alerts)).toBe(true);
    expect(canEmitAlerts({ rows: [], gateway: true } as Alerts)).toBe(false); // пусто → disabled
    expect(canEmitAlerts({ rows: [row], gateway: false } as Alerts)).toBe(false); // нет 1С
  });
});
