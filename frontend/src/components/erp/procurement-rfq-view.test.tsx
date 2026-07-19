import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

// API домена RFQ — мок только сетевых функций; statusLabel/bestBidId/типы оставляем
// настоящими (чистая логика без I/O — пусть считает по-настоящему).
vi.mock("@/lib/procurement-rfq", async () => {
  const actual = await vi.importActual<typeof import("@/lib/procurement-rfq")>(
    "@/lib/procurement-rfq",
  );
  return {
    ...actual,
    fetchRfqs: vi.fn(),
    createRfq: vi.fn(),
    addBid: vi.fn(),
    awardRfq: vi.fn(),
  };
});

import { ProcurementRfqView } from "@/components/erp/procurement-rfq-view";
import * as pr from "@/lib/procurement-rfq";
import type { Rfq } from "@/lib/procurement-rfq";

const rfqOpen: Rfq = {
  id: 1,
  item: "Сталь листовая",
  sku_code: "СТ-3",
  qty: 100,
  request_id: null,
  status: "open",
  due_date: null,
  best_bid_id: 20,
  bids: [
    { id: 10, rfq_id: 1, supplier_id: 5, price_byn: 250, lead_time_days: 30, incoterms: "FOB", note: "", is_winner: false },
    { id: 20, rfq_id: 1, supplier_id: 7, price_byn: 180, lead_time_days: 45, incoterms: "CIF", note: "", is_winner: false },
  ],
};

const rfqAwarded: Rfq = {
  id: 2,
  item: "Провод медный",
  sku_code: "",
  qty: 50,
  request_id: null,
  status: "awarded",
  due_date: null,
  best_bid_id: 30,
  bids: [
    { id: 30, rfq_id: 2, supplier_id: 9, price_byn: 500, lead_time_days: 20, incoterms: "DAP", note: "", is_winner: true },
  ],
};

const newRfq: Rfq = {
  id: 3,
  item: "Кабель ВВГ",
  sku_code: "",
  qty: 0,
  request_id: null,
  status: "open",
  due_date: null,
  best_bid_id: null,
  bids: [],
};

const mock = (fn: unknown) => fn as ReturnType<typeof vi.fn>;

beforeEach(() => {
  vi.clearAllMocks();
  // по умолчанию поллинг на маунте возвращает null → SSR-данные не затираются.
  mock(pr.fetchRfqs).mockResolvedValue(null);
});

