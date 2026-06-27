import { describe, expect, it } from "vitest";

import {
  allowedDeliveryTransitions,
  auditSummary,
  auditVariance,
  bestBid,
  bidRisk,
  bidSavings,
  canTransitionDelivery,
  computeScorecardScore,
  deliveryStatusLabel,
  nextRfqStatus,
  quoteTariff,
  rankBids,
  rfqStatusLabel,
  scoreGrade,
  summarizeShipments,
  tariffWeightPrice,
  vehicleFits,
  type AuditItem,
  type Bid,
  type ShipmentLike,
  type TariffRates,
} from "@/lib/logistics-domain";

const RATES: TariffRates = {
  price_w5: 100,
  price_w10: 150,
  price_w30: 300,
  over30_per_kg: 10,
  pickup_fee: 20,
  cod_pct: 2,
  insurance_pct: 1,
};

function bid(over: Partial<Bid>): Bid {
  return { carrier_code: "x", carrier: "X", price: 0, eta_days: 5, ...over };
}

describe("logistics-domain · tariffWeightPrice", () => {
  it("выбирает тариф по весовой вилке (≤5/≤10/≤30)", () => {
    expect(tariffWeightPrice(RATES, 3)).toBe(100);
    expect(tariffWeightPrice(RATES, 5)).toBe(100);
    expect(tariffWeightPrice(RATES, 8)).toBe(150);
    expect(tariffWeightPrice(RATES, 10)).toBe(150);
    expect(tariffWeightPrice(RATES, 25)).toBe(300);
    expect(tariffWeightPrice(RATES, 30)).toBe(300);
  });

  it("свыше 30 кг — база w30 + (вес−30)·over30_per_kg", () => {
    expect(tariffWeightPrice(RATES, 40)).toBe(300 + 10 * 10);
    expect(tariffWeightPrice(RATES, 35.5)).toBe(300 + 5.5 * 10);
  });

  it("нулевой/отрицательный вес → 0", () => {
    expect(tariffWeightPrice(RATES, 0)).toBe(0);
    expect(tariffWeightPrice(RATES, -4)).toBe(0);
  });
});

describe("logistics-domain · quoteTariff", () => {
  it("базовая котировка = вес-цена + забор груза", () => {
    expect(quoteTariff(RATES, 8)).toBe(170); // 150 + 20
  });

  it("страховка = declaredValue · insurance_pct%", () => {
    expect(quoteTariff(RATES, 8, { declaredValue: 1000 })).toBe(180); // 170 + 10
  });

  it("наложенный платёж = фрахт · cod_pct%", () => {
    // фрахт 170 → cod 2% = 3.4 → итог 173.4
    expect(quoteTariff(RATES, 8, { cod: true })).toBe(173.4);
  });

  it("складывает страховку и COD, округляет до 2 знаков", () => {
    expect(quoteTariff(RATES, 8, { declaredValue: 1000, cod: true })).toBe(183.4);
  });
});

describe("logistics-domain · ставки тендера", () => {
  const bids: Bid[] = [
    bid({ carrier_code: "a", price: 900, eta_days: 6 }),
    bid({ carrier_code: "b", price: 700, eta_days: 7 }),
    bid({ carrier_code: "c", price: 700, eta_days: 5 }),
    bid({ carrier_code: "d", price: 1200, eta_days: 4 }),
  ];

  it("bestBid: минимальная цена, при равенстве — меньший срок", () => {
    expect(bestBid(bids)?.carrier_code).toBe("c");
    expect(bestBid([])).toBeNull();
  });

  it("rankBids: сортировка по цене, затем по сроку (копия, без мутации)", () => {
    const ranked = rankBids(bids);
    expect(ranked.map((b) => b.carrier_code)).toEqual(["c", "b", "a", "d"]);
    expect(bids[0].carrier_code).toBe("a"); // исходный массив не тронут
  });

  it("bidSavings: разрыв между худшей и лучшей ценой", () => {
    expect(bidSavings(bids)).toBe(500); // 1200 − 700
    expect(bidSavings([bid({ price: 500 })])).toBe(0);
    expect(bidSavings([])).toBe(0);
  });

  it("bidRisk: ≥25% ниже медианы при ≥3 ставках → флаг демпинга", () => {
    const all: Bid[] = [70, 95, 100, 105, 120].map((p, i) =>
      bid({ carrier_code: String(i), price: p }),
    );
    const r = bidRisk(all[0], all);
    expect(r.median).toBe(100);
    expect(r.deviationPct).toBe(30);
    expect(r.isSuspiciouslyCheap).toBe(true);
  });

  it("bidRisk: 2 ставки — мало для флага даже при сильном отклонении", () => {
    const all: Bid[] = [bid({ price: 50 }), bid({ price: 100 })];
    expect(bidRisk(all[0], all).isSuspiciouslyCheap).toBe(false);
  });

  it("bidRisk: близко к медиане → не демпинг", () => {
    const all: Bid[] = [90, 95, 105, 110].map((p) => bid({ price: p }));
    const r = bidRisk(all[0], all);
    expect(r.deviationPct).toBe(10);
    expect(r.isSuspiciouslyCheap).toBe(false);
  });

  it("bidRisk: одна ставка — нет медианы, нет сигналов", () => {
    const one = bid({ price: 100 });
    expect(bidRisk(one, [one]).isSuspiciouslyCheap).toBe(false);
  });
});

