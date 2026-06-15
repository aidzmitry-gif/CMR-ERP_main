import { describe, expect, it } from "vitest";

import { formatAuditDate } from "./spravochniki-card";

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
