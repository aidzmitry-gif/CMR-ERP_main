import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { PICKER_COLUMNS_KEY } from "@/lib/catalog-picker-table";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { CatalogPickerModal } from "./catalog-picker-modal";
import { useProductPicker } from "./product-picker";
import * as api from "@/lib/api";

vi.mock("@/lib/api", () => ({
  fetchStock: vi.fn(), addDealItem: vi.fn(), createPriceQuote: vi.fn(),
  fetchLastOrder: vi.fn(), issueDocument: vi.fn(), updateDeal: vi.fn(), requestApproval: vi.fn(),
}));
vi.mock("./currency-context", () => ({
  useCurrency: () => ({ fmt: (price: number) => `${price.toFixed(2)} BYN` }),
}));

const sku = { id: 1, code: "A1", title: "Товар А", unit: "шт" };
const stock = { sku_code: "A1", warehouse: "Основной", qty_available: 10, qty_reserved: 0, qty_forecast: 0, price: 150 };

function Harness({ onClose = vi.fn(), onCommitted = vi.fn() }: { onClose?: () => void; onCommitted?: () => void }) {
  const picker = useProductPicker(true, "d1");
  return <CatalogPickerModal state={picker} dealId="d1" counterparty="Клиент" onClose={onClose} onCommitted={onCommitted} />;
}

beforeEach(() => {
  vi.resetAllMocks();
  const layout = new Map<string, string>();
  vi.stubGlobal("localStorage", { getItem: vi.fn((key: string) => layout.get(key) ?? null), setItem: vi.fn((key: string, value: string) => layout.set(key, value)) });
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true, status: 200, json: async () => [sku] }));
  vi.mocked(api.fetchStock).mockResolvedValue([]);
  vi.mocked(api.addDealItem).mockResolvedValue(true);
  vi.mocked(api.createPriceQuote).mockResolvedValue(true);
  vi.mocked(api.requestApproval).mockResolvedValue(true);
});
afterEach(() => vi.unstubAllGlobals());

describe("CatalogPickerModal — selection stays open", () => {
  it("ignores the second click on the quantity backdrop without closing either dialog", async () => {
    const onClose = vi.fn();
    render(<Harness onClose={onClose} />);
    fireEvent.click(await screen.findByText(sku.title));
    const quantityDialog = screen.getByRole("dialog", { name: `Количество и цена: ${sku.title}` });
    fireEvent.click(quantityDialog.parentElement!);
    expect(quantityDialog).toBeInTheDocument();
    expect(screen.getByRole("dialog", { name: "Подбор товара", exact: true })).toBeInTheDocument();
    expect(onClose).not.toHaveBeenCalled();
    expect(api.addDealItem).not.toHaveBeenCalled();
  });

  it("cancels quantity entry without closing the picker or writing a document", async () => {
    const onClose = vi.fn();
    render(<Harness onClose={onClose} />);
    fireEvent.click(await screen.findByText(sku.title));
    const quantityDialog = screen.getByRole("dialog", { name: `Количество и цена: ${sku.title}` });
    fireEvent.click(within(quantityDialog).getByRole("button", { name: "Отмена" }));
    expect(quantityDialog).not.toBeInTheDocument();
    expect(screen.getByRole("dialog", { name: "Подбор товара", exact: true })).toBeInTheDocument();
    expect(onClose).not.toHaveBeenCalled();
    expect(api.addDealItem).not.toHaveBeenCalled();
  });

  it("keeps two products with quantities/prices in the basket until explicit transfer", async () => {
    const second = { ...sku, id: 2, code: "B2", title: "Товар Б" };
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true, status: 200, json: async () => [sku, second] }));
    const onClose = vi.fn(), onCommitted = vi.fn();
    render(<Harness onClose={onClose} onCommitted={onCommitted} />);
    for (const [item, qty, price] of [[sku, 3, 100], [second, 2, 200]] as const) {
      fireEvent.click(await screen.findByText(item.title));
      fireEvent.change(screen.getByLabelText("Количество товара"), { target: { value: String(qty) } });
      fireEvent.change(screen.getByLabelText("Цена за единицу"), { target: { value: String(price) } });
      fireEvent.click(screen.getByRole("button", { name: "Добавить в подбор", exact: true }));
      expect(screen.getByRole("dialog", { name: "Подбор товара", exact: true })).toBeInTheDocument();
      expect(api.addDealItem).not.toHaveBeenCalled();
      expect(api.createPriceQuote).not.toHaveBeenCalled();
      expect(onClose).not.toHaveBeenCalled();
    }
    expect(screen.getAllByText("700.00 BYN").length).toBeGreaterThan(0);
    expect(onCommitted).not.toHaveBeenCalled();
    await act(async () => { fireEvent.click(screen.getAllByRole("button", { name: "Перенести в документ" })[0]); });
    expect(api.addDealItem).toHaveBeenNthCalledWith(1, "d1", 1, 3, 100);
    expect(api.addDealItem).toHaveBeenNthCalledWith(2, "d1", 2, 2, 200);
    expect(onCommitted).toHaveBeenCalledTimes(1);
  });
});

