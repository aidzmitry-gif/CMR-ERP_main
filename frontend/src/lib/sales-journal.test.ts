import { describe, expect, it } from "vitest";

import {
  EMPTY_JOURNAL_FILTERS,
  filterJournal,
  formatDayMonth,
  funnelLabel,
  hasActiveFilters,
  journalStats,
  monthGroups,
  type JournalRow,
} from "@/lib/sales-journal";

const row = (over: Partial<JournalRow> = {}): JournalRow => ({
  deal_id: 1,
  number: "СД-0001",
  title: "Поставка",
  counterparty: "ООО Ромашка",
  owner: "Сидоров К.",
  funnel: "new_clients",
  amount: 1000,
  closed_on: "2026-07-01",
  revenue: 1000,
  gross_profit: 200,
  margin_pct: 20,
  margin_reason: null,
  payment: "paid",
  invoice_number: "СЧ-1",
  shipment: "delivered",
  ...over,
});

describe("filterJournal", () => {
  it("без фильтров возвращает всё как есть", () => {
    const rows = [row({ deal_id: 1 }), row({ deal_id: 2 })];
    expect(filterJournal(rows, EMPTY_JOURNAL_FILTERS)).toHaveLength(2);
  });

  it("фильтрует по периоду closed_on (from/to)", () => {
    const rows = [
      row({ deal_id: 1, closed_on: "2026-06-30" }),
      row({ deal_id: 2, closed_on: "2026-07-05" }),
      row({ deal_id: 3, closed_on: "2026-07-15" }),
    ];
    const result = filterJournal(rows, { ...EMPTY_JOURNAL_FILTERS, from: "2026-07-01", to: "2026-07-10" });
    expect(result.map((r) => r.deal_id)).toEqual([2]);
  });

  it("сделка без даты закрытия не проходит под заданный период", () => {
    const rows = [row({ deal_id: 1, closed_on: null })];
    const result = filterJournal(rows, { ...EMPTY_JOURNAL_FILTERS, from: "2026-07-01" });
    expect(result).toHaveLength(0);
  });

  it("фильтрует по воронке", () => {
    const rows = [
      row({ deal_id: 1, funnel: "new_clients" }),
      row({ deal_id: 2, funnel: "tenders" }),
    ];
    const result = filterJournal(rows, { ...EMPTY_JOURNAL_FILTERS, funnel: "tenders" });
    expect(result.map((r) => r.deal_id)).toEqual([2]);
  });

  it("фильтрует по менеджеру", () => {
    const rows = [
      row({ deal_id: 1, owner: "Сидоров К." }),
      row({ deal_id: 2, owner: "Петрова А." }),
    ];
    const result = filterJournal(rows, { ...EMPTY_JOURNAL_FILTERS, owner: "Петрова А." });
    expect(result.map((r) => r.deal_id)).toEqual([2]);
  });

  it("поиск матчит номер/название/клиента без учёта регистра", () => {
    const rows = [
      row({ deal_id: 1, number: "СД-0042", title: "Насосы", counterparty: "Автопарк" }),
      row({ deal_id: 2, number: "СД-0099", title: "Кабель", counterparty: "Белтранс" }),
    ];
    expect(filterJournal(rows, { ...EMPTY_JOURNAL_FILTERS, q: "насос" }).map((r) => r.deal_id)).toEqual([1]);
    expect(filterJournal(rows, { ...EMPTY_JOURNAL_FILTERS, q: "белтранс" }).map((r) => r.deal_id)).toEqual([2]);
  });

  it("только неоплаченные — оставляет payment !== paid", () => {
    const rows = [
      row({ deal_id: 1, payment: "paid" }),
      row({ deal_id: 2, payment: "invoiced" }),
      row({ deal_id: 3, payment: "none" }),
    ];
    const result = filterJournal(rows, { ...EMPTY_JOURNAL_FILTERS, unpaidOnly: true });
    expect(result.map((r) => r.deal_id)).toEqual([2, 3]);
  });
});

