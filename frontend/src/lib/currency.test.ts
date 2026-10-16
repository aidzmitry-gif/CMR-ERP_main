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
    expect(norm(formatInBase(355, "EUR", 3.55))).toBe("100 €");
  });

  it("RUB — делит на 0.037, подпись ₽", () => {
    // 37 BYN / 0.037 = 1000 RUB
    expect(norm(formatInBase(37, "RUB", 0.037))).toBe("1 000 ₽");
  });

  it("неизвестная валюта — без пересчёта, код как подпись", () => {
    expect(norm(formatInBase(1000, "XXX"))).toBe("Курс недоступен");
  });
});

it("сохраняет копейки согласованной цены и округляет валютный пересчёт до копеек", () => {
  expect(norm(formatInBase(125.50, "BYN"))).toBe("125,5 Br");
  expect(norm(formatInBase(100.50, "BYN"))).toBe("100,5 Br");
  expect(norm(formatInBase(0.01, "BYN"))).toBe("0,01 Br");
  expect(norm(formatInBase(0, "BYN"))).toBe("0 Br");
  expect(norm(formatInBase(1, "EUR", 3))).toBe("0,33 €");
});