describe("CatalogPickerModal — compact warehouse table", () => {
  it("reorders prices and quantity with their actual cells and keeps quantity actions working", async () => {
    vi.mocked(api.fetchStock).mockResolvedValue([
      { ...stock, qty_available: 12, qty_reserved: 5, price: 150 },
      { ...stock, warehouse: "Дополнительный", qty_available: 4, qty_reserved: 1, price: 165 },
    ]);
    render(<Harness />);
    await screen.findByText(sku.title);
    fireEvent.click(screen.getByText("Столбцы"));
    for (let i = 0; i < 6; i++) fireEvent.click(screen.getByRole("button", { name: "Выше: Цены" }));
    for (let i = 0; i < 7; i++) fireEvent.click(screen.getByRole("button", { name: "Выше: В подбор" }));
    const table = screen.getByRole("table", { name: "Товары по складам" });
    expect(within(table).getAllByRole("columnheader").map(th => th.textContent)).toEqual(["В подбор", "Цены", "Наименование", "Склад", "Остаток", "Резерв", "Свободно"]);
    const cells = within(within(table).getByTitle(sku.title).closest("tr")!).getAllByRole("cell");
    expect(cells[1]).toHaveTextContent("150.00 BYN165.00 BYN");
    expect(cells[3]).toHaveTextContent("ОсновнойДополнительный");
    expect(cells[4]).toHaveTextContent("124"); expect(cells[5]).toHaveTextContent("51"); expect(cells[6]).toHaveTextContent("73");
    fireEvent.click(within(cells[0]).getByRole("button", { name: "Подобрать" }));
    fireEvent.change(screen.getByLabelText("Количество товара"), { target: { value: "2" } });
    fireEvent.click(screen.getByRole("button", { name: "Добавить в подбор", exact: true }));
    const qtyCell = within(within(table).getByTitle(sku.title).closest("tr")!).getAllByRole("cell")[0];
    fireEvent.click(within(qtyCell).getByRole("button", { name: "+", exact: true }));
    expect(qtyCell).toHaveTextContent("3");
    expect(api.addDealItem).not.toHaveBeenCalled(); expect(api.createPriceQuote).not.toHaveBeenCalled();
  });

  it("accepts a typed pixel width after reorder and restores metadata-only layout on reopen", async () => {
    const first = render(<Harness />);
    await screen.findByText(sku.title);
    fireEvent.click(screen.getByText("Столбцы"));
    fireEvent.click(screen.getByRole("button", { name: "Выше: Цены" }));
    const input = screen.getByLabelText("Ширина в пикселях: Цены");
    fireEvent.change(input, { target: { value: "2" } });
    expect(input).toHaveValue(2);
    fireEvent.change(input, { target: { value: "205" } });
    fireEvent.blur(input);
    expect(screen.getByRole("separator", { name: "Ширина: Цены" })).toHaveAttribute("aria-valuenow", "205");
    const saved = JSON.parse(localStorage.getItem(PICKER_COLUMNS_KEY)!);
    expect(Object.keys(saved)).toEqual(["title", "code", "warehouse", "on", "reserved", "free", "price", "quantity"]);
    for (const entry of Object.values(saved)) expect(Object.keys(entry as object).sort()).toEqual(["order", "visible", "width"]);
    first.unmount(); render(<Harness />);
    const headers = within(screen.getByRole("table")).getAllByRole("columnheader");
    expect(headers.map(th => th.textContent)).toEqual(["Наименование", "Склад", "Остаток", "Резерв", "Цены", "Свободно", "В подбор"]);
    expect(screen.getByRole("separator", { name: "Ширина: Цены" })).toHaveAttribute("aria-valuenow", "205");
  });

  it("hides and reveals optional stock/price columns without changing their chosen order", async () => {
    render(<Harness />); await screen.findByText(sku.title);
    fireEvent.click(screen.getByText("Столбцы"));
    fireEvent.click(screen.getByRole("button", { name: "Выше: Цены" }));
    for (const name of ["Цены", "Остаток"]) fireEvent.click(screen.getByRole("checkbox", { name, exact: true }));
    expect(within(screen.getByRole("table")).queryByRole("columnheader", { name: "Цены" })).not.toBeInTheDocument();
    expect(screen.getByRole("checkbox", { name: "Наименование", exact: true })).toBeDisabled();
    expect(screen.getByRole("checkbox", { name: "В подбор", exact: true })).toBeDisabled();
    for (const name of ["Цены", "Остаток"]) fireEvent.click(screen.getByRole("checkbox", { name, exact: true }));
    expect(within(screen.getByRole("table")).getAllByRole("columnheader").map(th => th.textContent)).toEqual(["Наименование", "Склад", "Остаток", "Резерв", "Цены", "Свободно", "В подбор"]);
  });

  it("resets custom order, width and visibility together", async () => {
    render(<Harness />); await screen.findByText(sku.title);
    fireEvent.click(screen.getByText("Столбцы"));
    fireEvent.click(screen.getByRole("button", { name: "Выше: Цены" }));
    fireEvent.change(screen.getByLabelText("Ширина: Цены", { selector: "input" }), { target: { value: "220" } });
    fireEvent.click(screen.getByLabelText("Код", { exact: true }));
    fireEvent.click(screen.getByRole("button", { name: "Сбросить столбцы" }));
    expect(within(screen.getByRole("table")).getAllByRole("columnheader").map(th => th.textContent)).toEqual(["Наименование", "Склад", "Остаток", "Резерв", "Свободно", "Цены", "В подбор"]);
    expect(screen.getByRole("separator", { name: "Ширина: Цены" })).toHaveAttribute("aria-valuenow", "135");
    expect(screen.getByLabelText("Код", { exact: true })).not.toBeChecked();
  });

  it("keeps manual agreed price outside warehouse price stacks", async () => {
    vi.mocked(api.fetchStock).mockResolvedValue([
      { ...stock, warehouse: "Склад 1", price: 150 }, { ...stock, warehouse: "Склад 1", price: 160 },
      { ...stock, warehouse: "Склад 2", qty_available: 5, price: 170 },
    ]);
    render(<Harness />);
    fireEvent.click(await screen.findByText(sku.title));
    fireEvent.change(screen.getByLabelText("Цена за единицу"), { target: { value: "180" } });
    fireEvent.click(screen.getByRole("button", { name: /Добавить в подбор|Сохранить в подборе/ }));
    const table = screen.getByRole("table", { name: "Товары по складам" });
    const cells = within(within(table).getByTitle(sku.title).closest("tr")!).getAllByRole("cell");
    expect(cells[0]).toHaveTextContent("Цена в подборе: 180.00 BYN");
    expect(cells[5]).not.toHaveTextContent("180");
    expect(cells[5].children).toHaveLength(2);
    expect(cells[5]).toHaveTextContent("150.00 BYN160.00 BYN170.00 BYN");
  });
  it("shows aligned stock, reserve, free and all prices per warehouse", async () => {
    vi.mocked(api.fetchStock).mockResolvedValue([
      { ...stock, qty_available: 12, qty_reserved: 5, price: 150 },
      { ...stock, warehouse: "Дополнительный", qty_available: 4, qty_reserved: 1, price: 165 },
    ]);
    render(<Harness />);
    const table = await screen.findByRole("table", { name: "Товары по складам" });
    await waitFor(() => expect(within(table).getByText("Дополнительный")).toBeInTheDocument());
    const cells = within(within(table).getByText(sku.title).closest("tr")!).getAllByRole("cell");
    expect(cells[1]).toHaveTextContent("ОсновнойДополнительный");
    expect(cells[2]).toHaveTextContent("124");
    expect(cells[3]).toHaveTextContent("51");
    expect(cells[4]).toHaveTextContent("73");
    expect(cells[5]).toHaveTextContent("150.00 BYN165.00 BYN");
  });

  it("shows unknown rather than zero when stock is unavailable", async () => {
    render(<Harness />);
    const table = screen.getByRole("table", { name: "Товары по складам" });
    await within(table).findByText(sku.title);
    const cells = within(within(table).getByText(sku.title).closest("tr")!).getAllByRole("cell");
    for (const cell of cells.slice(1, 6)) expect(cell).toHaveTextContent("—");
  });

  it("keeps long internal code hidden by default, abbreviates display and retains full hover text", async () => {
    const code = `SRC-${"1234567890".repeat(6)}`;
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true, status: 200, json: async () => [{ ...sku, code }] }));
    render(<Harness />);
    await screen.findByText(sku.title);
    expect(screen.queryByTitle(code)).not.toBeInTheDocument();
    fireEvent.click(screen.getByLabelText("Код"));
    expect(screen.getByTitle(code)).toHaveTextContent("SRC-123…567890");
    expect(screen.getByRole("table")).toHaveClass("table-fixed");
  });

  it("resizes by keyboard, persists only layout and restores after reopening", async () => {
    const first = render(<Harness />);
    await screen.findByText(sku.title);
    const expectColumnNames = () => {
      const table = screen.getByRole("table", { name: "Товары по складам" });
      for (const name of ["Наименование", "Склад", "Остаток", "Резерв", "Свободно", "Цены", "В подбор"]) {
        expect(within(table).getByRole("columnheader", { name, exact: true })).toBeInTheDocument();
      }
    };
    expectColumnNames();
    fireEvent.keyDown(screen.getByRole("separator", { name: "Ширина: Наименование" }), { key: "ArrowRight" });
    expect(screen.getByRole("separator", { name: "Ширина: Наименование" })).toHaveAttribute("aria-valuenow", "290");
    expectColumnNames();
    expect(localStorage.setItem).toHaveBeenCalledWith(PICKER_COLUMNS_KEY, expect.not.stringContaining(sku.title));
    first.unmount(); render(<Harness />);
    expect(screen.getByRole("separator", { name: "Ширина: Наименование" })).toHaveAttribute("aria-valuenow", "290");
    expectColumnNames();
    fireEvent.click(screen.getByText("Столбцы"));
    fireEvent.click(screen.getByRole("button", { name: "Сбросить столбцы" }));
    expect(screen.getByRole("separator", { name: "Ширина: Наименование" })).toHaveAttribute("aria-valuenow", "280");
    expectColumnNames();
  });

  it("changes width by drag and stops listening after pointer release", async () => {
    vi.stubGlobal("PointerEvent", MouseEvent);
    render(<Harness />);
    await screen.findByText(sku.title);
    fireEvent.pointerDown(screen.getByRole("separator", { name: "Ширина: Наименование" }), { clientX: 200 });
    fireEvent.pointerMove(window, { clientX: 250 });
    fireEvent.pointerUp(window);
    fireEvent.pointerMove(window, { clientX: 500 });
    expect(screen.getByRole("separator", { name: "Ширина: Наименование" })).toHaveAttribute("aria-valuenow", "330");
  });

  it("paginates a large catalog and resets the page when searching", async () => {
    const skus = Array.from({ length: 101 }, (_, index) => ({ ...sku, id: index + 1, code: `C${index}`, title: `Позиция ${index}` }));
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true, status: 200, json: async () => skus }));
    render(<Harness />);
    await screen.findByText("Позиция 0");
    expect(screen.queryByText("Позиция 100")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Следующие товары" }));
    expect(screen.getByText("Позиция 100")).toBeInTheDocument();
    fireEvent.change(screen.getByPlaceholderText(/Название \/ артикул/), { target: { value: "Позиция 0" } });
    expect(screen.getByTitle("Позиция 0")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Предыдущие товары" })).toBeDisabled();
  });
});

