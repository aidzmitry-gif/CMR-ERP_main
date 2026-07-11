import { describe, expect, it } from "vitest";

import {
  assemble,
  calcActivity,
  mergeSaved,
  metricsFromPlan,
  nextMonthKey,
  regularCycleCaption,
  regularWhenLabel,
  reverseCount,
  toDrafts,
  verdictOf,
  type CommittedRow,
  type PlanItemOut,
  type PlanSources,
  type RegularRow,
} from "./plan-constructor";

const COMMITTED: CommittedRow = {
  ref: "CRM-1029",
  title: "АКБ 6СТ-190 (перезаказ Белтранс)",
  when_label: "придёт 05.07",
  revenue: 52000,
  gross: 19200,
  probability: 90,
};

const REGULAR_IN_MONTH: RegularRow = {
  counterparty: "ТЧУП «Энергомир»",
  orders_count: 6,
  cycle_days: 100,
  last_order: "2026-04-09",
  expected: "2026-07-18",
  in_month: true,
  avg_check: 31600,
  probability: 80,
  gross: 12200,
};

const REGULAR_OUT_OF_MONTH: RegularRow = {
  counterparty: "ОДО «ВодоканалСервис»",
  orders_count: 1,
  cycle_days: null,
  last_order: "2026-06-02",
  expected: null,
  in_month: false,
  avg_check: 27300,
  probability: 60,
  gross: 9000,
};

const SOURCES: PlanSources = {
  month: "2026-08",
  owner: "Иванов И.",
  base_gross: 75000,
  committed: [COMMITTED],
  regulars: [REGULAR_IN_MONTH, REGULAR_OUT_OF_MONTH],
  defaults: { avg_check: 16000, margin_pct: 34 },
  saved_items: [],
};

describe("calcActivity", () => {
  it("считает сделки/выручку/прибыль по заявкам и звонкам", () => {
    const r = calcActivity({
      leads: 30,
      leadConvPct: 12,
      calls: 150,
      callConvPct: 1.5,
      avgCheck: 16000,
      marginPct: 34,
    });
    // 30*0.12 + 150*0.015 = 3.6 + 2.25 = 5.85 сделок
    expect(r.deals).toBeCloseTo(5.85);
    expect(r.revenue).toBeCloseTo(5.85 * 16000);
    expect(r.gross).toBeCloseTo(r.revenue * 0.34);
  });

  it("нулевые входы дают нулевой результат, без NaN/Infinity", () => {
    const r = calcActivity({ leads: 0, leadConvPct: 0, calls: 0, callConvPct: 0, avgCheck: 0, marginPct: 0 });
    expect(r).toEqual({ deals: 0, revenue: 0, gross: 0 });
  });
});

describe("reverseCount", () => {
  it("дефицит + нормальная конверсия → нужные сделки/заявки/звонки", () => {
    const r = reverseCount(10000, { leadConvPct: 12, callConvPct: 1.5, avgCheck: 16000, marginPct: 34 });
    expect(r).not.toBeNull();
    // perDealGross = 16000*0.34 = 5440; needDeals = ceil(10000/5440) = 2
    expect(r!.needDeals).toBe(2);
    expect(r!.needLeads).toBe(Math.ceil(2 / 0.12));
    expect(r!.needCalls).toBe(Math.ceil(2 / 0.015));
  });

  it("нулевая конверсия заявок → needLeads null, needCalls посчитан", () => {
    const r = reverseCount(10000, { leadConvPct: 0, callConvPct: 1.5, avgCheck: 16000, marginPct: 34 });
    expect(r).not.toBeNull();
    expect(r!.needLeads).toBeNull();
    expect(r!.needCalls).not.toBeNull();
  });

  it("нулевой чек/маржа → вся защита от деления на ноль (null, не Infinity/NaN)", () => {
    expect(reverseCount(10000, { leadConvPct: 12, callConvPct: 1.5, avgCheck: 0, marginPct: 34 })).toBeNull();
    expect(reverseCount(10000, { leadConvPct: 12, callConvPct: 1.5, avgCheck: 16000, marginPct: 0 })).toBeNull();
  });

  it("нет дефицита (0 или отрицательный) → null", () => {
    expect(reverseCount(0, { leadConvPct: 12, callConvPct: 1.5, avgCheck: 16000, marginPct: 34 })).toBeNull();
    expect(reverseCount(-500, { leadConvPct: 12, callConvPct: 1.5, avgCheck: 16000, marginPct: 34 })).toBeNull();
  });
});

describe("verdictOf", () => {
  it("база не задана → null", () => {
    expect(verdictOf(null, 50000)).toBeNull();
  });

  it("дефицит → ok=false, diff отрицательный", () => {
    const v = verdictOf(75000, 50000);
    expect(v).toEqual({ ok: false, diff: -25000 });
  });

  it("план набран → ok=true, diff >= 0", () => {
    const v = verdictOf(75000, 80000);
    expect(v).toEqual({ ok: true, diff: 5000 });
  });
});

