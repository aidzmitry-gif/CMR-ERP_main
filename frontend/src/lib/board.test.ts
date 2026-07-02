import { describe, expect, it } from "vitest";

import {
  LOST_STAGE,
  STAGE_PROBABILITY,
  STUCK_DAYS,
  dateBucketId,
  daysInStage,
  ensureLostStage,
  groupByDateBucket,
  isOpenStage,
  isStuck,
  moveDealToStage,
  probabilityFor,
  recomputeStages,
  stageWeightedSum,
  weightedAmount,
} from "@/lib/board";
import type { Deal, Stage } from "@/lib/types";

const deal = (id: string, amount: number, extra: Partial<Deal> = {}): Deal => ({
  id,
  number: `N-${id}`,
  company: "ООО",
  description: "d",
  amount,
  priority: "Средний",
  owner: "o",
  ...extra,
});
const stage = (id: string, deals: Deal[]): Stage => ({ id, title: id, color: "#000", count: deals.length, sum: 0, deals });

describe("recomputeStages", () => {
  it("пересчитывает count и sum по сделкам стадии", () => {
    const [s] = recomputeStages([stage("new", [deal("1", 100), deal("2", 50)])]);
    expect(s.count).toBe(2);
    expect(s.sum).toBe(150);
  });
});

describe("moveDealToStage", () => {
  const stages = [stage("new", [deal("1", 100)]), stage("won", [])];

  it("перемещает сделку в целевую стадию и пересчитывает агрегаты", () => {
    const next = moveDealToStage(stages, "1", "won");
    expect(next.find((s) => s.id === "new")!.deals).toHaveLength(0);
    const won = next.find((s) => s.id === "won")!;
    expect(won.deals).toHaveLength(1);
    expect(won.count).toBe(1);
    expect(won.sum).toBe(100);
  });

  it("возвращает прежний массив, если сделка уже в целевой стадии", () => {
    expect(moveDealToStage(stages, "1", "new")).toBe(stages);
  });

  it("возвращает прежний массив для несуществующей сделки", () => {
    expect(moveDealToStage(stages, "999", "won")).toBe(stages);
  });
});

describe("ensureLostStage (SALES-40)", () => {
  it("добавляет стадию «отказ» в конец, если её нет (fallback без бэка)", () => {
    const next = ensureLostStage([stage("new", []), stage("won", [])]);
    expect(next).toHaveLength(3);
    const last = next[next.length - 1];
    expect(last.id).toBe("lost");
    expect(last.title).toBe(LOST_STAGE.title);
    expect(last.color).toBe("#EF4444");
    expect(last.deals).toEqual([]);
  });

  it("идемпотентна: не дублирует стадию, если она уже пришла с бэка", () => {
    const withLost = [stage("new", []), { ...LOST_STAGE, count: 0, sum: 0, deals: [] }];
    expect(ensureLostStage(withLost)).toBe(withLost);
  });
});

describe("probabilityFor (SALES-44)", () => {
  it("берёт дефолт по стадии, если probability не задана", () => {
    expect(probabilityFor(deal("1", 100), "new")).toBe(STAGE_PROBABILITY.new);
    expect(probabilityFor(deal("1", 100), "contract")).toBe(STAGE_PROBABILITY.contract);
  });

  it("уважает явно заданную probability, включая 0", () => {
    expect(probabilityFor(deal("1", 100, { probability: 90 }), "new")).toBe(90);
    expect(probabilityFor(deal("1", 100, { probability: 0 }), "new")).toBe(0);
  });

  it("0 для неизвестной стадии без явной вероятности", () => {
    expect(probabilityFor(deal("1", 100), "unknown")).toBe(0);
  });
});

describe("weightedAmount / stageWeightedSum (SALES-44)", () => {
  it("взвешенная сумма сделки = amount × probability / 100", () => {
    expect(weightedAmount(deal("1", 1_000_000, { probability: 50 }), "has_price")).toBe(500_000);
    expect(weightedAmount(deal("1", 1_000_000), "protected")).toBe(850_000); // дефолт protected=85%
  });

  it("взвешенная сумма стадии суммирует по всем сделкам", () => {
    const s = stage("has_price", [
      deal("1", 1_000_000, { probability: 50 }), // 500 000
      deal("2", 400_000), // дефолт has_price → 400 000 × prob
    ]);
    expect(stageWeightedSum(s)).toBe(500_000 + (400_000 * STAGE_PROBABILITY.has_price) / 100);
  });
});

describe("isOpenStage — единый охват взвешенного прогноза (SALES-44)", () => {
  it("открытый pipeline: всё, кроме won/lost/cond_lost", () => {
    expect(isOpenStage(stage("new", []))).toBe(true);
    expect(isOpenStage(stage("contract", []))).toBe(true);
    expect(isOpenStage(stage("won", []))).toBe(false);
    expect(isOpenStage(stage("lost", []))).toBe(false);
    expect(isOpenStage(stage("cond_lost", []))).toBe(false);
  });

  it("Σ «взвешенно» по открытым колонкам = итогу строки (cond_lost не рассинхронит)", () => {
    // Раньше cond_lost с карточками показывался в колонке (5%), но не входил в итог PipelineRow
    // (open-фильтр) → Σ колонок ≠ итогу. Единый isOpenStage устраняет расхождение.
    const stages = [
      stage("new", [deal("1", 1_000_000)]),
      stage("cond_lost", [deal("2", 500_000)]),
      stage("won", [deal("3", 800_000)]),
    ];
    const rowTotal = stages.filter(isOpenStage).reduce((n, s) => n + stageWeightedSum(s), 0);
    // Колонки показывают «взвешенно» ровно для тех же стадий (showWeighted = isOpenStage && deals>0).
    const columnsSum = stages
      .filter((s) => isOpenStage(s) && s.deals.length > 0)
      .reduce((n, s) => n + stageWeightedSum(s), 0);
    expect(columnsSum).toBe(rowTotal);
    expect(rowTotal).toBe((1_000_000 * STAGE_PROBABILITY.new) / 100); // cond_lost/won вклада не дают
  });
});

