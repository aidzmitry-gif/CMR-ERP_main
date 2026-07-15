import { describe, expect, it } from "vitest";

import {
  LOST_STAGE,
  REVIVE_AFTER_DAYS,
  STAGE_PROBABILITY,
  STUCK_DAYS,
  approvalBadge,
  cardAttention,
  closeabilityQueue,
  closeDateLabel,
  closeProximity,
  dateBucketId,
  dealStepText,
  daysInStage,
  daysUntilDate,
  discountGate,
  ensureLostStage,
  focusQueue,
  formatWaitAge,
  groupByDateBucket,
  inboundSignal,
  invoiceBadge,
  invoicesAtRisk,
  isClosedStageId,
  isOpenStage,
  isStuck,
  marginForecastResult,
  moveDealToStage,
  probabilityFor,
  recomputeStages,
  reviveDays,
  shouldAutoAssignNextStep,
  sortDealsForBoard,
  stageWeightedSum,
  waitAgeMsFor,
  type InvoiceRiskEntry,
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

  it("FIX-2: cond_lost (и производные коды секций) — не висяк; у него сигнал «реанимировать»", () => {
    expect(isStuck(deal("1", 100, { stageChangedAt: old }), "cond_lost", NOW)).toBe(false);
    expect(isStuck(deal("1", 100, { stageChangedAt: old }), "rp_won", NOW)).toBe(false);
    expect(isStuck(deal("1", 100, { stageChangedAt: old }), "tn_lost", NOW)).toBe(false);
  });

  it("не висяк без даты входа в стадию", () => {
    expect(isStuck(deal("1", 100), "new", NOW)).toBe(false);
  });
});

describe("isClosedStageId", () => {
  it("закрытые: won/lost + производные; открытые: остальные", () => {
    for (const id of ["won", "lost", "cond_lost", "rp_won", "tn_lost"]) {
      expect(isClosedStageId(id)).toBe(true);
    }
    for (const id of ["new", "contract", "has_price", "meeting"]) {
      expect(isClosedStageId(id)).toBe(false);
    }
  });
});

describe("reviveDays — реанимация «Условного отказа» (слайс 3)", () => {
  const NOW = Date.parse("2026-06-11T12:00:00Z");
  const daysAgo = (n: number) => new Date(NOW - n * 86_400_000).toISOString();

  it("cond_lost старше порога → дни в стадии; моложе порога → null", () => {
    expect(reviveDays(deal("1", 100, { stageChangedAt: daysAgo(10) }), "cond_lost", NOW)).toBe(10);
    expect(
      reviveDays(deal("1", 100, { stageChangedAt: daysAgo(REVIVE_AFTER_DAYS) }), "cond_lost", NOW),
    ).toBe(REVIVE_AFTER_DAYS);
    expect(
      reviveDays(deal("1", 100, { stageChangedAt: daysAgo(REVIVE_AFTER_DAYS - 1) }), "cond_lost", NOW),
    ).toBeNull();
  });

  it("не cond_lost или нет даты — null", () => {
    expect(reviveDays(deal("1", 100, { stageChangedAt: daysAgo(30) }), "new", NOW)).toBeNull();
    expect(reviveDays(deal("1", 100, { stageChangedAt: daysAgo(30) }), "lost", NOW)).toBeNull();
    expect(reviveDays(deal("1", 100), "cond_lost", NOW)).toBeNull();
  });
});