describe("hasActiveFilters", () => {
  it("false для пустых фильтров, true при любом заданном", () => {
    expect(hasActiveFilters(EMPTY_JOURNAL_FILTERS)).toBe(false);
    expect(hasActiveFilters({ ...EMPTY_JOURNAL_FILTERS, q: "  " })).toBe(false);
    expect(hasActiveFilters({ ...EMPTY_JOURNAL_FILTERS, q: "иск" })).toBe(true);
    expect(hasActiveFilters({ ...EMPTY_JOURNAL_FILTERS, unpaidOnly: true })).toBe(true);
  });
});

describe("journalStats", () => {
  it("считает сумму и кол-во по срезу", () => {
    const rows = [row({ deal_id: 1, amount: 100 }), row({ deal_id: 2, amount: 200 })];
    const stats = journalStats(rows);
    expect(stats.count).toBe(2);
    expect(stats.totalAmount).toBe(300);
  });

  it("gross_profit=null не превращается в 0 — влияет только на pricedCount", () => {
    const rows = [
      row({ deal_id: 1, gross_profit: 300 }),
      row({ deal_id: 2, gross_profit: null, margin_reason: "нет landed cost" }),
    ];
    const stats = journalStats(rows);
    expect(stats.totalGross).toBe(300);
    expect(stats.pricedCount).toBe(1);
    expect(stats.count).toBe(2);
  });

  it("если ни одна сделка не оценена — totalGross null, а не 0", () => {
    const rows = [row({ deal_id: 1, gross_profit: null }), row({ deal_id: 2, gross_profit: null })];
    const stats = journalStats(rows);
    expect(stats.totalGross).toBeNull();
    expect(stats.pricedCount).toBe(0);
  });

  it("считает неоплаченные (payment !== paid)", () => {
    const rows = [
      row({ deal_id: 1, payment: "paid" }),
      row({ deal_id: 2, payment: "invoiced" }),
      row({ deal_id: 3, payment: "none" }),
    ];
    expect(journalStats(rows).unpaidCount).toBe(2);
  });
});

describe("monthGroups", () => {
  it("группирует по месяцу закрытия, месяцы по убыванию", () => {
    const rows = [
      row({ deal_id: 1, closed_on: "2026-05-10" }),
      row({ deal_id: 2, closed_on: "2026-07-03" }),
      row({ deal_id: 3, closed_on: "2026-07-20" }),
    ];
    const groups = monthGroups(rows);
    expect(groups.map((g) => g.key)).toEqual(["2026-07", "2026-05"]);
    expect(groups[0].title).toBe("Июль 2026");
    expect(groups[0].rows.map((r) => r.deal_id)).toEqual([3, 2]); // DESC внутри группы
    expect(groups[0].sum).toBe(2000);
  });

  it("строки с closed_on=null не теряются — группа «Без даты» в конце", () => {
    const rows = [
      row({ deal_id: 1, closed_on: "2026-07-03" }),
      row({ deal_id: 2, closed_on: null }),
    ];
    const groups = monthGroups(rows);
    expect(groups.map((g) => g.key)).toEqual(["2026-07", "none"]);
    expect(groups.at(-1)!.title).toBe("Без даты");
    expect(groups.at(-1)!.rows.map((r) => r.deal_id)).toEqual([2]);
  });

  it("пустой список → пустой массив групп", () => {
    expect(monthGroups([])).toEqual([]);
  });
});

describe("formatDayMonth", () => {
  it("форматирует ISO-дату в дд.мм.гггг", () => {
    expect(formatDayMonth("2026-07-11")).toBe("11.07.2026");
  });

  it("null → прочерк", () => {
    expect(formatDayMonth(null)).toBe("—");
  });
});

describe("funnelLabel", () => {
  it("известные коды маппятся на русские названия", () => {
    expect(funnelLabel("new_clients")).toBe("Новые клиенты");
    expect(funnelLabel("repeat_clients")).toBe("Постоянные");
    expect(funnelLabel("tenders")).toBe("Тендеры");
  });

  it("неизвестный код возвращается как есть (фолбэк)", () => {
    expect(funnelLabel("custom_code")).toBe("custom_code");
  });
});
