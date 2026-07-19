import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { SalesJournal } from "@/components/sales/sales-journal";
import type { JournalRow } from "@/lib/sales-journal";

// Компонент тянет журнал глобальным fetch("/api/sales/journal") — маршрутизируем его
// сами (в @/lib/api он не ходит). Чистые хелперы @/lib/sales-journal и @/lib/format
// НЕ мокаем — пусть реально фильтруют/группируют/форматируют деньги.

// Суммы держим < 1000, чтобы ru-RU не вставлял групповой разделитель (nbsp) и
// ассерты по деньгам были устойчивы к ICU-окружению CI.
const paidRow: JournalRow = {
  deal_id: 1,
  number: "CRM-101",
  title: "Партия АКБ",
  counterparty: "ООО Ромашка",
  owner: "Иванов И.И.",
  funnel: "new_clients",
  amount: 500,
  closed_on: "2026-07-11",
  revenue: 500,
  gross_profit: 150,
  margin_pct: 30,
  margin_reason: null,
  payment: "paid",
  invoice_number: null,
  shipment: "delivered",
};

const invoicedRow: JournalRow = {
  deal_id: 2,
  number: "CRM-102",
  title: "Прокат листовой",
  counterparty: "ЗАО Берёза",
  owner: "Петров П.П.",
  funnel: "repeat_clients",
  amount: 300,
  closed_on: "2026-07-05",
  revenue: 300,
  gross_profit: null, // маржа не рассчитана → карточка прибыли покажет «—»
  margin_pct: null,
  margin_reason: "нет себестоимости",
  payment: "invoiced",
  invoice_number: "СЧ-7",
  shipment: "none",
};

// ── настраиваемый ответ fetch ─────────────────────────────────────────────────
let fetchImpl: () => Promise<{ ok: boolean; status?: number; json?: () => Promise<unknown> }>;

function respondWith(rows: JournalRow[]) {
  fetchImpl = () => Promise.resolve({ ok: true, json: () => Promise.resolve(rows) });
}

beforeEach(() => {
  respondWith([paidRow, invoicedRow]);
  global.fetch = vi.fn(() => fetchImpl()) as unknown as typeof fetch;
});

afterEach(() => {
  vi.restoreAllMocks();
});

// дожидается, когда журнал перешёл из «Загрузка…» в готовое состояние
async function renderReady() {
  render(<SalesJournal />);
  await screen.findByText("Реестр свершившихся продаж: сделка попадает сюда в момент «Выиграна».");
  await waitFor(() => expect(screen.queryByText("Загрузка…")).not.toBeInTheDocument());
}