describe("CatalogPickerModal — цена подбора", () => {
  it("независимо редактирует цену и количество двух повторённых строк одного SKU", async () => {
    vi.mocked(api.fetchLastOrder).mockResolvedValue([100, 200].map((unit_price, index) => ({
      id: index + 9, sku_id: sku.id, code: sku.code, title: sku.title, unit: sku.unit,
      qty: index + 1, unit_price, last_price: 700, min_price: 500,
    })));
    render(<Harness />);
    await screen.findByText(sku.title);
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Прошлый заказ" })); });
    fireEvent.click(screen.getAllByTitle("Изменить количество/цену")[0]);
    expect(screen.getByLabelText("Цена за единицу")).toHaveValue("100");
    fireEvent.change(screen.getByLabelText("Цена за единицу"), { target: { value: "125.50" } });
    fireEvent.change(screen.getByLabelText("Количество товара"), { target: { value: "3" } });
    fireEvent.click(screen.getByRole("button", { name: /Добавить в подбор|Сохранить в подборе/ }));
    fireEvent.click(screen.getAllByTitle("Изменить количество/цену")[1]);
    expect(screen.getByLabelText("Цена за единицу")).toHaveValue("200");
    expect(screen.getByLabelText("Количество товара")).toHaveValue("2");
    fireEvent.change(screen.getByLabelText("Цена за единицу"), { target: { value: "0" } });
    fireEvent.change(screen.getByLabelText("Количество товара"), { target: { value: "4" } });
    fireEvent.click(screen.getByRole("button", { name: /Добавить в подбор|Сохранить в подборе/ }));
    fireEvent.click(screen.getAllByTitle("Изменить количество/цену")[0]);
    expect(screen.getByLabelText("Цена за единицу")).toHaveValue("125.5");
    expect(screen.getByLabelText("Количество товара")).toHaveValue("3");
    fireEvent.click(screen.getByRole("button", { name: /Добавить в подбор|Сохранить в подборе/ }));
    await act(async () => { fireEvent.click(screen.getAllByRole("button", { name: "Перенести в документ" })[0]); });
    expect(api.addDealItem).toHaveBeenNthCalledWith(1, "d1", 1, 3, 125.5);
    expect(api.addDealItem).toHaveBeenNthCalledWith(2, "d1", 1, 4, 0);
  });

  it.each(["125.50", "0"])("сохраняет ручную цену %s без складской базы", async (price) => {
    render(<Harness />);
    fireEvent.click(await screen.findByText(sku.title));
    expect(screen.getByLabelText("Цена за единицу")).toHaveValue("");
    expect(screen.getByLabelText("Скидка, %")).toBeDisabled();
    fireEvent.change(screen.getByLabelText("Цена за единицу"), { target: { value: price } });
    fireEvent.click(screen.getByRole("button", { name: /Добавить в подбор|Сохранить в подборе/ }));
    fireEvent.click(screen.getByTitle("Изменить количество/цену"));
    expect(screen.getByLabelText("Цена за единицу")).toHaveValue(String(Number(price)));
    fireEvent.click(screen.getByRole("button", { name: /Добавить в подбор|Сохранить в подборе/ }));
    await act(async () => { fireEvent.click(screen.getAllByRole("button", { name: "Перенести в документ" })[0]); });
    expect(api.addDealItem).toHaveBeenCalledWith("d1", 1, 1, Number(price));
  });

  it("пустая правка известной цены остаётся null при повторном открытии и переносе", async () => {
    vi.mocked(api.fetchStock).mockResolvedValue([stock]);
    render(<Harness />);
    fireEvent.click(await screen.findByText(sku.title));
    expect(screen.getByLabelText("Цена за единицу")).toHaveValue("150");
    fireEvent.change(screen.getByLabelText("Цена за единицу"), { target: { value: "" } });
    fireEvent.click(screen.getByRole("button", { name: /Добавить в подбор|Сохранить в подборе/ }));
    expect(screen.getAllByText(/Цена не подтверждена/).length).toBeGreaterThan(0);
    fireEvent.click(screen.getByTitle("Изменить количество/цену"));
    expect(screen.getByLabelText("Цена за единицу")).toHaveValue("");
    fireEvent.click(screen.getByRole("button", { name: /Добавить в подбор|Сохранить в подборе/ }));
    await act(async () => { fireEvent.click(screen.getAllByRole("button", { name: "Перенести в документ" })[0]); });
    expect(api.addDealItem).toHaveBeenCalledWith("d1", 1, 1, null);
    expect(api.createPriceQuote).not.toHaveBeenCalled();
  });

  it.each(["-1", "ошибка"])("не подтверждает некорректную цену %s", async (price) => {
    render(<Harness />);
    fireEvent.click(await screen.findByText(sku.title));
    fireEvent.change(screen.getByLabelText("Цена за единицу"), { target: { value: price } });
    expect(screen.getByRole("alert")).toHaveTextContent("Укажите цену не меньше нуля");
    expect(screen.getByRole("button", { name: /Добавить в подбор|Сохранить в подборе/ })).toBeDisabled();
    expect(api.addDealItem).not.toHaveBeenCalled();
  });

  it("скидка рассчитывает net-цену один раз, перенос сохраняет её", async () => {
    vi.mocked(api.fetchStock).mockResolvedValue([stock]);
    render(<Harness />);
    fireEvent.click(await screen.findByText(sku.title));
    fireEvent.change(screen.getByLabelText("Скидка, %"), { target: { value: "20" } });
    expect(screen.getByLabelText("Цена за единицу")).toHaveValue("120");
    fireEvent.click(screen.getByRole("button", { name: /Добавить в подбор|Сохранить в подборе/ }));
    await act(async () => { fireEvent.click(screen.getAllByRole("button", { name: "Перенести в документ" })[0]); });
    expect(api.addDealItem).toHaveBeenCalledWith("d1", 1, 1, 120);
  });

  it.each([
    [100.50, "5", 95.48],
    [100.50, "0", 100.50],
    [1.005, "0", 1.01],
    [10.075, "0", 10.08],
    [1.0049, "0", 1],
  ])("округляет скидку HALF_UP до копеек: %s минус %s%% → %s", async (base, discount, price) => {
    vi.mocked(api.fetchStock).mockResolvedValue([{ ...stock, price: base }]);
    render(<Harness />);
    fireEvent.click(await screen.findByText(sku.title));
    if (discount === "0") fireEvent.change(screen.getByLabelText("Скидка, %"), { target: { value: "1" } });
    fireEvent.change(screen.getByLabelText("Скидка, %"), { target: { value: discount } });
    expect(screen.getByLabelText("Цена за единицу")).toHaveValue(String(price));
    fireEvent.click(screen.getByRole("button", { name: /Добавить в подбор|Сохранить в подборе/ }));
    await act(async () => { fireEvent.click(screen.getAllByRole("button", { name: "Перенести в документ" })[0]); });
    expect(api.addDealItem).toHaveBeenCalledWith("d1", 1, 1, price);
  });

  it("при частичном переносе оставляет false/rejected строки и повторяет только их", async () => {
    const skus = [sku, { ...sku, id: 2, code: "B2", title: "Товар Б" }, { ...sku, id: 3, code: "C3", title: "Товар В" }];
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true, status: 200, json: async () => skus }));
    const add = vi.mocked(api.addDealItem).mockResolvedValueOnce(true).mockResolvedValueOnce(false).mockRejectedValueOnce(new Error("network"));
    const onCommitted = vi.fn();
    render(<Harness onCommitted={onCommitted} />);
    for (const selected of skus) {
      fireEvent.click(await screen.findByText(selected.title));
      fireEvent.change(screen.getByLabelText("Цена за единицу"), { target: { value: "125.50" } });
      fireEvent.click(screen.getByRole("button", { name: /Добавить в подбор|Сохранить в подборе/ }));
    }
    await act(async () => { fireEvent.click(screen.getAllByRole("button", { name: "Перенести в документ" })[0]); });
    expect(screen.getByRole("alert")).toHaveTextContent("Перенесено позиций: 1/3");
    expect(screen.getAllByTitle("Изменить количество/цену")).toHaveLength(2);
    expect(screen.getByRole("dialog", { name: "Подбор товара" })).toBeInTheDocument();
    expect(screen.queryByText(/✅ Перенесено/)).toBeNull();
    expect(onCommitted).not.toHaveBeenCalled();
    await act(async () => { fireEvent.click(screen.getAllByRole("button", { name: "Перенести в документ" })[0]); });
    expect(add.mock.calls.map((args) => args[1])).toEqual([1, 2, 3, 2, 3]);
    expect(add).toHaveBeenNthCalledWith(4, "d1", 2, 1, 125.5);
    expect(add).toHaveBeenNthCalledWith(5, "d1", 3, 1, 125.5);
    expect(screen.queryByRole("alert")).toBeNull();
    expect(onCommitted).toHaveBeenCalledTimes(1);
  });

  it("rejection снимает busy, сохраняет ввод и разрешает успешный повтор", async () => {
    let rejectWrite!: (error: Error) => void;
    vi.mocked(api.addDealItem).mockReturnValueOnce(new Promise<boolean>((_, reject) => { rejectWrite = reject; }));
    const onClose = vi.fn();
    const onCommitted = vi.fn();
    render(<Harness onClose={onClose} onCommitted={onCommitted} />);
    fireEvent.click(await screen.findByText(sku.title));
    fireEvent.change(screen.getByLabelText("Цена за единицу"), { target: { value: "0" } });
    fireEvent.click(screen.getByRole("button", { name: /Добавить в подбор|Сохранить в подборе/ }));
    const transfer = screen.getAllByRole("button", { name: "Перенести в документ" })[0];
    fireEvent.click(transfer);
    expect(transfer).toBeDisabled();
    fireEvent.keyDown(window, { key: "Escape" });
    expect(onClose).not.toHaveBeenCalled();
    await act(async () => { rejectWrite(new Error("network")); });
    expect(screen.getByRole("alert")).toHaveTextContent("Перенесено позиций: 0/1");
    expect(transfer).toBeEnabled();
    expect(onCommitted).not.toHaveBeenCalled();
    fireEvent.click(screen.getByTitle("Изменить количество/цену"));
    expect(screen.getByLabelText("Цена за единицу")).toHaveValue("0");
    fireEvent.click(screen.getByRole("button", { name: /Добавить в подбор|Сохранить в подборе/ }));
    await act(async () => { fireEvent.click(transfer); });
    expect(api.addDealItem).toHaveBeenCalledTimes(2);
    expect(api.addDealItem).toHaveBeenLastCalledWith("d1", 1, 1, 0);
    expect(onCommitted).toHaveBeenCalledTimes(1);
  });

  it("повтор заказа с одним SKU по 100/200 оставляет отказавшую строку 200 и переносит её повторно", async () => {
    vi.mocked(api.fetchLastOrder).mockResolvedValue([100, 200].map((unit_price, index) => ({
      id: index + 9, sku_id: sku.id, code: sku.code, title: sku.title, unit: sku.unit,
      qty: 1, unit_price, last_price: 700, min_price: 500,
    })));
    vi.mocked(api.addDealItem).mockResolvedValueOnce(true).mockResolvedValueOnce(false);
    const onCommitted = vi.fn();
    render(<Harness onCommitted={onCommitted} />);
    await screen.findByText(sku.title);
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Прошлый заказ" })); });
    expect(screen.getAllByTitle("Изменить количество/цену")).toHaveLength(2);
    await act(async () => { fireEvent.click(screen.getAllByRole("button", { name: "Перенести в документ" })[0]); });
    expect(screen.getByRole("alert")).toHaveTextContent("Перенесено позиций: 1/2");
    expect(screen.getByTitle("Изменить количество/цену")).toHaveTextContent("200.00 BYN");
    expect(onCommitted).not.toHaveBeenCalled();
    await act(async () => { fireEvent.click(screen.getAllByRole("button", { name: "Перенести в документ" })[0]); });
    expect(vi.mocked(api.addDealItem).mock.calls.map((args) => args[3])).toEqual([100, 200, 200]);
    expect(api.addDealItem).toHaveBeenLastCalledWith("d1", 1, 1, 200);
    expect(screen.queryByRole("alert")).toBeNull();
    expect(onCommitted).toHaveBeenCalledTimes(1);
  });

  it("после частичного переноса сохраняет необходимость согласования уже перенесённых строк", async () => {
    const second = { ...sku, id: 2, code: "B2", title: "Товар Б" };
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true, status: 200, json: async () => [sku, second] }));
    vi.mocked(api.fetchStock).mockResolvedValue([
      { ...stock, price: 100, cost: 100 },
      { ...stock, sku_code: second.code, price: 100, cost: 0 },
    ]);
    vi.mocked(api.addDealItem).mockResolvedValueOnce(true).mockResolvedValueOnce(false);
    const onCommitted = vi.fn();
    render(<Harness onCommitted={onCommitted} />);
    fireEvent.click(await screen.findByText(sku.title));
    fireEvent.change(screen.getByLabelText("Количество товара"), { target: { value: "10" } });
    fireEvent.click(screen.getByRole("button", { name: /Добавить в подбор|Сохранить в подборе/ }));
    fireEvent.click(screen.getByText(second.title));
    fireEvent.click(screen.getByRole("button", { name: /Добавить в подбор|Сохранить в подборе/ }));
    fireEvent.click(screen.getAllByRole("button", { name: /Перенести → согласовать скидку/ })[0]);
    await act(async () => { fireEvent.click(screen.getAllByRole("button", { name: "Да, перенести (на согласование)" })[0]); });
    expect(screen.getByRole("alert")).toHaveTextContent("Перенесено позиций: 1/2");
    expect(api.requestApproval).not.toHaveBeenCalled();
    expect(onCommitted).not.toHaveBeenCalled();
    await act(async () => { fireEvent.click(screen.getAllByRole("button", { name: /Перенести → согласовать скидку/ })[0]); });
    expect(vi.mocked(api.addDealItem).mock.calls.map((args) => args[1])).toEqual([1, 2, 2]);
    expect(api.requestApproval).toHaveBeenCalledExactlyOnceWith("d1", "deal.discount");
    expect(onCommitted).toHaveBeenCalledTimes(1);
  });

  it.each(["false", "rejection"])("повторяет только согласование после %s без повторного POST товара", async (failure) => {
    vi.mocked(api.fetchStock).mockResolvedValue([{ ...stock, cost: 145 }]);
    const approval = vi.mocked(api.requestApproval);
    if (failure === "false") approval.mockResolvedValueOnce(false);
    else approval.mockRejectedValueOnce(new Error("network"));
    const onCommitted = vi.fn();
    render(<Harness onCommitted={onCommitted} />);
    fireEvent.click(await screen.findByText(sku.title));
    fireEvent.click(screen.getByRole("button", { name: /Добавить в подбор|Сохранить в подборе/ }));
    fireEvent.click(screen.getAllByRole("button", { name: /Перенести → согласовать скидку/ })[0]);
    expect(api.addDealItem).not.toHaveBeenCalled();
    await act(async () => { fireEvent.click(screen.getAllByRole("button", { name: "Да, перенести (на согласование)" })[0]); });
    expect(screen.getByRole("alert")).toHaveTextContent("не удалось отправить скидку на согласование");
    expect(screen.queryByText(/✅/)).toBeNull();
    expect(onCommitted).not.toHaveBeenCalled();
    expect(screen.getAllByRole("button", { name: "Повторить согласование" })[0]).toBeEnabled();
    await act(async () => { fireEvent.click(screen.getAllByRole("button", { name: "Повторить согласование" })[0]); });
    expect(api.addDealItem).toHaveBeenCalledTimes(1);
    expect(approval).toHaveBeenCalledTimes(2);
    expect(screen.queryByRole("alert")).toBeNull();
    expect(onCommitted).toHaveBeenCalledTimes(1);
    expect(screen.getByText(/✅ Позиции сохранены · скидка отправлена/)).toBeInTheDocument();
  });

  it("Escape вызывает актуальное сохранение родителя", async () => {
    const first = vi.fn();
    const next = vi.fn();
    const { rerender } = render(<Harness onClose={first} />);
    await screen.findByText(sku.title);
    rerender(<Harness onClose={next} />);
    fireEvent.keyDown(window, { key: "Escape" });
    await waitFor(() => expect(next).toHaveBeenCalledTimes(1));
    expect(first).not.toHaveBeenCalled();
  });
});
