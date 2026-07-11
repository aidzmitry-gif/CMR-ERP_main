import { describe, expect, it } from "vitest";

import {
  DEFAULT_MESSAGE_TEMPLATES,
  DEFAULT_NEXT_STEP_TEMPLATES,
  MESSAGE_TEMPLATES,
  NEXT_STEP_TEMPLATES,
  PROGRESSION_STAGES,
  SALES_STAGES,
  STAGE_BY_ID,
  TERMINAL_STAGES,
  messageTemplatesFor,
  nextStepPreset,
  nextStepTemplatesFor,
  presetDateISO,
  progressionIndex,
} from "@/lib/sales-stages";

describe("SALES_STAGES (канон, зеркало backend stages.py)", () => {
  it("11 стадий, начинается с new, заканчивается lost", () => {
    expect(SALES_STAGES).toHaveLength(11);
    expect(SALES_STAGES[0].id).toBe("new");
    expect(SALES_STAGES.at(-1)!.id).toBe("lost");
  });

  it("STAGE_BY_ID отдаёт заголовок по id", () => {
    expect(STAGE_BY_ID.price_req.title).toBe("Цена запрошена");
    expect(STAGE_BY_ID.won.title).toBe("Успех");
  });

  it("TERMINAL_STAGES — won/lost, но НЕ cond_lost (реанимируемый)", () => {
    expect(TERMINAL_STAGES.has("won")).toBe(true);
    expect(TERMINAL_STAGES.has("lost")).toBe(true);
    expect(TERMINAL_STAGES.has("cond_lost")).toBe(false);
  });
});

describe("PROGRESSION_STAGES (линейный степпер)", () => {
  it("9 стадий: прогрессия без терминалов-отказа, заканчивается won", () => {
    expect(PROGRESSION_STAGES).toHaveLength(9);
    expect(PROGRESSION_STAGES.some((s) => s.id === "cond_lost")).toBe(false);
    expect(PROGRESSION_STAGES.some((s) => s.id === "lost")).toBe(false);
    expect(PROGRESSION_STAGES.at(-1)!.id).toBe("won");
  });
});

describe("progressionIndex", () => {
  it("индекс в прогрессии: new=0, won=8 (последняя)", () => {
    expect(progressionIndex("new")).toBe(0);
    expect(progressionIndex("won")).toBe(8);
  });

  it("−1 для терминалов-отказа и неизвестной стадии (степпер без активного узла)", () => {
    expect(progressionIndex("cond_lost")).toBe(-1);
    expect(progressionIndex("lost")).toBe(-1);
    expect(progressionIndex("какая-то")).toBe(-1);
  });
});

describe("NEXT_STEP_TEMPLATES (слайс 4, «след. шаг в 2 клика»)", () => {
  it("у каждой открытой стадии канона (все, кроме won/lost) есть 3-4 пресета", () => {
    for (const s of SALES_STAGES) {
      if (s.id === "won" || s.id === "lost") continue;
      const presets = NEXT_STEP_TEMPLATES[s.id];
      expect(presets, `стадия ${s.id} без пресетов`).toBeDefined();
      expect(presets.length).toBeGreaterThanOrEqual(3);
      expect(presets.length).toBeLessThanOrEqual(4);
      for (const p of presets) {
        expect(p.label.length).toBeGreaterThan(0);
        expect(p.offsetDays).toBeGreaterThanOrEqual(0);
      }
    }
  });

  it("won/lost — намеренно без пресетов (сделка закрыта)", () => {
    expect(NEXT_STEP_TEMPLATES.won).toBeUndefined();
    expect(NEXT_STEP_TEMPLATES.lost).toBeUndefined();
  });

  it("cond_lost — реанимационные пресеты (более длинный срок)", () => {
    expect(NEXT_STEP_TEMPLATES.cond_lost.every((p) => p.offsetDays >= 5)).toBe(true);
  });
});