describe("daysInStage (SALES-43)", () => {
  const NOW = Date.parse("2026-06-11T12:00:00Z");

  it("считает целые дни от stage_changed_at", () => {
    expect(daysInStage("2026-06-07T12:00:00Z", NOW)).toBe(4);
    expect(daysInStage("2026-06-10T12:00:00Z", NOW)).toBe(1);
    expect(daysInStage("2026-06-11T00:00:00Z", NOW)).toBe(0);
  });

  it("null, если дата неизвестна или неразборчива", () => {
    expect(daysInStage(undefined, NOW)).toBeNull();
    expect(daysInStage("не-дата", NOW)).toBeNull();
  });

  it("не уходит в минус для будущей даты", () => {
    expect(daysInStage("2026-06-20T12:00:00Z", NOW)).toBe(0);
  });
});

describe("isStuck (SALES-43)", () => {
  const NOW = Date.parse("2026-06-11T12:00:00Z");
  const old = "2026-06-06T12:00:00Z"; // 5 дней
  const recent = "2026-06-10T12:00:00Z"; // 1 день

  it("висяк: открытая стадия без движения ≥ порога", () => {
    expect(isStuck(deal("1", 100, { stageChangedAt: old }), "new", NOW)).toBe(true);
    expect(STUCK_DAYS).toBe(4);
  });

  it("не висяк, если в стадии меньше порога", () => {
    expect(isStuck(deal("1", 100, { stageChangedAt: recent }), "new", NOW)).toBe(false);
  });

  it("терминальные стадии (won/lost) никогда не висяки", () => {
    expect(isStuck(deal("1", 100, { stageChangedAt: old }), "won", NOW)).toBe(false);
    expect(isStuck(deal("1", 100, { stageChangedAt: old }), "lost", NOW)).toBe(false);
  });

  it("не висяк без даты входа в стадию", () => {
    expect(isStuck(deal("1", 100), "new", NOW)).toBe(false);
  });
});

describe("dateBucketId / groupByDateBucket (П4, слайс 4)", () => {
  // Локальное время (не UTC): 11.06.2026 12:00 — избегаем TZ-сдвига полуночи «сегодня».
  const NOW = new Date(2026, 5, 11, 12, 0, 0).getTime();
  const at = (y: number, m: number, d: number, h = 12) => new Date(y, m, d, h).toISOString();

  it("без next_step_at — честный бакет «Без даты» (не «Позже»)", () => {
    expect(dateBucketId(deal("1", 100), NOW)).toBe("no_date");
  });

  it("неразборчивая дата — тоже «Без даты»", () => {
    expect(dateBucketId(deal("1", 100, { nextStepAt: "не-дата" }), NOW)).toBe("no_date");
  });

  it("вчера/раньше сегодняшней полуночи — просрочено", () => {
    expect(dateBucketId(deal("1", 100, { nextStepAt: at(2026, 5, 10, 23) }), NOW)).toBe("overdue");
    expect(dateBucketId(deal("1", 100, { nextStepAt: at(2026, 5, 1) }), NOW)).toBe("overdue");
  });

  it("сегодня (00:00..23:59 календарного дня) — «Сегодня» независимо от текущего часа", () => {
    expect(dateBucketId(deal("1", 100, { nextStepAt: at(2026, 5, 11, 0) }), NOW)).toBe("today");
    expect(dateBucketId(deal("1", 100, { nextStepAt: at(2026, 5, 11, 23) }), NOW)).toBe("today");
  });

  it("завтра — «Завтра»", () => {
    expect(dateBucketId(deal("1", 100, { nextStepAt: at(2026, 5, 12, 1) }), NOW)).toBe("tomorrow");
  });

  it("через 3-6 дней — «Неделя», через 8-29 — «Месяц», 31+ — «Позже»", () => {
    expect(dateBucketId(deal("1", 100, { nextStepAt: at(2026, 5, 14) }), NOW)).toBe("week");
    expect(dateBucketId(deal("1", 100, { nextStepAt: at(2026, 5, 20) }), NOW)).toBe("month");
    expect(dateBucketId(deal("1", 100, { nextStepAt: at(2026, 6, 20) }), NOW)).toBe("later");
  });

  it("groupByDateBucket возвращает все 7 бакетов (даже пустые) и не теряет сделки", () => {
    const deals = [
      deal("1", 100, { nextStepAt: at(2026, 5, 10, 23) }), // overdue
      deal("2", 200, { nextStepAt: at(2026, 5, 11, 8) }), // today
      deal("3", 300), // no_date
    ];
    const buckets = groupByDateBucket(deals, NOW);
    expect(buckets).toHaveLength(7);
    expect(buckets.find((b) => b.id === "overdue")?.deals.map((d) => d.id)).toEqual(["1"]);
    expect(buckets.find((b) => b.id === "today")?.deals.map((d) => d.id)).toEqual(["2"]);
    expect(buckets.find((b) => b.id === "no_date")?.deals.map((d) => d.id)).toEqual(["3"]);
    expect(buckets.find((b) => b.id === "tomorrow")?.deals).toEqual([]);
    const total = buckets.reduce((n, b) => n + b.deals.length, 0);
    expect(total).toBe(deals.length);
  });
});
