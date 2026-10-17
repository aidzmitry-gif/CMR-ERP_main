import { describe, expect, it } from "vitest";

import {
  canRequestCarrier,
  classifyTracking,
  isOfficeCarrierList,
  isOfficeDocList,
  officeDocToDelivery,
  officeStageToTracking,
  parseWeightKg,
  summarizeDeliveries,
  trackingLabel,
  type Delivery,
} from "@/lib/office-delivery";

describe("office-delivery · parseWeightKg", () => {
  it("парсит чистое число как кг", () => {
    expect(parseWeightKg("350")).toBe(350);
    expect(parseWeightKg(450)).toBe(450);
  });

  it("парсит явные килограммы и пробел-разделитель тысяч", () => {
    expect(parseWeightKg("350 кг")).toBe(350);
    expect(parseWeightKg("1 200 кг")).toBe(1200);
    expect(parseWeightKg("1 200 kg")).toBe(1200);
  });

  it("переводит тонны в килограммы", () => {
    expect(parseWeightKg("1,2 т")).toBe(1200);
    expect(parseWeightKg("0.5 т")).toBe(500);
    expect(parseWeightKg("2т")).toBe(2000);
    expect(parseWeightKg("1.5 t")).toBe(1500);
  });

  it("не трактует пустой, отрицательный или неразбираемый вес как ноль", () => {
    expect(parseWeightKg("")).toBeNull();
    expect(parseWeightKg("—")).toBeNull();
    expect(parseWeightKg("нет данных")).toBeNull();
    expect(parseWeightKg(-5)).toBeNull();
  });

  it("UNSUPPORTED-WEIGHT-UNIT: не разбирает неизвестные единицы и числа внутри произвольного текста", () => {
    expect(parseWeightKg("500 г")).toBeNull();
    expect(parseWeightKg("примерно 500 кг")).toBeNull();
    expect(parseWeightKg("500 kg по накладной")).toBeNull();
  });
});

describe("office-delivery · покрытие веса", () => {
  it("оставляет неизвестный вес неизвестным", () => {
    const delivery: Delivery = { id: 1, code: "Д-1", company: "X", weight: "—", amount: 0, stage: "unknown" };
    expect(parseWeightKg(delivery.weight)).toBeNull();
  });

  it("считает покрытие веса только по распознанным положительным значениям", () => {
    const summary = summarizeDeliveries([
      { id: 1, code: "1", company: "A", weight: "500 кг", amount: 0, stage: "unknown" },
      { id: 2, code: "2", company: "B", weight: "", amount: 0, stage: "unknown" },
      { id: 3, code: "3", company: "C", weight: "0", amount: 0, stage: "unknown" },
    ]);
    expect(summary.weightKnown).toBe(1);
    expect(summary.total).toBe(3);
  });

  it("не использует вес как неподтверждённое правило выбора способа доставки", () => {
    expect(parseWeightKg("299 кг")).toBe(299);
    expect(parseWeightKg("300 кг")).toBe(300);
    expect(parseWeightKg("нет данных")).toBeNull();
  });
});

describe("office-delivery · classifyTracking", () => {
  it("известная стадия отображается с подписью и тоном", () => {
    expect(classifyTracking("in_transit").label).toBe("В пути");
    expect(classifyTracking("delivered").tone).toBe("green");
    expect(classifyTracking("delayed").tone).toBe("red");
  });

  it("trackingLabel даёт подпись подтверждённой стадии", () => {
    expect(trackingLabel("new")).toBe("Создана");
    expect(trackingLabel("delivered")).toBe("Доставлена");
  });

  it("неизвестная стадия имеет отдельную нейтральную подпись", () => {
    // @ts-expect-error — намеренно невалидная стадия
    expect(classifyTracking("zzz").label).toBe("Не подтверждён");
    expect(classifyTracking("unknown").label).toBe("Не подтверждён");
  });
});

describe("office-delivery · summarizeDeliveries", () => {
  const sample: Delivery[] = [
    { id: 1, code: "0156", company: "A", weight: "1 200 кг", amount: 100, stage: "in_transit" },
    { id: 2, code: "0157", company: "B", weight: "50 кг", amount: 200, stage: "delivered", carrier: "СДЭК" },
    { id: 3, code: "0158", company: "C", weight: "400 кг", amount: 300, stage: "delayed" },
    { id: 4, code: "0159", company: "D", weight: "900 кг", amount: 50, stage: "unknown" },
  ];

  it("считает документы, подтверждённые стадии, покрытие и суммы", () => {
    const summary = summarizeDeliveries(sample);
    expect(summary.total).toBe(4);
    expect(summary.inTransit).toBe(1);
    expect(summary.delivered).toBe(1);
    expect(summary.delayed).toBe(1);
    expect(summary.trackingKnown).toBe(3);
    expect(summary.weightKnown).toBe(4);
    expect(summary.totalAmount).toBe(650);
  });

  it("не включает неизвестное в счётчики подтверждённой доставки", () => {
    const summary = summarizeDeliveries([{ ...sample[0], stage: "unknown", weight: "" }]);
    expect(summary.inTransit).toBe(0);
    expect(summary.delivered).toBe(0);
    expect(summary.trackingKnown).toBe(0);
    expect(summary.weightKnown).toBe(0);
  });

  it("пустой успешный список имеет нулевые счётчики", () => {
    expect(summarizeDeliveries([])).toEqual({
      total: 0,
      inTransit: 0,
      delivered: 0,
      delayed: 0,
      trackingKnown: 0,
      weightKnown: 0,
      totalAmount: 0,
    });
  });
});

