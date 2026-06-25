import { describe, expect, it } from "vitest";

import {
  formatAuditDate,
  formatTouchTs,
  provenanceCounts,
  sourceMeta,
  syncEntityLabel,
  syncStateMeta,
  touchKindMeta,
} from "./spravochniki-card";

describe("formatAuditDate", () => {
  it("формат backend `str(datetime)` — пробел-разделитель, naive", () => {
    expect(formatAuditDate("2026-06-05 12:34:56.123456")).toBe("05.06.2026");
  });

  it("формат backend с офсетом таймзоны", () => {
    expect(formatAuditDate("2026-01-09 00:00:00.000000+00:00")).toBe("09.01.2026");
  });

  it("ISO-форма с `T` тоже разбирается", () => {
    expect(formatAuditDate("2026-12-31T23:59:59Z")).toBe("31.12.2026");
  });

  it("конец дня в плюсовой таймзоне НЕ сдвигает календарную дату", () => {
    // важно: дата берётся из строки, не из new Date() → нет сдвига дня
    expect(formatAuditDate("2026-12-31 23:30:00")).toBe("31.12.2026");
  });

  it("нераспознанная строка возвращается как есть (не NaN.NaN.NaN)", () => {
    expect(formatAuditDate("")).toBe("");
    expect(formatAuditDate("—")).toBe("—");
  });
});

describe("sourceMeta", () => {
  it("известные источники — подпись и тон", () => {
    expect(sourceMeta("egr").label).toBe("ЕГР");
    expect(sourceMeta("1c").tone).toBe("onec");
    expect(sourceMeta("bitrix").tone).toBe("bitrix");
  });

  it("неизвестный источник → нейтральный (не падает)", () => {
    const m = sourceMeta("xz");
    expect(m.label).toBe("xz");
    expect(m.tone).toBe("manual");
  });
});

describe("provenanceCounts", () => {
  it("считает поля по источникам в порядке убывания доверия", () => {
    const counts = provenanceCounts({
      name: { source: "egr" },
      unp: { source: "egr" },
      phone: { source: "manual" },
      industry: { source: "1c" },
    });
    expect(counts.map((c) => [c.source, c.count])).toEqual([
      ["egr", 2],
      ["manual", 1],
      ["1c", 1],
    ]);
  });

  it("пустое происхождение → пустой список", () => {
    expect(provenanceCounts({})).toEqual([]);
  });

  it("неизвестный источник попадает в хвост, не теряется", () => {
    const counts = provenanceCounts({ a: { source: "egr" }, b: { source: "weird" } });
    expect(counts.map((c) => c.source)).toEqual(["egr", "weird"]);
  });
});

describe("touchKindMeta", () => {
  it("звонок/сделка/сообщение — иконки", () => {
    expect(touchKindMeta("call").icon).toBe("📞");
    expect(touchKindMeta("deal").label).toBe("Сделка");
    expect(touchKindMeta("message").label).toBe("Сообщение");
  });

  it("неизвестный тип → как есть", () => {
    expect(touchKindMeta("task").label).toBe("task");
  });
});

describe("formatTouchTs", () => {
  it("дата + время из ISO с T", () => {
    expect(formatTouchTs("2026-06-24T10:05:00")).toBe("24.06.2026 10:05");
  });

  it("дата + время из backend str(datetime) (пробел-разделитель)", () => {
    expect(formatTouchTs("2026-06-24 10:05:33.1")).toBe("24.06.2026 10:05");
  });

  it("без времени — деградирует до даты", () => {
    expect(formatTouchTs("2026-06-24")).toBe("24.06.2026");
  });
});

describe("syncStateMeta", () => {
  it("известные статусы → подпись и тон", () => {
    expect(syncStateMeta("synced")).toEqual({ label: "выгружено", tone: "ok" });
    expect(syncStateMeta("pending").tone).toBe("wait");
    expect(syncStateMeta("error").tone).toBe("err");
  });

  it("неизвестный статус → как есть, нейтральный тон", () => {
    expect(syncStateMeta("queued")).toEqual({ label: "queued", tone: "wait" });
  });
});

describe("syncEntityLabel", () => {
  it("известные типы переведены", () => {
    expect(syncEntityLabel("counterparty")).toBe("Контрагент");
    expect(syncEntityLabel("sku")).toBe("Номенклатура");
  });

  it("неизвестный тип возвращается как есть", () => {
    expect(syncEntityLabel("invoice")).toBe("invoice");
  });
});
