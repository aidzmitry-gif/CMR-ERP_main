import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

// I/O-функции reference-data мокаем; чистые хелперы (sortVersionsDesc) — оставляем
// настоящими через importActual, иначе таймлайн/таблица версий сортировались бы моком.
vi.mock("@/lib/reference-data", async (importActual) => ({
  ...(await importActual<typeof import("@/lib/reference-data")>()),
  addRateVersion: vi.fn(),
  currencyRateAsOf: vi.fn(),
}));

import { SpravRates } from "@/components/erp/spravochniki/sprav-rates";
import * as ref from "@/lib/reference-data";
import type { CurrencyRateRow, VatRateRow } from "@/lib/reference-data";

// Даты выбраны относительно «сегодня» так, чтобы versionStatus давал детерминированные
// статусы независимо от дня прогона: архив закрыт в прошлом, текущая с end_date=null,
// план — со стартом в далёком будущем.
const usdRates: CurrencyRateRow[] = [
  { id: 1, currency_code: "USD", rate: 2.5, start_date: "2020-01-01", end_date: "2022-01-01" }, // архив
  { id: 2, currency_code: "USD", rate: 3.1, start_date: "2022-01-01", end_date: null }, // текущая
  { id: 3, currency_code: "USD", rate: 3.5, start_date: "2999-01-01", end_date: null }, // план
];
const eurRates: CurrencyRateRow[] = [
  { id: 10, currency_code: "EUR", rate: 3.4, start_date: "2023-01-01", end_date: null },
];
const currencyRates = [...usdRates, ...eurRates];

const vatRates: VatRateRow[] = [
  { id: 100, code: "НДС20", title: "Стандартная", rate: 20, start_date: "2022-01-01", end_date: null },
  { id: 101, code: "НДС10", title: "Льготная", rate: 10, start_date: "2020-01-01", end_date: "2022-01-01" },
];

function renderRates() {
  return render(<SpravRates initialCurrencyRates={currencyRates} initialVatRates={vatRates} />);
}

beforeEach(() => vi.clearAllMocks());