describe("office-delivery · officeDocToDelivery", () => {
  it("стадию трекинга определяет только явный текст события доставки", () => {
    expect(officeStageToTracking("shipped", "Доставка: В пути · Минск → Гомель")).toBe("in_transit");
    expect(officeStageToTracking("docs", "Доставлено, закрываем документы")).toBe("delivered");
    expect(officeStageToTracking("ready", "Доставка: задержка маршрута")).toBe("delayed");
    expect(officeStageToTracking("paid", "Оплачено")).toBe("unknown");
    expect(officeStageToTracking("await_pay", "Ожидает оплаты")).toBe("unknown");
    expect(officeStageToTracking("docs", "Документы собраны")).toBe("unknown");
    expect(officeStageToTracking("shipped", "Отгружено, готовим документы")).toBe("unknown");
  });

  it("NEGATIVE-DELIVERY-TEXT: отрицание и встроенный статус не становятся доставкой", () => {
    expect(officeStageToTracking("docs", "Доставка: не доставлено")).toBe("unknown");
    expect(officeStageToTracking("docs", "Сведения: Доставлено, закрываем документы")).toBe("unknown");
  });

  it("маппит документ, не превращая op_date в ETA или tracking-факт", () => {
    const delivery = officeDocToDelivery({
      id: 7,
      number: "ДОК-2026-0007",
      company: "ООО Альфа",
      amount: 5000,
      delivery: "СДЭК",
      docs_status: "Доставка: В пути",
      stage: "shipped",
      region: "Гомель",
      weight: "420",
    });
    expect(delivery).toEqual({
      id: 7,
      code: "ДОК-2026-0007",
      company: "ООО Альфа",
      weight: "420",
      amount: 5000,
      stage: "in_transit",
      carrier: "СДЭК",
      destination: "Гомель",
      officeStage: "shipped",
    });
  });

  it("пустые вес, перевозчик и направление остаются неизвестными", () => {
    const delivery = officeDocToDelivery({
      id: 1,
      number: "Д-1",
      company: "X",
      amount: 0,
      delivery: "",
      docs_status: "",
      stage: "ready",
      region: "",
      weight: "",
    });
    expect(delivery.carrier).toBeUndefined();
    expect(delivery.destination).toBeUndefined();
    expect(delivery.weight).toBe("");
    expect(delivery.stage).toBe("unknown");
    expect(delivery.officeStage).toBe("ready");
  });
});

describe("office-delivery · list response guards", () => {
  it("считает пустой массив корректным ответом списка документов", () => {
    expect(isOfficeDocList([])).toBe(true);
    expect(isOfficeDocList([{ id: 1, number: "D-1", company: "X", amount: 0, delivery: "", docs_status: "", stage: "ready" }])).toBe(true);
  });

  it("отвергает объекты и строки с неверными типами вместо пустого списка", () => {
    expect(isOfficeDocList({ docs: [] })).toBe(false);
    expect(isOfficeDocList([{ id: 1, number: "D-1", company: "X", amount: "0", delivery: "", docs_status: "", stage: "ready" }])).toBe(false);
  });
});

describe("office-delivery · canRequestCarrier", () => {
  const base: Delivery = { id: 1, code: "Д-1", company: "X", weight: "500 кг", amount: 0, stage: "unknown" };

  it("показывает заявку только для документа со стадией ready", () => {
    expect(canRequestCarrier({ ...base, officeStage: "ready" })).toBe(true);
    expect(canRequestCarrier({ ...base, officeStage: "shipped" })).toBe(false);
    expect(canRequestCarrier({ ...base, officeStage: "paid" })).toBe(false);
  });

  it("не разрешает заявку без исходной стадии документа", () => {
    expect(canRequestCarrier(base)).toBe(false);
  });
});

describe("office-delivery · prototype carrier names", () => {
  it("принимает только идентификатор и отображаемое имя, игнорируя коммерческие поля", () => {
    expect(isOfficeCarrierList([{ id: "sample", name: "Перевозчик", rating: 5, price_from: 0, heavy: true }])).toBe(true);
  });
});