describe("nextStepTemplatesFor / nextStepPreset", () => {
  it("отдаёт пресеты стадии канона как есть", () => {
    expect(nextStepTemplatesFor("qual")).toBe(NEXT_STEP_TEMPLATES.qual);
  });

  it("неизвестная/не заданная стадия — DEFAULT_NEXT_STEP_TEMPLATES", () => {
    expect(nextStepTemplatesFor("рп_какая-то")).toBe(DEFAULT_NEXT_STEP_TEMPLATES);
    expect(nextStepTemplatesFor(undefined)).toBe(DEFAULT_NEXT_STEP_TEMPLATES);
  });

  it("nextStepPreset — первый пресет стадии (дефолт для авто-назначения)", () => {
    expect(nextStepPreset("qual")).toEqual(NEXT_STEP_TEMPLATES.qual[0]);
    expect(nextStepPreset("unknown")).toEqual(DEFAULT_NEXT_STEP_TEMPLATES[0]);
  });
});

describe("presetDateISO (слайс 4) — детерминированная локальная дата пресета", () => {
  // Локальное время (не UTC) — симметрично остальным датам канона (board.test.ts).
  const NOW = new Date(2026, 5, 11, 15, 30, 0).getTime(); // 11.06.2026 15:30

  it("offsetDays=0 — сегодняшняя дата, время фиксировано 09:00:00", () => {
    expect(presetDateISO(0, NOW)).toBe("2026-06-11T09:00:00");
  });

  it("offsetDays=1/14 — сдвигает дату вперёд, время не меняется", () => {
    expect(presetDateISO(1, NOW)).toBe("2026-06-12T09:00:00");
    expect(presetDateISO(14, NOW)).toBe("2026-06-25T09:00:00");
  });

  it("корректно переносит через границу месяца/года", () => {
    const endOfYear = new Date(2026, 11, 30, 8, 0, 0).getTime(); // 30.12.2026
    expect(presetDateISO(3, endOfYear)).toBe("2027-01-02T09:00:00");
  });

  it("не зависит от часа/минуты в `now` — только календарная дата", () => {
    const morning = new Date(2026, 5, 11, 0, 1, 0).getTime();
    const night = new Date(2026, 5, 11, 23, 59, 0).getTime();
    expect(presetDateISO(0, morning)).toBe(presetDateISO(0, night));
  });
});

describe("MESSAGE_TEMPLATES (слайс 8, «касания клиента с доски»)", () => {
  it("у каждой открытой стадии канона (все, кроме won/lost) есть 2-3 шаблона", () => {
    for (const s of SALES_STAGES) {
      if (s.id === "won" || s.id === "lost") continue;
      const templates = MESSAGE_TEMPLATES[s.id];
      expect(templates, `стадия ${s.id} без шаблонов сообщений`).toBeDefined();
      expect(templates.length).toBeGreaterThanOrEqual(2);
      expect(templates.length).toBeLessThanOrEqual(3);
      for (const t of templates) {
        expect(t.label.length).toBeGreaterThan(0);
        expect(t.text.length).toBeGreaterThan(0);
      }
    }
  });

  it("won/lost — намеренно без шаблонов (сделка закрыта, писать нечего)", () => {
    expect(MESSAGE_TEMPLATES.won).toBeUndefined();
    expect(MESSAGE_TEMPLATES.lost).toBeUndefined();
  });

  it("has_price — есть шаблон «Напомнить о КП»", () => {
    expect(MESSAGE_TEMPLATES.has_price.some((t) => t.label === "Напомнить о КП")).toBe(true);
  });

  it("invoice — есть шаблон напоминания об оплате", () => {
    expect(MESSAGE_TEMPLATES.invoice.some((t) => t.label.includes("оплат"))).toBe(true);
  });

  it("cond_lost — реанимационные шаблоны (сделка не терминальна)", () => {
    expect(MESSAGE_TEMPLATES.cond_lost.some((t) => t.label.includes("улучшенным"))).toBe(true);
  });
});

describe("messageTemplatesFor", () => {
  it("отдаёт шаблоны стадии канона как есть", () => {
    expect(messageTemplatesFor("has_price")).toBe(MESSAGE_TEMPLATES.has_price);
  });

  it("неизвестная/не заданная стадия — DEFAULT_MESSAGE_TEMPLATES", () => {
    expect(messageTemplatesFor("рп_какая-то")).toBe(DEFAULT_MESSAGE_TEMPLATES);
    expect(messageTemplatesFor(undefined)).toBe(DEFAULT_MESSAGE_TEMPLATES);
  });
});