describe("ProcurementRfqView", () => {
  it("рендерит список запросов, счётчики предложений и по умолчанию открывает первый", () => {
    render(<ProcurementRfqView initial={[rfqOpen, rfqAwarded]} />);
    // оба запроса в списке слева
    expect(screen.getAllByText("Сталь листовая").length).toBeGreaterThan(0);
    expect(screen.getByText("Провод медный")).toBeInTheDocument();
    // счётчики предложений на карточках списка
    expect(screen.getByText("2 пред.")).toBeInTheDocument();
    expect(screen.getByText("1 пред.")).toBeInTheDocument();
    // первый выбран по умолчанию → его статус-бейдж в правой карточке
    expect(screen.getByText("Открыт")).toBeInTheDocument();
  });

  it("пустой список показывает «Запросов нет» и подсказку выбрать запрос", () => {
    render(<ProcurementRfqView initial={[]} />);
    expect(screen.getByText("Запросов нет")).toBeInTheDocument();
    expect(screen.getByText("Выберите запрос слева")).toBeInTheDocument();
  });

  it("клик по другому запросу в списке открывает его карточку", async () => {
    render(<ProcurementRfqView initial={[rfqOpen, rfqAwarded]} />);
    // до клика открыт первый (open) — метки завершённого тендера ещё нет
    expect(screen.queryByText("Победитель выбран")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /Провод медный/ }));

    expect(await screen.findByText("Победитель выбран")).toBeInTheDocument();
  });

  it("лучшее предложение подсвечено «лучшая», цена и поставщик видны", () => {
    render(<ProcurementRfqView initial={[rfqOpen]} />);
    // best_bid_id=20 (цена 180) → метка «лучшая»
    expect(screen.getByText("лучшая")).toBeInTheDocument();
    expect(screen.getByText("180")).toBeInTheDocument();
    expect(screen.getByText("#7")).toBeInTheDocument();
    expect(screen.getByText("#5")).toBeInTheDocument();
  });

  it("победитель отмечен «победитель», а форма и «Выбрать» скрыты у завершённого тендера", () => {
    render(<ProcurementRfqView initial={[rfqAwarded]} />);
    expect(screen.getByText("победитель")).toBeInTheDocument();
    // тендер разыгран (status !== open) → нет ни кнопки выбора, ни формы предложения
    expect(screen.queryByRole("button", { name: /Выбрать/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Предложение/ })).not.toBeInTheDocument();
    expect(screen.queryByPlaceholderText("Цена, BYN")).not.toBeInTheDocument();
  });

  it("создание с пустым полем даёт ошибку и не зовёт API", () => {
    render(<ProcurementRfqView initial={[rfqOpen]} />);
    const createRow = screen.getByPlaceholderText("Новый запрос: позиция").closest("div") as HTMLElement;
    fireEvent.click(within(createRow).getByRole("button"));

    expect(screen.getByText("Укажите позицию запроса")).toBeInTheDocument();
    expect(pr.createRfq).not.toHaveBeenCalled();
  });

  it("создание запроса зовёт createRfq и показывает новую карточку после обновления", async () => {
    mock(pr.fetchRfqs).mockResolvedValueOnce(null); // маунт: не трогаем SSR-данные
    mock(pr.createRfq).mockResolvedValue(newRfq);
    mock(pr.fetchRfqs).mockResolvedValueOnce([rfqOpen, newRfq]); // refresh после создания

    render(<ProcurementRfqView initial={[rfqOpen]} />);
    const input = screen.getByPlaceholderText("Новый запрос: позиция");
    fireEvent.change(input, { target: { value: "Кабель ВВГ" } });
    const createRow = input.closest("div") as HTMLElement;
    fireEvent.click(within(createRow).getByRole("button"));

    await waitFor(() => expect(pr.createRfq).toHaveBeenCalledWith({ item: "Кабель ВВГ" }));
    // список пополнился созданным запросом, поле ввода очищено
    expect((await screen.findAllByText("Кабель ВВГ")).length).toBeGreaterThan(0);
    expect((input as HTMLInputElement).value).toBe("");
  });

  it("сбой создания показывает ошибку, а не молчит", async () => {
    mock(pr.createRfq).mockResolvedValue(null); // сетевая ошибка / отказ бэка
    render(<ProcurementRfqView initial={[rfqOpen]} />);
    const input = screen.getByPlaceholderText("Новый запрос: позиция");
    fireEvent.change(input, { target: { value: "Кабель ВВГ" } });
    fireEvent.click(within(input.closest("div") as HTMLElement).getByRole("button"));

    expect(await screen.findByText("Не удалось создать запрос")).toBeInTheDocument();
  });

  it("добавление предложения без цены даёт ошибку и не зовёт addBid", () => {
    render(<ProcurementRfqView initial={[rfqOpen]} />);
    fireEvent.click(screen.getByRole("button", { name: /Предложение/ }));

    expect(screen.getByText("Укажите цену предложения")).toBeInTheDocument();
    expect(pr.addBid).not.toHaveBeenCalled();
  });

  it("добавление предложения парсит числа и зовёт addBid ожидаемыми полями", async () => {
    mock(pr.addBid).mockResolvedValue(rfqOpen);
    render(<ProcurementRfqView initial={[rfqOpen]} />);

    fireEvent.change(screen.getByPlaceholderText("ID поставщика"), { target: { value: "9" } });
    fireEvent.change(screen.getByPlaceholderText("Цена, BYN"), { target: { value: "199" } });
    fireEvent.change(screen.getByPlaceholderText("Срок, дн"), { target: { value: "12" } });
    fireEvent.change(screen.getByPlaceholderText("Incoterms"), { target: { value: "DAP" } });
    fireEvent.click(screen.getByRole("button", { name: /Предложение/ }));

    await waitFor(() =>
      expect(pr.addBid).toHaveBeenCalledWith(1, {
        supplier_id: 9,
        price_byn: 199,
        lead_time_days: 12,
        incoterms: "DAP",
      }),
    );
  });

  it("«Выбрать» зовёт awardRfq с id соответствующего предложения", async () => {
    mock(pr.awardRfq).mockResolvedValue({ ...rfqOpen, status: "awarded" });
    render(<ProcurementRfqView initial={[rfqOpen]} />);

    const awardButtons = screen.getAllByRole("button", { name: /Выбрать/ });
    expect(awardButtons).toHaveLength(2); // по одной на предложение открытого тендера
    fireEvent.click(awardButtons[0]); // первая строка = предложение id=10

    await waitFor(() => expect(pr.awardRfq).toHaveBeenCalledWith(1, 10));
  });

  it("поллинг на маунте подтягивает свежий список поверх SSR-данных", async () => {
    mock(pr.fetchRfqs).mockResolvedValueOnce([rfqOpen, rfqAwarded]);
    render(<ProcurementRfqView initial={[rfqOpen]} />);

    // второй запрос пришёл только из fetchRfqs (в initial его не было)
    expect(await screen.findByText("Провод медный")).toBeInTheDocument();
  });
});