describe("logistics-domain · scorecard", () => {
  it("computeScorecardScore: взвешенная сумма метрик (claims инвертируется)", () => {
    const perfect = computeScorecardScore({
      otd_pct: 100,
      otif_pct: 100,
      damage_free_pct: 100,
      billing_accuracy_pct: 100,
      claims_ratio_pct: 0,
    });
    expect(perfect).toBe(100);
  });

  it("computeScorecardScore: учитывает веса", () => {
    const s = computeScorecardScore({
      otd_pct: 80,
      otif_pct: 80,
      damage_free_pct: 80,
      billing_accuracy_pct: 80,
      claims_ratio_pct: 20, // инверт → 80
    });
    expect(s).toBe(80);
  });

  it("scoreGrade: ≥90→A, ≥75→B, иначе C", () => {
    expect(scoreGrade(95)).toBe("A");
    expect(scoreGrade(90)).toBe("A");
    expect(scoreGrade(80)).toBe("B");
    expect(scoreGrade(75)).toBe("B");
    expect(scoreGrade(60)).toBe("C");
  });
});

describe("logistics-domain · аудит счетов", () => {
  it("auditVariance = счёт − ожидаемое (округление до 2)", () => {
    expect(auditVariance(1200, 1000)).toBe(200);
    expect(auditVariance(1000, 1000)).toBe(0);
    expect(auditVariance(999.999, 1000)).toBe(0); // −0.001 → −0 → 0
  });

  it("auditSummary: проверено/расхождения/к возврату (только переплаты)", () => {
    const items: AuditItem[] = [
      { invoice_amount: 1200, expected_amount: 1000 }, // +200 переплата
      { invoice_amount: 1000, expected_amount: 1000 }, // ок
      { invoice_amount: 800, expected_amount: 900 }, // −100 недоплата (не возвращаем)
    ];
    const s = auditSummary(items);
    expect(s.checked).toBe(3);
    expect(s.discrepancies).toBe(2);
    expect(s.toRecover).toBe(200);
  });
});

describe("logistics-domain · сводка доставок", () => {
  it("summarizeShipments: группировка по статусу/трекингу", () => {
    const items: ShipmentLike[] = [
      { status: "delivered" },
      { status: "shipped", tracking_status: "in_transit" },
      { status: "shipped", tracking_status: "at_customs" },
      { status: "planned" },
    ];
    const s = summarizeShipments(items);
    expect(s.total).toBe(4);
    expect(s.delivered).toBe(1);
    expect(s.atCustoms).toBe(1);
    expect(s.inTransit).toBe(1);
  });
});

describe("logistics-domain · допуск транспорта (парк)", () => {
  it("vehicleFits: вес ≤ грузоподъёмности и температурный режим", () => {
    const v = { capacity_kg: 1000, temp_control: false };
    expect(vehicleFits(v, { weight_kg: 800 })).toBe(true);
    expect(vehicleFits(v, { weight_kg: 1200 })).toBe(false);
    expect(vehicleFits(v, { weight_kg: 500, needs_temp: true })).toBe(false);
    expect(vehicleFits({ capacity_kg: 1000, temp_control: true }, { weight_kg: 500, needs_temp: true })).toBe(true);
  });
});

describe("logistics-domain · статусы тендера", () => {
  it("nextRfqStatus: продвижение по цепочке, финал стоит на месте", () => {
    expect(nextRfqStatus("draft")).toBe("sent");
    expect(nextRfqStatus("collecting")).toBe("negotiation");
    expect(nextRfqStatus("awarded")).toBe("contracted");
    expect(nextRfqStatus("contracted")).toBe("contracted");
    expect(nextRfqStatus("unknown")).toBe("unknown");
  });

  it("rfqStatusLabel: русские подписи", () => {
    expect(rfqStatusLabel("collecting")).toBe("Сбор ставок");
    expect(rfqStatusLabel("awarded")).toBe("Победитель выбран");
    expect(rfqStatusLabel("weird")).toBe("weird");
  });
});

describe("logistics-domain · статусы доставки", () => {
  it("canTransitionDelivery: разрешённые переходы", () => {
    expect(canTransitionDelivery("planned", "assigned")).toBe(true);
    expect(canTransitionDelivery("assigned", "in_transit")).toBe(true);
    expect(canTransitionDelivery("in_transit", "at_customs")).toBe(true);
    expect(canTransitionDelivery("at_customs", "delivered")).toBe(true);
    expect(canTransitionDelivery("in_transit", "delivered")).toBe(true);   // прямой
    expect(canTransitionDelivery("at_customs", "in_transit")).toBe(true);  // возврат с таможни
  });

  it("canTransitionDelivery: запрет регресса и из конечного состояния", () => {
    expect(canTransitionDelivery("delivered", "in_transit")).toBe(false);
    expect(canTransitionDelivery("delivered", "delivered")).toBe(false);
    expect(canTransitionDelivery("in_transit", "planned")).toBe(false);
    expect(canTransitionDelivery("planned", "delivered")).toBe(false);     // через assigned
    expect(canTransitionDelivery("unknown", "delivered")).toBe(false);
  });

  it("allowedDeliveryTransitions: список разрешённых следующих", () => {
    expect(allowedDeliveryTransitions("planned")).toEqual(["assigned"]);
    expect(allowedDeliveryTransitions("in_transit")).toEqual(["at_customs", "delivered"]);
    expect(allowedDeliveryTransitions("delivered")).toEqual([]);
    expect(allowedDeliveryTransitions("unknown")).toEqual([]);
  });

  it("deliveryStatusLabel: русские подписи", () => {
    expect(deliveryStatusLabel("in_transit")).toBe("В пути");
    expect(deliveryStatusLabel("delivered")).toBe("Доставлено");
    expect(deliveryStatusLabel("alien")).toBe("alien");
  });
});
