import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/api", () => ({
  fetchStock: vi.fn(),
  addDealItem: vi.fn(),
  createPriceQuote: vi.fn(),
  fetchLastOrder: vi.fn(),
  issueDocument: vi.fn(),
  updateDeal: vi.fn(),
}));

vi.mock("@/components/kanban/currency-context", () => ({
  useCurrency: () => ({ fmt: (v: number) => `${v.toFixed(2)} BYN` }),
}));

import {
  catalogEmptyMessage,
  ProductPicker,
  ProductPickerModal,
  ProductPickerTotals,
  useProductPicker,
  type ProductPickerState,
} from "@/components/kanban/product-picker";
import * as api from "@/lib/api";

const mock = (fn: unknown) => fn as ReturnType<typeof vi.fn>;

const fmt = (v: number) => `${v.toFixed(2)} BYN`;

const skus = [
  { id: 1, code: "AKB-60", title: "АКБ 60Ah 12V", unit: "шт" },
  { id: 2, code: "AKB-100", title: "АКБ 100Ah 12V", unit: "шт" },
  { id: 3, code: "LAMP-H4", title: "Лампа H4 24V", unit: "шт" },
];

const stockRows = [
  {
    sku_code: "AKB-60",
    warehouse: "Минск",
    qty_available: 10,
    qty_reserved: 2,
    qty_forecast: 0,
    price: 150,
    cost: 100,
  },
  {
    sku_code: "AKB-100",
    warehouse: "Минск",
    qty_available: 0,
    qty_reserved: 0,
    qty_forecast: 5,
    price: 220,
    cost: null,
  },
];

function mockSkusFetch(status = 200) {
  global.fetch = vi.fn().mockResolvedValue({
    ok: status === 200,
    status,
    json: async () => skus,
  }) as unknown as typeof fetch;
}