describe("SpravRates", () => {
  it("рендерит заголовок, вкладки валют + НДС и по умолчанию открывает первую валюту (USD)", () => {
    renderRates();
    expect(screen.getByText("Курсы валют и ставки НДС")).toBeInTheDocument();
    // вкладки собираются из уникальных currency_code + «НДС»
    expect(screen.getByRole("button", { name: /USD → BYN/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /EUR → BYN/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "НДС" })).toBeInTheDocument();
    // активна первая валюта → шапка курса USD и НЕ таблица НДС
    expect(screen.getByRole("heading", { name: "Курс USD → BYN" })).toBeInTheDocument();
    expect(screen.queryByText("Ставки НДС — история по датам")).not.toBeInTheDocument();
  });

  it("таблица версий и таймлайн показывают все версии USD со статусами (Активна/Запланирована)", () => {
    renderRates();
    // 3 версии USD (архив/текущая/план) → счётчик и статусные бейджи
    expect(screen.getByText("3 версий")).toBeInTheDocument();
    expect(screen.getByText("Активна")).toBeInTheDocument();
    expect(screen.getByText("Запланирована")).toBeInTheDocument();
    // текущий курс 3.1 виден (в таблице и таймлайне) — реальное значение из фикстуры
    expect(screen.getAllByText("3.1").length).toBeGreaterThan(0);
  });

  it("переключение на вкладку НДС показывает таблицу ставок и прячет курсовой блок", () => {
    renderRates();
    fireEvent.click(screen.getByRole("button", { name: "НДС" }));
    expect(screen.getByText("Ставки НДС — история по датам")).toBeInTheDocument();
    // ставки с процентом из фикстуры
    expect(screen.getByText("20%")).toBeInTheDocument();
    expect(screen.getByText("10%")).toBeInTheDocument();
    expect(screen.getByText("Стандартная")).toBeInTheDocument();
    // курсовой блок ушёл
    expect(screen.queryByRole("heading", { name: "Курс USD → BYN" })).not.toBeInTheDocument();
  });

  it("переключение на EUR меняет активную валюту (шапка и счётчик версий)", () => {
    renderRates();
    fireEvent.click(screen.getByRole("button", { name: /EUR → BYN/ }));
    expect(screen.getByRole("heading", { name: "Курс EUR → BYN" })).toBeInTheDocument();
    // у EUR одна версия
    expect(screen.getByText("1 версий")).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Курс USD → BYN" })).not.toBeInTheDocument();
  });

  it("кнопка «Добавить версию» заблокирована без данных и активна после ввода курса и даты", () => {
    renderRates();
    const addBtn = screen.getByRole("button", { name: /Добавить версию/ });
    expect(addBtn).toBeDisabled();
    fireEvent.change(screen.getByPlaceholderText("например, 3.27"), { target: { value: "3.27" } });
    // только курс — всё ещё заблокирована (нужна дата)
    expect(addBtn).toBeDisabled();
    const dateInputs = document.querySelectorAll<HTMLInputElement>('input[type="date"]');
    fireEvent.change(dateInputs[0], { target: { value: "2027-01-01" } }); // «Действует с» в карточке добавления
    expect(addBtn).toBeEnabled();
  });

  it("успешное добавление версии зовёт addRateVersion, дописывает строку и пишет успех", async () => {
    (ref.addRateVersion as ReturnType<typeof vi.fn>).mockResolvedValue(true);
    renderRates();
    expect(screen.getByText("3 версий")).toBeInTheDocument();

    fireEvent.change(screen.getByPlaceholderText("например, 3.27"), { target: { value: "3.27" } });
    const dateInputs = document.querySelectorAll<HTMLInputElement>('input[type="date"]');
    fireEvent.change(dateInputs[0], { target: { value: "2027-01-01" } });
    fireEvent.click(screen.getByRole("button", { name: /Добавить версию/ }));

    await waitFor(() =>
      expect(ref.addRateVersion).toHaveBeenCalledWith("currency-rates", {
        currency_code: "USD",
        rate: 3.27,
        start_date: "2027-01-01",
      }),
    );
    // новая версия добавлена в состояние → счётчик 3 → 4, показано сообщение об успехе
    expect(await screen.findByText("Версия добавлена")).toBeInTheDocument();
    expect(screen.getByText("4 версий")).toBeInTheDocument();
  });

  it("сбой бэкенда при добавлении показывает ошибку и НЕ добавляет строку", async () => {
    (ref.addRateVersion as ReturnType<typeof vi.fn>).mockResolvedValue(false);
    renderRates();

    fireEvent.change(screen.getByPlaceholderText("например, 3.27"), { target: { value: "9.99" } });
    const dateInputs = document.querySelectorAll<HTMLInputElement>('input[type="date"]');
    fireEvent.change(dateInputs[0], { target: { value: "2027-05-05" } });
    fireEvent.click(screen.getByRole("button", { name: /Добавить версию/ }));

    await waitFor(() => expect(ref.addRateVersion).toHaveBeenCalled());
    expect(await screen.findByText(/Бэкенд недоступен/)).toBeInTheDocument();
    // строка не появилась — счётчик остался 3
    expect(screen.getByText("3 версий")).toBeInTheDocument();
  });

  it("предпросмотр «на дату» зовёт currencyRateAsOf и показывает найденный курс", async () => {
    (ref.currencyRateAsOf as ReturnType<typeof vi.fn>).mockResolvedValue({
      id: 2,
      currency_code: "USD",
      rate: 3.1,
      start_date: "2022-01-01",
      end_date: null,
    } satisfies CurrencyRateRow);
    renderRates();

    // второй date-инпут принадлежит карточке предпросмотра «Дата документа»
    const dateInputs = document.querySelectorAll<HTMLInputElement>('input[type="date"]');
    fireEvent.change(dateInputs[1], { target: { value: "2023-06-01" } });
    fireEvent.click(screen.getByTitle("Найти курс"));

    await waitFor(() => expect(ref.currencyRateAsOf).toHaveBeenCalledWith("USD", "2023-06-01"));
    const card = await screen.findByText("Документ на эту дату видит курс");
    // «Документ…» — метка внутри emerald-бокса; сам курс лежит в соседнем div → берём родителя
    const box = card.parentElement as HTMLElement;
    expect(within(box).getByText("3.1")).toBeInTheDocument();
    expect(within(box).getByText(/BYN\/USD/)).toBeInTheDocument();
  });

  it("кнопка поиска курса заблокирована без даты и активна после ввода", () => {
    renderRates();
    const searchBtn = screen.getByTitle("Найти курс");
    expect(searchBtn).toBeDisabled();
    const dateInputs = document.querySelectorAll<HTMLInputElement>('input[type="date"]');
    fireEvent.change(dateInputs[1], { target: { value: "2023-06-01" } });
    expect(searchBtn).toBeEnabled();
  });

  it("во время запроса «на дату» показывает индикатор «Запрос…», затем результат", async () => {
    let resolveAsOf!: (v: CurrencyRateRow | null) => void;
    (ref.currencyRateAsOf as ReturnType<typeof vi.fn>).mockReturnValue(
      new Promise<CurrencyRateRow | null>((r) => {
        resolveAsOf = r;
      }),
    );
    renderRates();

    const dateInputs = document.querySelectorAll<HTMLInputElement>('input[type="date"]');
    fireEvent.change(dateInputs[1], { target: { value: "2023-06-01" } });
    fireEvent.click(screen.getByTitle("Найти курс"));

    // пока промис не разрешён — состояние «pending»
    expect(await screen.findByText("Запрос…")).toBeInTheDocument();

    resolveAsOf({ id: 2, currency_code: "USD", rate: 3.1, start_date: "2022-01-01", end_date: null });
    await waitFor(() =>
      expect(screen.getByText("Документ на эту дату видит курс")).toBeInTheDocument(),
    );
    expect(screen.queryByText("Запрос…")).not.toBeInTheDocument();
  });
});
