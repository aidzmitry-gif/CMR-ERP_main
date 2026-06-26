import { describe, expect, it } from "vitest";

import { COMPANIES, formatInBase } from "@/lib/currency";

describe("COMPANIES", () => {
  it("3 юр-лица by/ru/pl со своими базовыми валютами", () => {
    expect(COMPANIES.map((c) => c.id)).toEqual(["by", "ru", "pl"]);
    expect(COMPANIES.find((c) => c.id === "by")!.base).toBe("BYN");
    expect(COMPANIES.find((c) => c.id === "ru")!.base).toBe("RUB");
    expect(COMPANIES.find((c) => c.id === "pl")!.base).toBe("EUR");
  });
});

// Intl.NumberFormat("ru-RU") разделяет тысячи неразрывным пробелом (U+00A0/U+202F);
// \s в JS включает их — нормализуем все пробелы к обычному для стабильного сравнения.
const norm = (s: string) => s.replace(/\s/g, " ");

describe("formatInBase (BYN → базовая валюта ЮЛ)", () => {
  it("BYN — без пересчёта, подпись Br", () => {
    expect(norm(formatInBase(19_300_000, "BYN"))).toBe("19 300 000 Br");
  });

  it("EUR — делит на курс 3.55, подпись €", () => {
    // 355 BYN / 3.55 = 100 EUR
    expect(norm(formatInBase(355, "EUR"))).toBe("100 €");
  });

  it("RUB — делит на 0.037, подпись ₽", () => {
    // 37 BYN / 0.037 = 1000 RUB
    expect(norm(formatInBase(37, "RUB"))).toBe("1 000 ₽");
  });

  it("неизвестная валюта — без пересчёта, код как подпись", () => {
    expect(norm(formatInBase(1000, "XXX"))).toBe("1 000 XXX");
  });
});