describe("sortDealsForBoard — «деньги × срочность» (слайс 3)", () => {
  const NOW = new Date(2026, 5, 11, 12, 0, 0).getTime();
  const at = (d: number) => new Date(2026, 5, d, 10).toISOString();

  it("просроченные (weighted DESC) → сегодня → завтра → остальные по weighted DESC", () => {
    const deals = [
      deal("plain-big", 1_000_000), // без даты, большой чек
      deal("today", 500, { nextStepAt: at(11) }),
      deal("overdue-small", 100, { nextStepAt: at(1) }),
      deal("tomorrow", 900, { nextStepAt: at(12) }),
      deal("overdue-big", 200, { nextStepAt: at(2) }),
      deal("plain-small", 50),
    ];
    const ordered = sortDealsForBoard(deals, "new", NOW).map((d) => d.id);
    expect(ordered).toEqual([
      "overdue-big", // 200 > 100 внутри «просрочено»
      "overdue-small",
      "today",
      "tomorrow",
      "plain-big", // остальные по weighted DESC
      "plain-small",
    ]);
  });

  it("закрытые стадии (won/lost/cond_lost) не сортируются — хронология как есть", () => {
    const deals = [deal("b", 10, { nextStepAt: at(1) }), deal("a", 999)];
    expect(sortDealsForBoard(deals, "won", NOW)).toBe(deals);
    expect(sortDealsForBoard(deals, "cond_lost", NOW)).toBe(deals);
  });

  it("до маунта (now=null) порядок исходный — без прыжка гидрации", () => {
    const deals = [deal("b", 10, { nextStepAt: at(1) }), deal("a", 999)];
    expect(sortDealsForBoard(deals, "new", null)).toBe(deals);
  });

  it("не мутирует вход", () => {
    const deals = [deal("b", 10, { nextStepAt: at(1) }), deal("a", 999)];
    const copy = [...deals];
    sortDealsForBoard(deals, "new", NOW);
    expect(deals).toEqual(copy);
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

  it("E (слайс 4): сделка с nextStepAt=сегодня получает бакет today — сквозная видимость чипа срочности", () => {
    // Проверка, что источник dateBucketId — nextStepAt (не legacy actionDate/todo): именно это
    // поле пишет композер NextStepComposer/handleNextStep, поэтому свежий шаг сразу
    // отражается в actBucket/чипе карточки (deals-workspace.tsx: actBucketFor → dateBucketId).
    expect(dateBucketId(deal("1", 100, { nextStepAt: at(2026, 5, 11, 9) }), NOW)).toBe("today");
  });
});

describe("dealStepText (слайс 4)", () => {
  it("todo + дата/время действия — склеены через « · »", () => {
    expect(
      dealStepText({ todo: "Согласовать КП", actionDate: "12.05", actionTime: "14:00" }),
    ).toBe("Согласовать КП · 12.05 · 14:00");
  });

  it("без todo — просто nextStep", () => {
    expect(dealStepText({ nextStep: "Позвонить" })).toBe("Позвонить");
  });

  it("todo без даты/времени — только сам todo (Boolean-фильтр пустых частей)", () => {
    expect(dealStepText({ todo: "Согласовать КП" })).toBe("Согласовать КП");
  });

  it("ничего не задано — undefined", () => {
    expect(dealStepText({})).toBeUndefined();
  });
});

describe("shouldAutoAssignNextStep (слайс 4, D)", () => {
  it("открытая стадия + нет шага (ни nextStep, ни todo) — true", () => {
    expect(shouldAutoAssignNextStep({}, "qual")).toBe(true);
  });

  it("закрытая стадия (won/lost + производные won/lost секций) — false", () => {
    expect(shouldAutoAssignNextStep({}, "won")).toBe(false);
    expect(shouldAutoAssignNextStep({}, "lost")).toBe(false);
    expect(shouldAutoAssignNextStep({}, "cond_lost")).toBe(false);
    expect(shouldAutoAssignNextStep({}, "rp_won")).toBe(false);
  });

  it("у сделки уже есть шаг (nextStep ИЛИ todo) — false, не перетираем ручной выбор", () => {
    expect(shouldAutoAssignNextStep({ nextStep: "Позвонить" }, "qual")).toBe(false);
    expect(shouldAutoAssignNextStep({ todo: "Согласовать" }, "qual")).toBe(false);
  });
});

describe("focusQueue — «Фокус дня» (слайс 5)", () => {
  const NOW = new Date(2026, 5, 11, 12, 0, 0).getTime(); // 11.06.2026 12:00 локальное
  const at = (d: number, h = 10) => new Date(2026, 5, d, h).toISOString();
  const daysAgoISO = (n: number) => new Date(NOW - n * 86_400_000).toISOString();

  it("now == null — пустой результат (SSR-гейт)", () => {
    const stages = [stage("new", [deal("1", 100)])];
    expect(focusQueue(stages, null)).toEqual({ items: [], total: 0 });
  });

  it("нет квалифицирующих сделок (шаг уже назначен) — пустой результат", () => {
    const stages = [stage("qual", [deal("has-step", 100, { nextStep: "Позвонить" })])];
    expect(focusQueue(stages, NOW)).toEqual({ items: [], total: 0 });
  });

  it("порядок: правее воронки раньше (вероятность стадии), внутри стадии — срочность", () => {
    const stages: Stage[] = [
      stage("new", [deal("notouch", 50, { stageChangedAt: daysAgoISO(2) })]),
      stage("qual", [
        deal("nostep", 100_000, { stageChangedAt: daysAgoISO(1) }),
        deal("overdue", 10, { nextStepAt: daysAgoISO(3) }),
        deal("today", 10, { nextStepAt: at(11) }),
      ]),
      stage("cond_lost", [deal("revive", 10, { stageChangedAt: daysAgoISO(REVIVE_AFTER_DAYS) })]),
    ];
    // qual (вероятность 25%) впереди new (10%) и cond_lost (5%); внутри qual — просрочено→сегодня→без шага.
    const ids = focusQueue(stages, NOW).items.map((i) => i.deal.id);
    expect(ids).toEqual(["overdue", "today", "nostep", "notouch", "revive"]);
  });

  it("близость к деньгам бьёт срочность: сделка у счёта (invoice, без шага) впереди просроченной холодной (new)", () => {
    const stages: Stage[] = [
      stage("new", [deal("cold-overdue", 100, { nextStepAt: daysAgoISO(5) })]),
      stage("qual", []),
      stage("price_req", []),
      stage("has_price", []),
      stage("meeting", []),
      stage("invoice", [deal("hot-nostep", 100, { stageChangedAt: daysAgoISO(1) })]),
    ];
    // invoice (70%) обгоняет new (10%), хотя у холодной шаг просрочен, а у горячей его вовсе нет.
    const ids = focusQueue(stages, NOW).items.map((i) => i.deal.id);
    expect(ids).toEqual(["hot-nostep", "cold-overdue"]);
  });

  it("severity: overdue=crit, today=warn, revive=info", () => {
    const stages: Stage[] = [
      stage("qual", [
        deal("overdue", 10, { nextStepAt: daysAgoISO(3) }),
        deal("today", 10, { nextStepAt: at(11) }),
      ]),
      stage("cond_lost", [deal("revive", 10, { stageChangedAt: daysAgoISO(10) })]),
    ];
    const items = focusQueue(stages, NOW).items;
    const sev = (id: string) => items.find((i) => i.deal.id === id)!.severity;
    expect(sev("overdue")).toBe("crit");
    expect(sev("today")).toBe("warn");
    expect(sev("revive")).toBe("info");
  });

  it("severity «без касания»: ≥1 дн — crit, 0 дн — warn", () => {
    const stages: Stage[] = [
      stage("new", [
        deal("notouch1", 10, { stageChangedAt: daysAgoISO(1) }),
        deal("notouch0", 10, { stageChangedAt: daysAgoISO(0) }),
      ]),
    ];
    const items = focusQueue(stages, NOW).items;
    const sev = (id: string) => items.find((i) => i.deal.id === id)!.severity;
    expect(sev("notouch1")).toBe("crit");
    expect(sev("notouch0")).toBe("warn");
  });

  it("текст reason соответствует формату каждого правила", () => {
    const stages: Stage[] = [
      stage("new", [deal("notouch", 10, { stageChangedAt: daysAgoISO(5) })]),
      stage("qual", [
        deal("nostep", 10, { stageChangedAt: daysAgoISO(2) }),
        deal("overdue", 10, { nextStepAt: daysAgoISO(3) }),
        deal("today", 10, { nextStepAt: at(11) }),
      ]),
      stage("cond_lost", [deal("revive", 10, { stageChangedAt: daysAgoISO(10) })]),
    ];
    const items = focusQueue(stages, NOW).items;
    const reason = (id: string) => items.find((i) => i.deal.id === id)!.reason;
    expect(reason("overdue")).toBe("просрочен 3 дн");
    expect(reason("today")).toBe("шаг сегодня");
    expect(reason("revive")).toBe("реанимировать · 10 дн");
    expect(reason("notouch")).toBe("без касания 5 дн");
    expect(reason("nostep")).toBe("без шага · в стадии 2 дн");
  });

  it("FIX-R1 (ревью 62c1a7d): просрочка на некратный интервал (вчера 20:00, сегодня 09:00) — «просрочен 1 дн», не 0", () => {
    const nowToday9 = new Date(2026, 5, 11, 9, 0, 0).getTime();
    const yesterday20 = new Date(2026, 5, 10, 20, 0, 0).toISOString();
    const stages: Stage[] = [stage("qual", [deal("overdue2", 10, { nextStepAt: yesterday20 })])];
    const items = focusQueue(stages, nowToday9).items;
    expect(items[0].reason).toBe("просрочен 1 дн");
  });

  it("правее воронки раньше: «без шага» в qual опережает «без касания» в new (близость к деньгам первична)", () => {
    const stages: Stage[] = [
      stage("new", [deal("touch-small", 1, { stageChangedAt: daysAgoISO(1) })]),
      stage("qual", [deal("step-big", 999_999, { stageChangedAt: daysAgoISO(30) })]),
    ];
    // qual (25%) впереди new (10%) — даже «без касания» новой заявки уступает сделке правее.
    const ids = focusQueue(stages, NOW).items.map((i) => i.deal.id);
    expect(ids).toEqual(["step-big", "touch-small"]);
  });

  it("внутри «без касания» сортирует по daysInStage DESC, не по деньгам", () => {
    const stages: Stage[] = [
      stage("new", [
        deal("a", 999_999, { stageChangedAt: daysAgoISO(1) }),
        deal("b", 1, { stageChangedAt: daysAgoISO(9) }),
      ]),
    ];
    const ids = focusQueue(stages, NOW).items.map((i) => i.deal.id);
    expect(ids).toEqual(["b", "a"]);
  });

  it("внутри «без шага» (остальные) сортирует по weighted DESC, не по дням", () => {
    const stages: Stage[] = [
      stage("new", []), // непустая позиция 0 — «qual» ниже НЕ первая стадия (иначе попал бы в «без касания»)
      stage("qual", [
        deal("a", 10, { stageChangedAt: daysAgoISO(30) }),
        deal("b", 999_999, { stageChangedAt: daysAgoISO(1) }),
      ]),
    ];
    const ids = focusQueue(stages, NOW).items.map((i) => i.deal.id);
    expect(ids).toEqual(["b", "a"]);
  });

  it("won/lost исключены целиком — даже формально «просроченные»", () => {
    const stages: Stage[] = [
      stage("won", [deal("w1", 100, { nextStepAt: daysAgoISO(5) })]),
      stage("lost", [deal("l1", 100, { nextStepAt: daysAgoISO(5) })]),
    ];
    expect(focusQueue(stages, NOW)).toEqual({ items: [], total: 0 });
  });

  it("cond_lost участвует ТОЛЬКО в реанимации — ниже порога не попадает никуда, даже если «просрочен»", () => {
    const stages: Stage[] = [
      stage("cond_lost", [
        deal("fresh", 100, { nextStepAt: daysAgoISO(5), stageChangedAt: daysAgoISO(2) }),
      ]),
    ];
    expect(focusQueue(stages, NOW)).toEqual({ items: [], total: 0 });
  });

  it("cap ограничивает items (по умолчанию 12), total считает все квалифицирующие", () => {
    const manyDeals = Array.from({ length: 15 }, (_, i) =>
      deal(`d${i}`, 100 + i, { nextStepAt: daysAgoISO(1) }),
    );
    const stages: Stage[] = [stage("qual", manyDeals)];
    const result = focusQueue(stages, NOW);
    expect(result.items).toHaveLength(12);
    expect(result.total).toBe(15);

    const result3 = focusQueue(stages, NOW, 3);
    expect(result3.items).toHaveLength(3);
    expect(result3.total).toBe(15);
  });
});

describe("cardAttention (цикл 8: единый чип внимания карточки)", () => {
  it("пустые сигналы — null (нет чипа)", () => {
    expect(cardAttention({})).toBeNull();
  });

  it("1. actBucket=overdue — «Просрочено», tone crit", () => {
    expect(cardAttention({ actBucket: "overdue" })).toEqual({
      label: "Просрочено",
      tone: "crit",
      title: "Следующий шаг просрочен",
    });
  });

  it("2. noTouchDays>=1 — «⏱ без касания N дн», tone crit", () => {
    expect(cardAttention({ noTouchDays: 3 })).toEqual({
      label: "⏱ без касания 3 дн",
      tone: "crit",
      title: "Новая заявка ещё не тронута — первое касание важнее прогрева",
    });
  });

  it("3. actBucket=today — «Сегодня», tone warn", () => {
    expect(cardAttention({ actBucket: "today" })).toEqual({
      label: "Сегодня",
      tone: "warn",
      title: "Следующий шаг сегодня",
    });
  });

  it("4. reviveDays задан — «реанимировать · N дн», tone revive", () => {
    expect(cardAttention({ reviveDays: 10 })).toEqual({
      label: "реанимировать · 10 дн",
      tone: "revive",
      title: "Условный отказ давно без касания — верни в работу",
    });
  });

  it("5. actBucket=tomorrow — «Завтра», tone soft", () => {
    expect(cardAttention({ actBucket: "tomorrow" })).toEqual({
      label: "Завтра",
      tone: "soft",
      title: "Следующий шаг завтра",
    });
  });

  it("6. stuck + daysInStage — «застрял N дн», tone soft", () => {
    expect(cardAttention({ stuck: true, daysInStage: 5 })).toEqual({
      label: "застрял 5 дн",
      tone: "soft",
      title: "Долго без движения по стадии",
    });
  });

  it("6b. stuck без daysInStage — сигнала нет (null)", () => {
    expect(cardAttention({ stuck: true, daysInStage: null })).toBeNull();
  });

  it("7. noTouchDays===0 — «⏱ без касания», tone muted", () => {
    expect(cardAttention({ noTouchDays: 0 })).toEqual({
      label: "⏱ без касания",
      tone: "muted",
      title: "Новая заявка сегодня — сделай первое касание",
    });
  });

  it("8. noStep — «нет шага», tone soft", () => {
    expect(cardAttention({ noStep: true })).toEqual({
      label: "нет шага",
      tone: "soft",
      title: "У сделки нет следующего шага — назначь действие",
    });
  });

  it("вытеснение: overdue побеждает noStep", () => {
    const r = cardAttention({ actBucket: "overdue", noStep: true });
    expect(r?.label).toBe("Просрочено");
  });

  it("вытеснение: noTouchDays>=1 побеждает actBucket=today", () => {
    const r = cardAttention({ actBucket: "today", noTouchDays: 1 });
    expect(r?.label).toBe("⏱ без касания 1 дн");
  });

  it("вытеснение: actBucket=today побеждает reviveDays", () => {
    const r = cardAttention({ actBucket: "today", reviveDays: 10 });
    expect(r?.label).toBe("Сегодня");
  });

  it("вытеснение: reviveDays побеждает actBucket=tomorrow", () => {
    const r = cardAttention({ actBucket: "tomorrow", reviveDays: 10 });
    expect(r?.label).toBe("реанимировать · 10 дн");
  });

  it("вытеснение: actBucket=tomorrow побеждает «застрял»", () => {
    const r = cardAttention({ actBucket: "tomorrow", stuck: true, daysInStage: 5 });
    expect(r?.label).toBe("Завтра");
  });

  it("вытеснение: «застрял» побеждает noTouchDays===0", () => {
    const r = cardAttention({ stuck: true, daysInStage: 5, noTouchDays: 0 });
    expect(r?.label).toBe("застрял 5 дн");
  });

  it("вытеснение: noTouchDays===0 побеждает noStep", () => {
    const r = cardAttention({ noTouchDays: 0, noStep: true });
    expect(r?.label).toBe("⏱ без касания");
  });
});

describe("daysUntilDate (слайс 6)", () => {
  const NOW = new Date(2026, 5, 11, 12, 0, 0).getTime(); // 11.06.2026 12:00 локальное

  it("сегодня — 0", () => {
    expect(daysUntilDate("2026-06-11", NOW)).toBe(0);
  });

  it("через N дней — положительное число", () => {
    expect(daysUntilDate("2026-06-16", NOW)).toBe(5);
  });

  it("в прошлом — отрицательное число", () => {
    expect(daysUntilDate("2026-06-01", NOW)).toBe(-10);
  });
});

describe("invoiceBadge (слайс 6, C)", () => {
  const NOW = new Date(2026, 5, 11, 12, 0, 0).getTime(); // 11.06.2026 12:00 локальное

  it("«✓ оплачен» — ТОЛЬКО paid; posted = записан в 1С, деньги не дошли (ревью f4f825d)", () => {
    expect(invoiceBadge({ status: "paid", validUntil: null }, NOW)).toEqual({
      label: "✓ оплачен",
      tone: "green",
    });
    // posted с истёкшим сроком — «просрочен», а не ложное «оплачен»
    expect(invoiceBadge({ status: "posted", validUntil: "2020-01-01" }, NOW)).toEqual({
      label: "💳 просрочен",
      tone: "red",
    });
  });

  it("posted без valid_until — нейтральный «не оплачен» (записан в 1С, ждём денег)", () => {
    expect(invoiceBadge({ status: "posted", validUntil: null }, NOW)).toEqual({
      label: "💳 не оплачен",
      tone: "neutral",
    });
  });

  it("valid_until = null и не posted/paid — honest-empty null (нет данных для бейджа)", () => {
    expect(invoiceBadge({ status: "draft", validUntil: null }, NOW)).toBeNull();
  });

  it("valid_until сегодня — «истекает 0д», жёлтый (K<=2)", () => {
    expect(invoiceBadge({ status: "draft", validUntil: "2026-06-11" }, NOW)).toEqual({
      label: "💳 истекает 0д",
      tone: "amber",
    });
  });

  it("valid_until в прошлом — «просрочен» красный", () => {
    expect(invoiceBadge({ status: "draft", validUntil: "2026-06-01" }, NOW)).toEqual({
      label: "💳 просрочен",
      tone: "red",
    });
  });

  it("valid_until через 5 дней — нейтральный тон (K>2)", () => {
    expect(invoiceBadge({ status: "draft", validUntil: "2026-06-16" }, NOW)).toEqual({
      label: "💳 истекает 5д",
      tone: "neutral",
    });
  });
});

describe("waitAgeMsFor (цикл 17 + фикс адверсарной верификации: наивный UTC без зоны)", () => {
  it("наивная строка без зоны (бэк шлёт naive UTC, «2026-07-11T12:00:00») — трактуется как UTC, не как локальное время раннера", () => {
    const since = Date.parse("2026-07-11T12:00:00Z");
    // ДО фикса Date.parse("2026-07-11T12:00:00") трактовал строку как ЛОКАЛЬНОЕ время —
    // в TZ восточнее UTC результат ушёл бы в отрицательные часы (обрезанные до 0 Math.max),
    // в TZ западнее — раздулся бы на лишние часы. Здесь возраст всегда ровно 5 минут.
    expect(waitAgeMsFor("2026-07-11T12:00:00", since + 5 * 60_000)).toBe(5 * 60_000);
  });

  it("строка с явной зоной Z — поведение не тронуто (парсим как есть, Z не дублируем)", () => {
    const since = Date.parse("2026-07-11T12:00:00Z");
    expect(waitAgeMsFor("2026-07-11T12:00:00Z", since + 5 * 60_000)).toBe(5 * 60_000);
  });

  it("строка с явным смещением (+03:00) — тоже не тронута (уже есть зона)", () => {
    const since = Date.parse("2026-07-11T15:00:00+03:00"); // == 12:00 UTC
    expect(waitAgeMsFor("2026-07-11T15:00:00+03:00", since + 60_000)).toBe(60_000);
  });

  it("waitingSince/now не заданы — null (graceful, бэк без миграции / до маунта)", () => {
    expect(waitAgeMsFor(null, 1000)).toBeNull();
    expect(waitAgeMsFor(undefined, 1000)).toBeNull();
    expect(waitAgeMsFor("2026-07-11T12:00:00Z", null)).toBeNull();
  });

  it("нераспознаваемая строка — null, не NaN", () => {
    expect(waitAgeMsFor("не-дата", 1000)).toBeNull();
  });

  it("будущий waiting_since (рассинхрон часов клиент/сервер) не уходит в минус", () => {
    const since = Date.parse("2026-07-11T12:00:00Z");
    expect(waitAgeMsFor("2026-07-11T12:00:00", since - 1000)).toBe(0);
  });
});

describe("inboundSignal (цикл 11: клиент ждёт ответа)", () => {
  it("unread>0 — бейдж «💬 N», тон money (самый горячий сигнал)", () => {
    expect(inboundSignal({ unread: 3, missed: 2 })).toEqual({
      label: "💬 3",
      tone: "money",
      title: "Клиент ждёт ответа — непрочитанных сообщений: 3",
    });
  });

  it("unread=0, missed>0 — «☎ пропущен», тон amber", () => {
    expect(inboundSignal({ unread: 0, missed: 1 })).toEqual({
      label: "☎ пропущен",
      tone: "amber",
      title: "Пропущенный звонок от клиента без ответа",
    });
  });

  it("unread приоритетнее missed — при обоих сигналах побеждает unread", () => {
    expect(inboundSignal({ unread: 1, missed: 5 })?.tone).toBe("money");
  });

  it("ни unread ни missed — null, бейдж не рендерится", () => {
    expect(inboundSignal({})).toBeNull();
    expect(inboundSignal({ unread: 0, missed: 0 })).toBeNull();
  });

  it("цикл 17: unread>1 + waitAgeMs известен — лейбл «💬 N · ждёт Nм/Nч/Nд» (фикс: счётчик не теряется)", () => {
    expect(inboundSignal({ unread: 2, waitAgeMs: 5 * 60_000 })).toEqual({
      label: "💬 2 · ждёт 5м",
      tone: "money",
      title: "Клиент ждёт ответа — непрочитанных сообщений: 2",
    });
  });

  it("цикл 17: unread===1 + waitAgeMs известен — лейбл «💬 ждёт Nм» без счётчика (1 и так очевидна)", () => {
    expect(inboundSignal({ unread: 1, waitAgeMs: 5 * 60_000 })).toEqual({
      label: "💬 ждёт 5м",
      tone: "money",
      title: "Клиент ждёт ответа — непрочитанных сообщений: 1",
    });
  });

  it("цикл 17: waitAgeMs не задан/null — graceful, старый лейбл «💬 N» (бэк без waiting_since)", () => {
    expect(inboundSignal({ unread: 2, waitAgeMs: null })?.label).toBe("💬 2");
    expect(inboundSignal({ unread: 2 })?.label).toBe("💬 2");
  });
});

describe("formatWaitAge (цикл 17: возраст ожидания ответа)", () => {
  it("< 60 минут — «Nм»", () => {
    expect(formatWaitAge(0)).toBe("0м");
    expect(formatWaitAge(5 * 60_000)).toBe("5м");
  });

  it("граница 59м/60м — 59 минут ещё «м», 60 минут уже «ч»", () => {
    expect(formatWaitAge(59 * 60_000)).toBe("59м");
    expect(formatWaitAge(60 * 60_000)).toBe("1ч");
  });

  it("< 24 часов — «Nч»", () => {
    expect(formatWaitAge(5 * 3_600_000)).toBe("5ч");
  });

  it("граница 23ч/24ч — 23 часа ещё «ч», 24 часа уже «д»", () => {
    expect(formatWaitAge(23 * 3_600_000)).toBe("23ч");
    expect(formatWaitAge(24 * 3_600_000)).toBe("1д");
  });

  it("≥ 24 часов — «Nд»", () => {
    expect(formatWaitAge(3 * 86_400_000)).toBe("3д");
  });

  it("отрицательный ms (рассинхрон часов) — честные «0м», не минус", () => {
    expect(formatWaitAge(-1000)).toBe("0м");
  });
});

describe("discountGate (слайс 9)", () => {
  it("пустой список позиций — null (гейта нет)", () => {
    expect(discountGate([], 1000)).toBeNull();
  });

  it("все min_price=null — null (нет ни одного справочного минимума)", () => {
    expect(
      discountGate(
        [
          { qty: 2, min_price: null },
          { qty: 1, min_price: null },
        ],
        100,
      ),
    ).toBeNull();
  });

  it("ровно на границе (amount === minTotal) — null, граница не нарушение", () => {
    // 2×100 + 1×50 = 250
    expect(
      discountGate(
        [
          { qty: 2, min_price: 100 },
          { qty: 1, min_price: 50 },
        ],
        250,
      ),
    ).toBeNull();
  });

  it("amount ниже минимума — корректные minTotal/gap", () => {
    // 2×100 + 1×50 = 250, amount=200 → gap=50
    expect(
      discountGate(
        [
          { qty: 2, min_price: 100 },
          { qty: 1, min_price: 50 },
        ],
        200,
      ),
    ).toEqual({ minTotal: 250, gap: 50 });
  });

  it("частичные min_price — считает только позиции с известным минимумом", () => {
    // известна только 1-я позиция: 3×40 = 120; 2-я (min_price=null) не участвует в сумме
    expect(
      discountGate(
        [
          { qty: 3, min_price: 40 },
          { qty: 5, min_price: null },
        ],
        100,
      ),
    ).toEqual({ minTotal: 120, gap: 20 });
  });
});

describe("invoicesAtRisk (цикл 12: счета под риском — резерв уходит)", () => {
  const NOW = new Date(2026, 5, 11, 12, 0, 0).getTime(); // 11.06.2026 12:00 локальное

  const entry = (
    dealId: string,
    amount: number,
    doc: Partial<InvoiceRiskEntry["doc"]>,
  ): InvoiceRiskEntry => ({
    deal: deal(dealId, amount),
    doc: {
      number: `СЧ-${dealId}`,
      status: "posted",
      validUntil: null,
      reserveStatus: "reserved",
      amount,
      ...doc,
    },
  });

  it("просроченный posted-счёт попадает в очередь — severity crit, подпись «просрочен N дн»", () => {
    const { items, total } = invoicesAtRisk([entry("1", 1000, { validUntil: "2026-06-01" })], NOW);
    expect(total).toBe(1);
    expect(items[0]).toMatchObject({ severity: "crit", reason: "просрочен 10 дн", docNumber: "СЧ-1" });
  });

  it("истекающий в пределах порога — severity warn, подпись «истекает N дн»", () => {
    const { items } = invoicesAtRisk([entry("1", 1000, { validUntil: "2026-06-13" })], NOW);
    expect(items[0]).toMatchObject({ severity: "warn", reason: "истекает 2 дн · резерв уйдёт" });
  });

  it("истекающий за пределами порога (>3 дн) и резерв не снят — вне очереди", () => {
    const { items, total } = invoicesAtRisk([entry("1", 1000, { validUntil: "2026-06-20" })], NOW);
    expect(items).toHaveLength(0);
    expect(total).toBe(0);
  });

  it("резерв уже снят, оплаты нет (даже без активного срока) — severity warn", () => {
    const { items } = invoicesAtRisk(
      [entry("1", 1000, { validUntil: null, reserveStatus: "released" })],
      NOW,
    );
    expect(items[0]).toMatchObject({ severity: "warn", reason: "резерв снят, оплаты нет" });
  });

  it("оплаченный (paid) счёт — исключён из очереди даже с истёкшим сроком", () => {
    const { items, total } = invoicesAtRisk(
      [entry("1", 1000, { status: "paid", validUntil: "2020-01-01" })],
      NOW,
    );
    expect(items).toHaveLength(0);
    expect(total).toBe(0);
  });

  it("черновик (draft, ещё не выставлен всерьёз) — исключён из очереди", () => {
    const { items } = invoicesAtRisk([entry("1", 1000, { status: "draft", validUntil: "2020-01-01" })], NOW);
    expect(items).toHaveLength(0);
  });

  it("сортировка: просроченные впереди истекающих, крупнее просрочка — раньше", () => {
    const { items } = invoicesAtRisk(
      [
        entry("expiring", 5000, { validUntil: "2026-06-13" }), // истекает через 2 дн
        entry("overdue-small", 100, { validUntil: "2026-06-10" }), // просрочен 1 дн
        entry("overdue-big", 100, { validUntil: "2026-06-01" }), // просрочен 10 дн
      ],
      NOW,
    );
    expect(items.map((i) => i.deal.id)).toEqual(["overdue-big", "overdue-small", "expiring"]);
  });

  it("при равной срочности — крупнее сумма счёта раньше", () => {
    const { items } = invoicesAtRisk(
      [
        entry("small", 500, { validUntil: "2026-06-13" }),
        entry("big", 5000, { validUntil: "2026-06-13" }),
      ],
      NOW,
    );
    expect(items.map((i) => i.deal.id)).toEqual(["big", "small"]);
  });

  it("cap обрезает очередь, но total считает ДО обрезки", () => {
    const entries = [1, 2, 3].map((n) => entry(String(n), n, { validUntil: "2026-06-01" }));
    const { items, total } = invoicesAtRisk(entries, NOW, 2);
    expect(items).toHaveLength(2);
    expect(total).toBe(3);
  });
});

describe("closeProximity / closeDateLabel (цикл 13: дожать до плана)", () => {
  const NOW = new Date(2026, 5, 11, 12, 0, 0).getTime(); // 11.06.2026 12:00 локальное

  it("просроченная дата — максимальная близость (1)", () => {
    expect(closeProximity("2026-06-01", NOW)).toBe(1);
  });

  it("сегодняшняя дата — максимальная близость (1)", () => {
    expect(closeProximity("2026-06-11", NOW)).toBe(1);
  });

  it("дата через 14 дней — близость 0.5 (половина затухания)", () => {
    expect(closeProximity("2026-06-25", NOW)).toBeCloseTo(0.5, 5);
  });

  it("очень далёкая дата не опускается ниже пола 0.15", () => {
    expect(closeProximity("2027-06-11", NOW)).toBeCloseTo(0.15, 5);
  });

  it("нет даты — нейтральная близость 0.4 (не 0 и не максимум)", () => {
    expect(closeProximity(undefined, NOW)).toBe(0.4);
  });

  it("неразборчивая дата — тот же нейтральный fallback, без падения", () => {
    expect(closeProximity("не дата", NOW)).toBe(0.4);
  });

  it("closeDateLabel: сегодня/просрочена/через N/не задана", () => {
    expect(closeDateLabel("2026-06-11", NOW)).toBe("ожид. сегодня");
    expect(closeDateLabel("2026-06-01", NOW)).toBe("просрочена на 10 дн");
    expect(closeDateLabel("2026-06-20", NOW)).toBe("ожид. через 9 дн");
    expect(closeDateLabel(undefined, NOW)).toBe("дата не задана");
  });
});

describe("closeabilityQueue (цикл 13: дожать до плана)", () => {
  const NOW = new Date(2026, 5, 11, 12, 0, 0).getTime(); // 11.06.2026 12:00 локальное

  it("сортирует по итоговому баллу DESC (probability × proximity × amount)", () => {
    const stages = [
      stage("negotiation", [
        deal("low", 1000, { probability: 20, expectedCloseDate: "2026-06-11" }),
        deal("high", 1000, { probability: 90, expectedCloseDate: "2026-06-11" }),
      ]),
    ];
    const { items } = closeabilityQueue(stages, NOW);
    expect(items.map((i) => i.deal.id)).toEqual(["high", "low"]);
  });

  it("вклад вероятности: выше probability при равных сумме/дате — выше в очереди", () => {
    const stages = [
      stage("negotiation", [
        deal("a", 5000, { probability: 30, expectedCloseDate: "2026-06-11" }),
        deal("b", 5000, { probability: 70, expectedCloseDate: "2026-06-11" }),
      ]),
    ];
    const { items } = closeabilityQueue(stages, NOW);
    expect(items[0].deal.id).toBe("b");
    expect(items[0].probability).toBe(70);
  });

  it("вклад суммы: крупнее amount при равных probability/дате — выше в очереди", () => {
    const stages = [
      stage("negotiation", [
        deal("small", 1000, { probability: 50, expectedCloseDate: "2026-06-11" }),
        deal("big", 9000, { probability: 50, expectedCloseDate: "2026-06-11" }),
      ]),
    ];
    const { items } = closeabilityQueue(stages, NOW);
    expect(items.map((i) => i.deal.id)).toEqual(["big", "small"]);
  });

  it("вклад близости даты: просроченная/сегодня опережает далёкую при равных probability/сумме", () => {
    const stages = [
      stage("negotiation", [
        deal("far", 5000, { probability: 50, expectedCloseDate: "2027-06-11" }),
        deal("soon", 5000, { probability: 50, expectedCloseDate: "2026-06-11" }),
      ]),
    ];
    const { items } = closeabilityQueue(stages, NOW);
    expect(items.map((i) => i.deal.id)).toEqual(["soon", "far"]);
  });

  it("won/lost/cond_lost — терминальные стадии исключены из очереди целиком", () => {
    const stages = [
      stage("negotiation", [deal("open", 1000, { probability: 50 })]),
      stage("won", [deal("w", 5000, { probability: 100 })]),
      stage("lost", [deal("l", 5000, { probability: 0 })]),
      stage("cond_lost", [deal("c", 5000, { probability: 5 })]),
    ];
    const { items, total } = closeabilityQueue(stages, NOW);
    expect(total).toBe(1);
    expect(items.map((i) => i.deal.id)).toEqual(["open"]);
  });

  it("сделка без expectedCloseDate участвует в очереди (нейтральная близость, не исключается)", () => {
    const stages = [stage("negotiation", [deal("no-date", 1000, { probability: 50 })])];
    const { items, total } = closeabilityQueue(stages, NOW);
    expect(total).toBe(1);
    expect(items[0].dateLabel).toBe("дата не задана");
  });

  it("now == null — пустой результат (SSR/до маунта)", () => {
    const stages = [stage("negotiation", [deal("a", 1000, { probability: 50 })])];
    expect(closeabilityQueue(stages, null)).toEqual({ items: [], total: 0 });
  });

  it("cap обрезает очередь, но total считает ДО обрезки", () => {
    const stages = [
      stage(
        "negotiation",
        [1, 2, 3].map((n) => deal(String(n), n * 1000, { probability: 50 })),
      ),
    ];
    const { items, total } = closeabilityQueue(stages, NOW, 2);
    expect(items).toHaveLength(2);
    expect(total).toBe(3);
  });
});

describe("approvalBadge (цикл 14: статус одобрения РОП)", () => {
  it("approved — «✅ скидка одобрена», тон money", () => {
    expect(approvalBadge("approved")).toEqual({
      label: "✅ скидка одобрена",
      tone: "money",
      title: "РОП одобрил скидку — закрывай по согласованной цене",
    });
  });

  it("rejected — «⛔ не одобрено», тон red", () => {
    expect(approvalBadge("rejected")).toEqual({
      label: "⛔ не одобрено",
      tone: "red",
      title: "РОП отклонил запрос на скидку",
    });
  });

  it("pending — honest-null (не шумим, факт запроса уже виден по скидочному гейту)", () => {
    expect(approvalBadge("pending")).toBeNull();
  });

  it("undefined/неизвестный статус — honest-null", () => {
    expect(approvalBadge(undefined)).toBeNull();
    expect(approvalBadge("weird")).toBeNull();
  });
});

describe("marginForecastResult (цикл 15: правда о марже вместо демо-константы)", () => {
  it("forecast == null (фетч не удался/ещё не пришёл) — honest-null", () => {
    expect(marginForecastResult(null)).toBeNull();
  });

  it("gross_weighted == null (фасад landed_cost не подключён/ничего не оценено) — honest-null", () => {
    expect(
      marginForecastResult({ gross_weighted: null, deals_priced: 0, deals_total: 5 }),
    ).toBeNull();
  });

  it("полная оценка (deals_priced === deals_total) — число без title", () => {
    expect(
      marginForecastResult({ gross_weighted: 1234.6, deals_priced: 5, deals_total: 5 }),
    ).toEqual({ amount: 1235, title: null });
  });

  it("частичная оценка (deals_priced < deals_total) — число + title «оценено по N из M»", () => {
    expect(
      marginForecastResult({ gross_weighted: 1000, deals_priced: 3, deals_total: 5 }),
    ).toEqual({ amount: 1000, title: "оценено по 3 из 5 сделок" });
  });

  it("gross_weighted == 0 — честный ноль, не путать с null", () => {
    expect(
      marginForecastResult({ gross_weighted: 0, deals_priced: 2, deals_total: 2 }),
    ).toEqual({ amount: 0, title: null });
  });
});
