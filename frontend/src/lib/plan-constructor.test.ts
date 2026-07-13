import { describe, expect, it } from "vitest";

import {
  assemble,
  calcActivity,
  concentration,
  confidenceBand,
  funnelCoverage,
  mergeSaved,
  metricsFromPlan,
  monthPace,
  nextMonthKey,
  paceStatus,
  regularCycleCaption,
  regularWhenLabel,
  reverseCount,
  toDrafts,
  verdictOf,
  weightedForecast,
  type CommittedRow,
  type PlanItemDraft,
  type PlanItemOut,
  type PlanSources,
  type RegularRow,
} from "./plan-constructor";

/** Мини-фабрика драфт-строки для тестов методов прогноза. */
function draft(over: Partial<PlanItemDraft>): PlanItemDraft {
  return {
    source: "committed",
    ref: "x",
    title: "Сделка",
    when_label: "—",
    revenue: 0,
    gross: 0,
    probability: 100,
    enabled: true,
    ...over,
  };
}

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

describe("weightedForecast", () => {
  it("приход ×0.9, постоянные ×вер-ть, новые как есть", () => {
    const drafts = [
      draft({ source: "committed", gross: 10000, probability: 100 }),
      draft({ source: "regular", gross: 10000, probability: 70 }),
    ];
    // 10000×0.9 + 10000×0.7 + 5000 = 9000 + 7000 + 5000
    expect(weightedForecast(drafts, 5000)).toBe(21000);
  });

  it("выключенные строки не считаются", () => {
    const drafts = [draft({ source: "committed", gross: 10000, enabled: false })];
    expect(weightedForecast(drafts, 0)).toBe(0);
  });

  it("взвешенный не выше потолка при вер-ти <100%", () => {
    const drafts = [
      draft({ source: "committed", gross: 20000 }),
      draft({ source: "regular", gross: 20000, probability: 50 }),
    ];
    const total = assemble(drafts, 3000).total;
    expect(weightedForecast(drafts, 3000)).toBeLessThan(total);
  });
});

describe("confidenceBand", () => {
  it("монотонна: гарантировано ≤ вероятно ≤ потолок", () => {
    const b = confidenceBand(30000, 45000, 60000);
    expect(b).toEqual({ guaranteed: 30000, probable: 45000, ceiling: 60000 });
  });

  it("не даёт уровням проседать ниже предыдущего", () => {
    // взвешенный ниже гарантированного (странные данные) — вероятно подтягивается к нему
    const b = confidenceBand(50000, 40000, 45000);
    expect(b.probable).toBe(50000);
    expect(b.ceiling).toBe(50000);
  });
});

describe("monthPace", () => {
  it("текущий месяц: доля рабочих дней и applicable=true", () => {
    // 15 июля 2026 (среда); вс — выходной
    const p = monthPace("2026-07", new Date(2026, 6, 15, 12));
    expect(p.applicable).toBe(true);
    expect(p.total).toBeGreaterThan(20); // ~27 рабочих дней (пн-сб)
    expect(p.passed).toBeGreaterThan(0);
    expect(p.frac).toBeCloseTo(p.passed / p.total, 5);
  });

  it("будущий месяц: applicable=false (темп ещё не наступил)", () => {
    const p = monthPace("2026-08", new Date(2026, 6, 15));
    expect(p.applicable).toBe(false);
  });

  it("прошедший месяц: все рабочие дни пройдены", () => {
    const p = monthPace("2026-06", new Date(2026, 6, 15));
    expect(p.applicable).toBe(false);
    expect(p.passed).toBe(p.total);
  });
});

describe("paceStatus", () => {
  it("опережение — зелёный", () => {
    const s = paceStatus(60000, 90000, 0.5); // ожидалось 45000, собрано 60000
    expect(s).toMatchObject({ tone: "green", ahead: true });
    expect(s.delta).toBe(15000);
  });

  it("небольшое отставание — жёлтый", () => {
    const s = paceStatus(43000, 90000, 0.5); // ожидалось 45000, отстаём на ~4.4%
    expect(s.tone).toBe("amber");
    expect(s.ahead).toBe(false);
  });

  it("отставание больше 15% — красный", () => {
    const s = paceStatus(30000, 90000, 0.5); // ожидалось 45000, отстаём на 33%
    expect(s.tone).toBe("red");
  });
});

describe("concentration", () => {
  const totals = { s1: 50000, s2: 30000, s3: 20000, total: 100000 };

  it(">40% на одном источнике — красный «на одной ноге»", () => {
    const drafts = [draft({ source: "committed", gross: 25000, title: "Сделка А" })];
    const c = concentration(drafts, totals); // источник s1=50% > любой сделки
    expect(c.tone).toBe("red");
    expect(c.pct).toBeCloseTo(0.5, 5);
    expect(c.label).toContain("Сделки месяца");
  });

  it("25–40% — жёлтая концентрация", () => {
    const t = { s1: 35000, s2: 33000, s3: 32000, total: 100000 };
    const drafts = [draft({ gross: 20000 })];
    const c = concentration(drafts, t);
    expect(c.tone).toBe("amber");
  });

  it("равномерно — зелёный", () => {
    const t = { s1: 20000, s2: 20000, s3: 20000, total: 100000 };
    const drafts = [draft({ gross: 15000 })];
    const c = concentration(drafts, t);
    expect(c.tone).toBe("green");
    expect(c.label).toContain("распределён");
  });

  it("пустой план (total=0) не делит на ноль", () => {
    const c = concentration([], { s1: 0, s2: 0, s3: 0, total: 0 });
    expect(c.pct).toBe(0);
    expect(c.tone).toBe("green");
  });
});

describe("funnelCoverage", () => {
  it("нет дефицита — null", () => {
    expect(funnelCoverage(100, 500, 0)).toBeNull();
    expect(funnelCoverage(100, 500, -1000)).toBeNull();
  });

  it("нулевая прибыль со сделки — null (нечего делить)", () => {
    expect(funnelCoverage(100, 0, 5000)).toBeNull();
  });

  it("считает в прибыли÷прибыли, ≥3× — запас", () => {
    // 100 заявок × 300 прибыли = 30000 потенциала ÷ дефицит 5000 = 6×
    const c = funnelCoverage(100, 300, 5000);
    expect(c?.coverage).toBeCloseTo(6, 5);
    expect(c?.tone).toBe("green");
    expect(c?.needMoreLeads).toBeNull();
  });

  it("<1.5× — не хватит, подсказывает сколько ещё заявок до 3×", () => {
    // 10 заявок × 300 = 3000 ÷ дефицит 5000 = 0.6×
    const c = funnelCoverage(10, 300, 5000);
    expect(c?.tone).toBe("red");
    // до 3×: нужно 3×5000/300 = 50 заявок, ещё 40
    expect(c?.needMoreLeads).toBe(40);
  });
});
