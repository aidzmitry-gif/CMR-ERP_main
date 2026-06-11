import { describe, expect, it } from "vitest";

import {
  canRequestCarrier,
  CARRIER_THRESHOLD_KG,
  classifyTracking,
  DEMO_DELIVERIES,
  eligibleCarriers,
  OFFICE_CARRIERS,
  officeDocToDelivery,
  officeStageToTracking,
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

describe("office-delivery · officeDocToDelivery (маппинг /office/docs)", () => {
  it("стадия трекинга — по тексту статуса доставки, затем по стадии документа", () => {
    expect(officeStageToTracking("shipped", "Доставка: В пути · Минск → Гомель")).toBe("in_transit");
    expect(officeStageToTracking("docs", "Доставлено, закрываем документы")).toBe("delivered");
    expect(officeStageToTracking("ready", "")).toBe("new");
    expect(officeStageToTracking("paid", "")).toBe("delivered");
    expect(officeStageToTracking("zzz", "")).toBe("new"); // неизвестная стадия → не падает
  });

  it("маппит документ API в строку доставки", () => {
    const d = officeDocToDelivery({
      id: 7, number: "ДОК-2026-0007", company: "ООО Альфа", amount: 5000,
      delivery: "СДЭК", docs_status: "Доставка: В пути", stage: "shipped",
      region: "Гомель", weight: "420", op_date: "2026-06-15",
    });
    expect(d).toMatchObject({
      id: 7, code: "ДОК-2026-0007", company: "ООО Альфа", amount: 5000,
      carrier: "СДЭК", stage: "in_transit", destination: "Гомель", weight: "420", eta: "2026-06-15",
    });
  });

  it("пустой перевозчик/регион → undefined (а не пустая строка)", () => {
    const d = officeDocToDelivery({
      id: 1, number: "Д-1", company: "X", amount: 0, delivery: "", docs_status: "",
      stage: "ready", region: "", weight: "", op_date: null,
    });
    expect(d.carrier).toBeUndefined();
    expect(d.destination).toBeUndefined();
    expect(d.stage).toBe("new");
    expect(d.officeStage).toBe("ready");   // сырая стадия сохранена для гарда заявки
  });
});

describe("office-delivery · eligibleCarriers (гард heavy)", () => {
  it("тяжёлый груз (≥300 кг) → только перевозчики с heavy", () => {
    const eligible = eligibleCarriers(OFFICE_CARRIERS, "1 200 кг");
    expect(eligible.length).toBeGreaterThan(0);
    expect(eligible.every((c) => c.heavy)).toBe(true);
    expect(eligible.map((c) => c.id)).toContain("dellin");
    expect(eligible.map((c) => c.id)).not.toContain("cdek"); // не heavy
  });

  it("лёгкий груз (<300 кг) → любой перевозчик", () => {
    expect(eligibleCarriers(OFFICE_CARRIERS, "50 кг")).toHaveLength(OFFICE_CARRIERS.length);
  });
});

describe("office-delivery · canRequestCarrier (стадия ready)", () => {
  const base: Delivery = { id: 1, code: "Д-1", company: "X", weight: "500 кг", amount: 0, stage: "new" };

  it("живой документ: заявка только на стадии ready", () => {
    expect(canRequestCarrier({ ...base, officeStage: "ready" })).toBe(true);
    expect(canRequestCarrier({ ...base, officeStage: "shipped" })).toBe(false);
    expect(canRequestCarrier({ ...base, officeStage: "paid" })).toBe(false);
  });

  it("демо-данные (без officeStage) → разрешено", () => {
    expect(canRequestCarrier(base)).toBe(true);
  });
});