describe("toDrafts", () => {
  it("committed всегда enabled=true; regular in_month=true → enabled=true, false → enabled=false", () => {
    const drafts = toDrafts(SOURCES);
    const committed = drafts.find((d) => d.source === "committed" && d.ref === COMMITTED.ref);
    const regularIn = drafts.find((d) => d.source === "regular" && d.ref === REGULAR_IN_MONTH.counterparty);
    const regularOut = drafts.find((d) => d.source === "regular" && d.ref === REGULAR_OUT_OF_MONTH.counterparty);
    expect(committed?.enabled).toBe(true);
    expect(regularIn?.enabled).toBe(true);
    expect(regularOut?.enabled).toBe(false);
  });

  it("gross: null из источника → 0 в драфте", () => {
    const sources: PlanSources = {
      ...SOURCES,
      committed: [{ ...COMMITTED, gross: null }],
      regulars: [],
    };
    const drafts = toDrafts(sources);
    expect(drafts[0].gross).toBe(0);
  });
});

describe("regularWhenLabel / regularCycleCaption", () => {
  it("с ожидаемой датой — «ожид. ДД.ММ»", () => {
    expect(regularWhenLabel(REGULAR_IN_MONTH)).toBe("ожид. 18.07");
  });

  it("без цикла — «1 заказ — цикла ещё нет»", () => {
    expect(regularCycleCaption(REGULAR_OUT_OF_MONTH)).toBe("1 заказ — цикла ещё нет");
  });

  it("с циклом — «цикл ~N дн · посл. ДД.ММ»", () => {
    expect(regularCycleCaption(REGULAR_IN_MONTH)).toBe("цикл ~100 дн · посл. 09.04");
  });
});

describe("assemble", () => {
  it("суммирует enabled-строки по источнику; s3 — активность отдельно", () => {
    const drafts = toDrafts(SOURCES);
    const r = assemble(drafts, 1000);
    expect(r.s1).toBe(19200); // committed
    expect(r.s2).toBe(12200); // только in_month regular
    expect(r.s3).toBe(1000);
    expect(r.total).toBe(19200 + 12200 + 1000);
  });

  it("выключенная строка не считается", () => {
    const drafts = toDrafts(SOURCES).map((d) => ({ ...d, enabled: false }));
    const r = assemble(drafts, 0);
    expect(r.total).toBe(0);
  });
});

describe("metricsFromPlan", () => {
  it("возвращает 5 метрик с округлением сделок", () => {
    const activity = { leads: 30, leadConvPct: 12, calls: 150, callConvPct: 1.5, avgCheck: 16000, marginPct: 34, deals: 5.85, revenue: 93600, gross: 31824 };
    const metrics = metricsFromPlan({ totalGross: 75000, activity });
    expect(metrics).toEqual([
      { metric: "gross_profit", target: 75000 },
      { metric: "new_deals_count", target: 6 },
      { metric: "cold_calls", target: 150 },
      { metric: "leads", target: 30 },
      { metric: "new_deals_amount", target: 93600 },
    ]);
  });
});

describe("mergeSaved", () => {
  it("накладывает enabled/gross сохранённой строки поверх свежего драфта по (source, ref)", () => {
    const drafts = toDrafts(SOURCES);
    const saved: PlanItemOut[] = [
      {
        id: 1,
        owner_id: 7,
        period_key: "2026-08",
        source: "committed",
        ref: COMMITTED.ref,
        title: COMMITTED.title,
        when_label: COMMITTED.when_label,
        revenue: COMMITTED.revenue,
        gross: 5000, // продавец руками занизил
        probability: COMMITTED.probability,
        enabled: false, // и выключил строку
      },
    ];
    const merged = mergeSaved(drafts, saved);
    const committed = merged.find((d) => d.source === "committed" && d.ref === COMMITTED.ref);
    expect(committed?.enabled).toBe(false);
    expect(committed?.gross).toBe(5000);
    // строка без сохранённого аналога остаётся как есть (suggested)
    const regularIn = merged.find((d) => d.source === "regular" && d.ref === REGULAR_IN_MONTH.counterparty);
    expect(regularIn?.gross).toBe(12200);
  });

  it("сохранённая строка без соответствия в текущих драфтах игнорируется", () => {
    const drafts = toDrafts(SOURCES);
    const saved: PlanItemOut[] = [
      {
        id: 2,
        owner_id: 7,
        period_key: "2026-08",
        source: "regular",
        ref: "Клиент, которого больше нет в базе",
        title: "—",
        when_label: "—",
        revenue: 0,
        gross: 999,
        probability: 0,
        enabled: true,
      },
    ];
    const merged = mergeSaved(drafts, saved);
    expect(merged).toHaveLength(drafts.length);
  });
});

describe("nextMonthKey", () => {
  it("следующий месяц в пределах года", () => {
    expect(nextMonthKey(new Date(2026, 6, 12))).toBe("2026-08"); // июль → август
  });

  it("переход через год", () => {
    expect(nextMonthKey(new Date(2026, 11, 20))).toBe("2027-01"); // декабрь → январь
  });
});