describe("SalesJournal", () => {
  it("показывает «Загрузка…» до ответа бэкенда и уходит с фетчем на /api/sales/journal", () => {
    // fetch «висит» — статус остаётся loading
    fetchImpl = () => new Promise(() => {});
    render(<SalesJournal />);
    expect(screen.getByText("Загрузка…")).toBeInTheDocument();
    expect(global.fetch).toHaveBeenCalledWith("/api/sales/journal", { cache: "no-store" });
  });

  it("при сбое бэкенда показывает сообщение об ошибке, а не пустой журнал", async () => {
    fetchImpl = () => Promise.resolve({ ok: false, status: 500 });
    render(<SalesJournal />);
    expect(await screen.findByText(/Журнал недоступен/)).toBeInTheDocument();
    // скорборд и лента не отрисованы
    expect(screen.queryByText("продаж")).not.toBeInTheDocument();
  });

  it("рендерит строки журнала, группу месяца и скорборд с реальными суммами", async () => {
    await renderReady();

    // строки
    expect(screen.getByText("ООО Ромашка")).toBeInTheDocument();
    expect(screen.getByText("ЗАО Берёза")).toBeInTheDocument();
    expect(screen.getByText("CRM-101")).toBeInTheDocument();

    // обе сделки закрыты в июле 2026 → одна группа с заголовком и счётчиком 2
    expect(screen.getByText("Июль 2026")).toBeInTheDocument();

    // скорборд: 2 продажи, сумма 800 BYN, прибыль 150 BYN по 1 из 2, 1 неоплаченная
    expect(screen.getByText("продаж").parentElement).toHaveTextContent("2");
    expect(screen.getByText(/по 1 из 2 оценённых/)).toBeInTheDocument();
    expect(screen.getByText("неоплаченных").parentElement).toHaveTextContent("1");
    // сумма 500 + 300 = 800 BYN (лейбл «сумма»)
    expect(screen.getByText("сумма").parentElement).toHaveTextContent("800 BYN");
  });

  it("оценённая сделка показывает маржу, неоценённая — прочерк с причиной", async () => {
    await renderReady();
    // маржа-чип оценённой строки: «30% · 150 BYN»
    expect(screen.getByText(/30% · 150 BYN/)).toBeInTheDocument();
    // неоценённая строка (invoicedRow) — прочерк с подсказкой-причиной
    const dash = screen.getByTitle("нет себестоимости");
    expect(dash).toHaveTextContent("—");
    // статус оплаты с номером счёта
    expect(screen.getByText(/счёт выставлен · СЧ-7/)).toBeInTheDocument();
  });

  it("фильтр по менеджеру оставляет только его сделки", async () => {
    await renderReady();
    const [, ownerSelect] = screen.getAllByRole("combobox"); // [0]=воронка, [1]=менеджер
    fireEvent.change(ownerSelect, { target: { value: "Иванов И.И." } });

    expect(screen.getByText("ООО Ромашка")).toBeInTheDocument();
    expect(screen.queryByText("ЗАО Берёза")).not.toBeInTheDocument();
    // скорборд пересчитался: осталась 1 продажа
    expect(screen.getByText("продаж").parentElement).toHaveTextContent("1");
  });

  it("поиск по названию/клиенту сужает ленту", async () => {
    await renderReady();
    fireEvent.change(screen.getByPlaceholderText("номер / название / клиент"), {
      target: { value: "Берёза" },
    });
    expect(screen.getByText("ЗАО Берёза")).toBeInTheDocument();
    expect(screen.queryByText("ООО Ромашка")).not.toBeInTheDocument();
  });

  it("галка «только неоплаченные» прячет оплаченную сделку", async () => {
    await renderReady();
    fireEvent.click(screen.getByRole("checkbox"));
    expect(screen.queryByText("ООО Ромашка")).not.toBeInTheDocument(); // paid — скрыт
    expect(screen.getByText("ЗАО Берёза")).toBeInTheDocument(); // invoiced — остался
  });

  it("быстрый период «7 дн» отсеивает старые сделки → «Ничего не найдено», сброс возвращает", async () => {
    await renderReady();
    // обе сделки закрыты в прошлом (июль 2026) относительно любого «сегодня» прогона —
    // окно последних 7 дней их не захватывает
    fireEvent.click(screen.getByRole("button", { name: "7 дн" }));
    expect(screen.getByText("Ничего не найдено")).toBeInTheDocument();
    expect(screen.queryByText("ООО Ромашка")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Сбросить фильтры" }));
    expect(screen.getByText("ООО Ромашка")).toBeInTheDocument();
  });

  it("пустой журнал показывает подсказку про первую сделку, а не «Ничего не найдено»", async () => {
    respondWith([]);
    render(<SalesJournal />);
    expect(await screen.findByText(/Продаж пока нет/)).toBeInTheDocument();
    expect(screen.queryByText("Ничего не найдено")).not.toBeInTheDocument();
  });

  it("карточка валовой прибыли показывает «—», когда в срезе нет оценённых сделок", async () => {
    respondWith([invoicedRow]); // единственная строка без gross_profit
    render(<SalesJournal />);
    const label = await screen.findByText(/по 0 из 1 оценённых/);
    // родитель-карточка содержит прочерк вместо суммы прибыли
    expect(within(label.parentElement as HTMLElement).getByText("—")).toBeInTheDocument();
  });
});