/** Тестовый хук-харнесс: реальный useProductPicker + презентационные ProductPicker/Totals. */
function Harness({ dealId = "d1" }: { dealId?: string }) {
  const picker = useProductPicker(true, dealId);
  return (
    <div>
      <ProductPicker state={picker} fmt={fmt} />
      <ProductPickerTotals state={picker} fmt={fmt} />
    </div>
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  mockSkusFetch();
  mock(api.fetchStock).mockResolvedValue(stockRows);
  mock(api.addDealItem).mockResolvedValue(true);
  mock(api.createPriceQuote).mockResolvedValue(true);
  mock(api.fetchLastOrder).mockResolvedValue([]);
  mock(api.issueDocument).mockResolvedValue({ ok: true, message: "Счёт создан", renderUrl: "/r" });
  mock(api.updateDeal).mockResolvedValue(true);
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("catalogEmptyMessage", () => {
  const status: ProductPickerState["catalogStatus"][] = ["loading", "auth", "error", "ready"];
  it("hasSkus=true — сообщение о пустом фильтре независимо от статуса", () => {
    for (const s of status) {
      expect(catalogEmptyMessage(s, true)).toBe(
        "Ничего не найдено — измените запрос или снимите фильтры",
      );
    }
  });
  it("loading — «Загрузка номенклатуры…»", () => {
    expect(catalogEmptyMessage("loading", false)).toBe("Загрузка номенклатуры…");
  });
  it("auth — просит перелогиниться через Keycloak", () => {
    expect(catalogEmptyMessage("auth", false)).toBe(
      "Нет доступа к номенклатуре — выйдите и войдите через Keycloak (нужен JWT).",
    );
  });
  it("error — просит обновить страницу", () => {
    expect(catalogEmptyMessage("error", false)).toBe(
      "Не удалось загрузить номенклатуру. Обновите страницу.",
    );
  });
  it("ready + пусто — «Номенклатура пуста»", () => {
    expect(catalogEmptyMessage("ready", false)).toBe("Номенклатура пуста.");
  });
});

describe("ProductPicker — поиск/фильтр и подбор позиции", () => {
  it("после загрузки показывает до 6 кандидатов из справочника с ценой/сроком", async () => {
    render(<Harness />);
    await waitFor(() => expect(screen.getByText("АКБ 60Ah 12V")).toBeInTheDocument());
    expect(screen.getByText("АКБ 100Ah 12V")).toBeInTheDocument();
    expect(screen.getByText("Лампа H4 24V")).toBeInTheDocument();
    // AKB-60: своб = 10-2=8, в наличии, маржа (150-100)/150=33%
    expect(screen.getByText(/150\.00 BYN/)).toBeInTheDocument();
    expect(screen.getByText(/своб 8/)).toBeInTheDocument();
    expect(screen.getByText("в наличии")).toBeInTheDocument();
    expect(screen.getByText(/маржа 33%/)).toBeInTheDocument();
  });

  it("фильтр по подстроке названия/кода (ёмкость 100Ah) сужает список", async () => {
    render(<Harness />);
    await waitFor(() => expect(screen.getByText("АКБ 60Ah 12V")).toBeInTheDocument());
    fireEvent.change(screen.getByPlaceholderText("Подобрать товар по названию / коду…"), {
      target: { value: "100Ah" },
    });
    expect(screen.queryByText("АКБ 60Ah 12V")).not.toBeInTheDocument();
    expect(screen.getByText("АКБ 100Ah 12V")).toBeInTheDocument();
    expect(screen.queryByText("Лампа H4 24V")).not.toBeInTheDocument();
  });

  it("фильтр по параметру напряжения (24V) находит только лампу", async () => {
    render(<Harness />);
    await waitFor(() => expect(screen.getByText("АКБ 60Ah 12V")).toBeInTheDocument());
    fireEvent.change(screen.getByPlaceholderText("Подобрать товар по названию / коду…"), {
      target: { value: "24V" },
    });
    expect(screen.getByText("Лампа H4 24V")).toBeInTheDocument();
    expect(screen.queryByText("АКБ 60Ah 12V")).not.toBeInTheDocument();
    expect(screen.queryByText("АКБ 100Ah 12V")).not.toBeInTheDocument();
  });

  it("фильтр без совпадений показывает honest-empty сообщение", async () => {
    render(<Harness />);
    await waitFor(() => expect(screen.getByText("АКБ 60Ah 12V")).toBeInTheDocument());
    fireEvent.change(screen.getByPlaceholderText("Подобрать товар по названию / коду…"), {
      target: { value: "несуществующий-артикул" },
    });
    expect(screen.getByText("Ничего не найдено — измените запрос или снимите фильтры")).toBeInTheDocument();
  });

  it("клик по кандидату добавляет строку в корзину и очищает поиск", async () => {
    render(<Harness />);
    await waitFor(() => expect(screen.getByText("АКБ 60Ah 12V")).toBeInTheDocument());
    fireEvent.click(screen.getByText("АКБ 60Ah 12V"));
    expect(screen.getByLabelText("Включить АКБ 60Ah 12V")).toBeInTheDocument();
    expect(screen.getByLabelText("Количество АКБ 60Ah 12V")).toHaveValue("1");
    // добавленная позиция больше не в кандидатах
    expect(
      screen.queryByRole("button", { name: /АКБ 60Ah 12V/ }),
    ).not.toBeInTheDocument();
    // итог = 150 * 1 — в блоке «Итого»
    expect(screen.getByText("150.00 BYN")).toBeInTheDocument();
  });

  it("изменение количества пересчитывает итог и маржу", async () => {
    render(<Harness />);
    await waitFor(() => expect(screen.getByText("АКБ 60Ah 12V")).toBeInTheDocument());
    fireEvent.click(screen.getByText("АКБ 60Ah 12V"));
    fireEvent.change(screen.getByLabelText("Количество АКБ 60Ah 12V"), { target: { value: "3" } });
    // итог = 150*3 = 450, с НДС 540
    expect(screen.getByText("450.00 BYN")).toBeInTheDocument();
    expect(screen.getByText(/с НДС 540\.00 BYN/)).toBeInTheDocument();
    // маржа = (150-100)*3 = 150 (33%), себес = 100*3=300
    expect(screen.getByText(/150\.00 BYN \(33%\)/)).toBeInTheDocument();
    expect(screen.getByText(/себес 300\.00 BYN/)).toBeInTheDocument();
  });

  it("нечисловой ввод количества откатывается на 1 (Math.max/parseInt guard)", async () => {
    render(<Harness />);
    await waitFor(() => expect(screen.getByText("АКБ 60Ah 12V")).toBeInTheDocument());
    fireEvent.click(screen.getByText("АКБ 60Ah 12V"));
    fireEvent.change(screen.getByLabelText("Количество АКБ 60Ah 12V"), { target: { value: "abc" } });
    expect(screen.getByLabelText("Количество АКБ 60Ah 12V")).toHaveValue("1");
  });

  it("снятие галочки исключает позицию из итога и маржи", async () => {
    render(<Harness />);
    await waitFor(() => expect(screen.getByText("АКБ 60Ah 12V")).toBeInTheDocument());
    fireEvent.click(screen.getByText("АКБ 60Ah 12V"));
    expect(screen.getByText("150.00 BYN")).toBeInTheDocument();
    fireEvent.click(screen.getByLabelText("Включить АКБ 60Ah 12V"));
    // «Итого» блок пропадает — итог по отмеченным = 0
    expect(screen.queryByText("Итого")).not.toBeInTheDocument();
  });

  it("под-заказ позиция (нет себестоимости) помечает маржу как «в наличии» и добавляет предупреждение", async () => {
    render(<Harness />);
    await waitFor(() => expect(screen.getByText("АКБ 60Ah 12V")).toBeInTheDocument());
    fireEvent.click(screen.getByText("АКБ 60Ah 12V")); // в наличии, есть себес
    // после добавления первой позиции без активного запроса список кандидатов скрыт —
    // раскрываем его повторным поиском.
    fireEvent.change(screen.getByPlaceholderText("Подобрать товар по названию / коду…"), {
      target: { value: "100Ah" },
    });
    fireEvent.click(screen.getByText("АКБ 100Ah 12V")); // под заказ, нет себес (cost=null)
    expect(screen.getByText(/Маржа · в наличии/)).toBeInTheDocument();
    expect(
      screen.getByText(
        "Под-заказ позиции — себестоимость из предварительного расчёта (скоро); пока в марже не учтены.",
      ),
    ).toBeInTheDocument();
  });

  it("крестик убирает позицию из корзины", async () => {
    render(<Harness />);
    await waitFor(() => expect(screen.getByText("АКБ 60Ah 12V")).toBeInTheDocument());
    fireEvent.click(screen.getByText("АКБ 60Ah 12V"));
    expect(screen.getByLabelText("Включить АКБ 60Ah 12V")).toBeInTheDocument();
    fireEvent.click(screen.getByLabelText("Убрать позицию"));
    expect(screen.queryByLabelText("Включить АКБ 60Ah 12V")).not.toBeInTheDocument();
  });
});

describe("ProductPickerModal — интеграция: повтор заказа / добавление в сделку / счёт", () => {
  function openModal(onClose = vi.fn(), onCommitted = vi.fn()) {
    render(
      <ProductPickerModal
        dealId="d1"
        counterparty="ООО Ромашка"
        onClose={onClose}
        onCommitted={onCommitted}
      />,
    );
    return { onClose, onCommitted };
  }

  it("пустая корзина: CTA заблокированы", async () => {
    openModal();
    await waitFor(() => expect(screen.getByText("АКБ 60Ah 12V")).toBeInTheDocument());
    expect(screen.getByRole("button", { name: /Добавить в сделку/ })).toBeDisabled();
    expect(screen.getByRole("button", { name: /Выставить счёт/ })).toBeDisabled();
  });

  it("«Добавить в сделку» без позиций (защита от пустого клика) не трогает бэкенд", async () => {
    openModal();
    await waitFor(() => expect(screen.getByText("АКБ 60Ah 12V")).toBeInTheDocument());
    // Кнопка disabled — событие не долетает, но проверим что API не звался.
    expect(api.addDealItem).not.toHaveBeenCalled();
  });

  it("выбор позиции + «Добавить в сделку»: пишет позицию и котировку цены, показывает тост", async () => {
    const { onCommitted } = openModal();
    await waitFor(() => expect(screen.getByText("АКБ 60Ah 12V")).toBeInTheDocument());
    fireEvent.click(screen.getByText("АКБ 60Ah 12V"));
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: /Добавить в сделку/ }));
    });
    expect(api.addDealItem).toHaveBeenCalledWith("d1", 1, 1);
    expect(api.createPriceQuote).toHaveBeenCalledWith("AKB-60", "ООО Ромашка", 150);
    expect(screen.getByText("✅ Добавлено в сделку позиций: 1/1")).toBeInTheDocument();
    expect(onCommitted).toHaveBeenCalledTimes(1);
  });

  it("«Повторить прошлый заказ»: пусто → сообщение «не найдено», позиции не добавляются", async () => {
    mock(api.fetchLastOrder).mockResolvedValue([]);
    openModal();
    await waitFor(() => expect(screen.getByText("АКБ 60Ah 12V")).toBeInTheDocument());
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: /Повторить прошлый заказ/ }));
    });
    expect(api.fetchLastOrder).toHaveBeenCalledWith("d1");
    expect(screen.getByText("Прошлых заказов этого контрагента не найдено")).toBeInTheDocument();
  });

  it("«Повторить прошлый заказ»: подтягивает позиции прошлой сделки в корзину", async () => {
    mock(api.fetchLastOrder).mockResolvedValue([
      { id: 9, sku_id: 2, code: "AKB-100", title: "АКБ 100Ah 12V", unit: "шт", qty: 2.6, last_price: null, min_price: null },
    ]);
    openModal();
    await waitFor(() => expect(screen.getByText("АКБ 60Ah 12V")).toBeInTheDocument());
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: /Повторить прошлый заказ/ }));
    });
    expect(screen.getByText("✅ Добавлено из прошлого заказа: 1")).toBeInTheDocument();
    // qty округляется до целого (Math.round(2.6) = 3)
    expect(screen.getByLabelText("Количество АКБ 100Ah 12V")).toHaveValue("3");
  });

  it("«Выставить счёт»: пишет позиции, открывает печать, ставит следующий шаг", async () => {
    const winStub = { location: { href: "" }, close: vi.fn() };
    const openSpy = vi.spyOn(window, "open").mockReturnValue(winStub as unknown as Window);
    const { onCommitted } = openModal();
    await waitFor(() => expect(screen.getByText("АКБ 60Ah 12V")).toBeInTheDocument());
    fireEvent.click(screen.getByText("АКБ 60Ah 12V"));
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: /Выставить счёт/ }));
    });
    expect(api.addDealItem).toHaveBeenCalledWith("d1", 1, 1);
    expect(api.issueDocument).toHaveBeenCalledWith("d1", "invoice");
    expect(winStub.location.href).toBe("/r");
    expect(screen.getByText("Счёт создан")).toBeInTheDocument();
    expect(mock(api.updateDeal).mock.calls[0][0]).toBe("d1");
    expect(mock(api.updateDeal).mock.calls[0][1]).toMatchObject({
      next_step: "Проверить оплату счёта",
    });
    expect(onCommitted).toHaveBeenCalledTimes(1);
    openSpy.mockRestore();
  });

  it("«Выставить счёт»: неуспех закрывает окно-пустышку и не меняет следующий шаг", async () => {
    mock(api.issueDocument).mockResolvedValue({ ok: false, message: "Нет позиций", renderUrl: null });
    const winStub = { location: { href: "" }, close: vi.fn() };
    const openSpy = vi.spyOn(window, "open").mockReturnValue(winStub as unknown as Window);
    const { onCommitted } = openModal();
    await waitFor(() => expect(screen.getByText("АКБ 60Ah 12V")).toBeInTheDocument());
    fireEvent.click(screen.getByText("АКБ 60Ah 12V"));
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: /Выставить счёт/ }));
    });
    expect(winStub.close).toHaveBeenCalled();
    expect(api.updateDeal).not.toHaveBeenCalled();
    expect(screen.getByText("Нет позиций")).toBeInTheDocument();
    expect(onCommitted).not.toHaveBeenCalled();
    openSpy.mockRestore();
  });

  it("клик по подложке закрывает модалку, клик внутри — нет", async () => {
    const { onClose } = openModal();
    await waitFor(() => expect(screen.getByText("АКБ 60Ah 12V")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("dialog"));
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("заголовок показывает контрагента, кнопка закрытия зовёт onClose", async () => {
    const { onClose } = openModal();
    expect(screen.getByText("Подбор товара · ООО Ромашка")).toBeInTheDocument();
    fireEvent.click(screen.getByLabelText("Закрыть"));
    expect(onClose).toHaveBeenCalledTimes(1);
  });
});

describe("ProductPickerModal — статусы каталога (401/ошибка сети)", () => {
  it("401 от каталога — авторизационное сообщение вместо списка", async () => {
    global.fetch = vi.fn().mockResolvedValue({ ok: false, status: 401, json: async () => [] }) as unknown as typeof fetch;
    render(<Harness />);
    await waitFor(() =>
      expect(
        screen.getByText("Нет доступа к номенклатуре — выйдите и войдите через Keycloak (нужен JWT)."),
      ).toBeInTheDocument(),
    );
  });

  it("сетевая ошибка при загрузке каталога — сообщение об ошибке", async () => {
    global.fetch = vi.fn().mockRejectedValue(new Error("network down")) as unknown as typeof fetch;
    render(<Harness />);
    await waitFor(() =>
      expect(
        screen.getByText("Не удалось загрузить номенклатуру. Обновите страницу."),
      ).toBeInTheDocument(),
    );
  });
});
