import { describe, expect, it } from "vitest";

import {
  CARRIER_THRESHOLD_KG,
  classifyTracking,
  DEMO_DELIVERIES,
  parseWeightKg,
  requiresCarrierRequest,
  summarizeDeliveries,
  trackingLabel,
  type Delivery,
} from "@/lib/office-delivery";

describe("office-delivery · parseWeightKg", () => {
  it("парсит чистое число (кг по умолчанию)", () => {
    expect(parseWeightKg("350")).toBe(350);
    expect(parseWeightKg(450)).toBe(450);
  });

  it("парсит явные килограммы и пробел-разделитель тысяч", () => {
    expect(parseWeightKg("350 кг")).toBe(350);
    expect(parseWeightKg("1 200 кг")).toBe(1200);
    expect(parseWeightKg("1 200 kg")).toBe(1200); // неразрывный пробел
  });

  it("переводит тонны в килограммы (запятая = десятичный разделитель)", () => {
    expect(parseWeightKg("1,2 т")).toBe(1200);
    expect(parseWeightKg("0.5 т")).toBe(500);
    expect(parseWeightKg("2т")).toBe(2000);
    expect(parseWeightKg("1.5 t")).toBe(1500);
  });

  it("непарсируемое / пустое / мусор → 0", () => {
    expect(parseWeightKg("")).toBe(0);
    expect(parseWeightKg("—")).toBe(0);
    expect(parseWeightKg("нет данных")).toBe(0);
    expect(parseWeightKg(-5)).toBe(0);
  });
});

describe("office-delivery · requiresCarrierRequest (гард ≥300 кг)", () => {
  it("порог зафиксирован на 300 кг", () => {
    expect(CARRIER_THRESHOLD_KG).toBe(300);
  });

  it("ровно порог и выше → заявка нужна", () => {
    expect(requiresCarrierRequest("300")).toBe(true);
    expect(requiresCarrierRequest("300 кг")).toBe(true);
    expect(requiresCarrierRequest("1,2 т")).toBe(true);
    expect(requiresCarrierRequest(500)).toBe(true);
  });

  it("ниже порога → заявка не нужна (курьер/самовывоз)", () => {
    expect(requiresCarrierRequest("299")).toBe(false);
    expect(requiresCarrierRequest("50 кг")).toBe(false);
    expect(requiresCarrierRequest("")).toBe(false);
  });
});

describe("office-delivery · classifyTracking", () => {
  it("известная стадия → подпись + тон", () => {
    expect(classifyTracking("in_transit").label).toBe("В пути");
    expect(classifyTracking("delivered").tone).toBe("green");
    expect(classifyTracking("delayed").tone).toBe("red");
  });

  it("trackingLabel — короткий доступ к подписи", () => {
    expect(trackingLabel("new")).toBe("Создана");
    expect(trackingLabel("delivered")).toBe("Доставлена");
  });

  it("неизвестная стадия не роняет приложение (фолбэк на «Создана»)", () => {
    // @ts-expect-error — намеренно невалидная стадия
    expect(classifyTracking("zzz").label).toBe("Создана");
  });
});

describe("office-delivery · summarizeDeliveries", () => {
  const sample: Delivery[] = [
    { id: 1, code: "0156", company: "A", weight: "1 200 кг", amount: 100, stage: "in_transit" },
    { id: 2, code: "0157", company: "B", weight: "50 кг", amount: 200, stage: "delivered", carrier: "СДЭК" },
    { id: 3, code: "0158", company: "C", weight: "400 кг", amount: 300, stage: "delayed" },
    { id: 4, code: "0159", company: "D", weight: "900 кг", amount: 50, stage: "new", carrier: "ПЭК" },
  ];

  it("считает суммы по стадиям и деньги", () => {
    const s = summarizeDeliveries(sample);
    expect(s.total).toBe(4);
    expect(s.inTransit).toBe(1);
    expect(s.delivered).toBe(1);
    expect(s.delayed).toBe(1);
    expect(s.totalAmount).toBe(650);
  });

  it("needCarrierRequest = тяжёлые (≥300 кг) БЕЗ назначенного перевозчика", () => {
    // id1 (1200кг, нет перевозчика) и id3 (400кг, нет перевозчика); id4 тяжёлый, но перевозчик назначен
    expect(summarizeDeliveries(sample).needCarrierRequest).toBe(2);
  });

  it("пустой список не роняет приложение", () => {
    expect(summarizeDeliveries([])).toEqual({
      total: 0,
      inTransit: 0,
      delivered: 0,
      delayed: 0,
      needCarrierRequest: 0,
      totalAmount: 0,
    });
  });
});

describe("office-delivery · DEMO_DELIVERIES", () => {
  it("есть демо-данные, у каждой есть валидная стадия", () => {
    expect(DEMO_DELIVERIES.length).toBeGreaterThan(0);
    for (const d of DEMO_DELIVERIES) {
      expect(classifyTracking(d.stage).label.length).toBeGreaterThan(0);
    }
  });
});
