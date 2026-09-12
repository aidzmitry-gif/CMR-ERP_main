import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/api", () => ({
  fetchDealItems: vi.fn(),
  fetchSkus: vi.fn(),
  addDealItem: vi.fn(),
  updateDealItem: vi.fn(),
  deleteDealItem: vi.fn(),
}));

// Себес/маржа позиций берутся из фасада маржи (тот же источник, что карточка метрик).
// Мокаем только фетч; чистые marginBySku/COST_SRC_LABEL оставляем настоящими.
vi.mock("@/lib/margin", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/margin")>()),
  fetchDealMargin: vi.fn(() => Promise.resolve(null)),
}));

import { DealItems } from "@/components/deal-items";
import * as api from "@/lib/api";
import * as margin from "@/lib/margin";

const mock = (fn: unknown) => fn as ReturnType<typeof vi.fn>;
beforeEach(() => {
  vi.resetAllMocks();
  vi.mocked(margin.fetchDealMargin).mockResolvedValue(null);
});

const item = { id: 5, sku_id: 1, code: "AKB-60", title: "Аккумулятор 60", unit: "шт", qty: 2, unit_price: 1200, last_price: 1500, min_price: 1450 };

function marginWith(cost_source: "demo" | "onec" | "landed") {
  return {
    deal_id: 1, revenue: 3000, cogs_landed: 2000, gross_profit: 1000, margin_pct: 33,
    priced_count: 1, total_count: 1, reason: null,
    lines: [{
      sku_code: "AKB-60", title: "Аккумулятор 60", qty: 2,
      unit_price: 1500, revenue: 3000, unit_landed_cost: 1000, cogs: 2000, margin_pct: 33,
      status: "priced" as const, cost_shipment_id: null, cost_fixed_at: null, cost_fx_rate: null,
      cost_source, price_source: "quote" as const,
    }],
  };
}

describe("DealItems", () => {
  it("подбор SKU и добавление позиции", async () => {
    mock(api.fetchDealItems).mockResolvedValue([]);
    mock(api.fetchSkus).mockResolvedValue([{ id: 1, code: "AKB-60", title: "АКБ", unit: "шт" }]);
    mock(api.addDealItem).mockResolvedValue(true);
    render(<DealItems dealId="1" />);
    expect(await screen.findByText("Позиций пока нет")).toBeInTheDocument();
    await waitFor(() => expect(api.fetchSkus).toHaveBeenCalled());
    fireEvent.click(screen.getByText("Добавить"));
    await waitFor(() => expect(api.addDealItem).toHaveBeenCalledWith("1", 1, 1, null));
  });

  it("изменение количества и удаление позиции", async () => {
    mock(api.fetchDealItems).mockResolvedValue([item]);
    mock(api.fetchSkus).mockResolvedValue([]);
    mock(api.updateDealItem).mockResolvedValue(true);
    mock(api.deleteDealItem).mockResolvedValue(true);
    render(<DealItems dealId="1" />);
    expect(await screen.findByText("Аккумулятор 60")).toBeInTheDocument();

    fireEvent.change(screen.getByDisplayValue("2"), { target: { value: "7" } });
    fireEvent.click(screen.getByRole("button", { name: "Сохранить позицию Аккумулятор 60" }));
    await waitFor(() => expect(api.updateDealItem).toHaveBeenCalledWith(5, 7));

    fireEvent.click(screen.getByTitle("Удалить позицию"));
    await waitFor(() => expect(api.deleteDealItem).toHaveBeenCalledWith(5));
  });

  it("меняет SKU и количество перед добавлением", async () => {
    mock(api.fetchDealItems).mockResolvedValue([]);
    mock(api.fetchSkus).mockResolvedValue([
      { id: 1, code: "A", title: "АКБ", unit: "шт" },
      { id: 2, code: "B", title: "Лист", unit: "т" },
    ]);
    mock(api.addDealItem).mockResolvedValue(true);
    render(<DealItems dealId="1" />);
    await waitFor(() => expect(api.fetchSkus).toHaveBeenCalled());
    fireEvent.change(screen.getByRole("combobox"), { target: { value: "2" } });
    fireEvent.change(screen.getByLabelText("Количество новой позиции"), { target: { value: "4" } });
    fireEvent.click(screen.getByText("Добавить"));
    await waitFor(() => expect(api.addDealItem).toHaveBeenCalledWith("1", 2, 4, null));
  });

  it("показывает себес/маржу и метку источника из фасада (демо)", async () => {
    mock(api.fetchDealItems).mockResolvedValue([item]);
    mock(api.fetchSkus).mockResolvedValue([]);
    mock(margin.fetchDealMargin).mockResolvedValue(marginWith("demo"));
    render(<DealItems dealId="1" />);
    expect(await screen.findByText(/маржа 17%/)).toBeInTheDocument();
    expect(screen.getByText(/демо \(не 1С\)/)).toBeInTheDocument();
  });

  it("считает маржу по подтверждённой цене каждой строки одного SKU", async () => {
    const lines = [100, 200, null, 0].map((unit_price, index) => ({
      ...item, id: index + 1, title: `Строка ${index + 1}`, unit_price,
    }));
    vi.mocked(api.fetchDealItems).mockResolvedValue(lines);
    vi.mocked(api.fetchSkus).mockResolvedValue([]);
    const facade = marginWith("onec");
    facade.lines = [100, 200].map((unit_price) => ({
      ...facade.lines[0], unit_price, unit_landed_cost: 80, margin_pct: (unit_price - 80) / unit_price * 100,
    }));
    vi.mocked(margin.fetchDealMargin).mockResolvedValue(facade);
    render(<DealItems dealId="1" />);
    await screen.findByText(/маржа 20%/);
    expect(within(screen.getByText("Строка 1").closest("li")!).getByText(/маржа 20%/)).toBeInTheDocument();
    expect(within(screen.getByText("Строка 2").closest("li")!).getByText(/маржа 60%/)).toBeInTheDocument();
    for (const title of ["Строка 3", "Строка 4"]) {
      const row = within(screen.getByText(title).closest("li")!);
      expect(row.getByText(/себес/)).toBeInTheDocument();
      expect(row.queryByText(/маржа/)).toBeNull();
    }
  });

  it.each([null, 0, 1200])("показывает согласованную цену %s отдельно от истории", async (unit_price) => {
    vi.mocked(api.fetchDealItems).mockResolvedValue([{ ...item, unit_price }]);
    vi.mocked(api.fetchSkus).mockResolvedValue([]);
    render(<DealItems dealId="1" />);
    await screen.findByText(item.title);
    expect(screen.getByText(/История: последняя/)).toBeInTheDocument();
    expect(screen.getByLabelText(`Цена за единицу ${item.title}`)).toHaveValue(unit_price);
    expect(screen.getByText(unit_price === null ? "Цена не подтверждена" : /Согласованная цена:/)).toBeInTheDocument();
  });

  it.each(["false", "rejection"])("сохраняет цену и количество при отказе добавления %s и разрешает повтор", async (failure) => {
    vi.mocked(api.fetchDealItems).mockResolvedValue([]);
    vi.mocked(api.fetchSkus).mockResolvedValue([{ id: 1, code: "A", title: "Товар", unit: "шт" }]);
    const add = vi.mocked(api.addDealItem);
    if (failure === "false") add.mockResolvedValueOnce(false);
    else add.mockRejectedValueOnce(new Error("network"));
    add.mockResolvedValueOnce(true);
    render(<DealItems dealId="1" />);
    await screen.findByRole("option", { name: "A · Товар" });
    fireEvent.change(screen.getByLabelText("Количество новой позиции"), { target: { value: "3" } });
    fireEvent.change(screen.getByLabelText("Цена за единицу новой позиции"), { target: { value: "125.5" } });
    fireEvent.click(screen.getByText("Добавить"));
    expect(await screen.findByRole("alert")).toHaveTextContent("Не удалось добавить позицию");
    expect(screen.getByLabelText("Количество новой позиции")).toHaveValue(3);
    expect(screen.getByLabelText("Цена за единицу новой позиции")).toHaveValue(125.5);
    expect(screen.getByText("Добавить")).toBeEnabled();
    expect(api.fetchDealItems).toHaveBeenCalledTimes(1);
    fireEvent.click(screen.getByText("Добавить"));
    await waitFor(() => expect(screen.getByLabelText("Цена за единицу новой позиции")).toHaveValue(null));
    expect(add).toHaveBeenNthCalledWith(2, "1", 1, 3, 125.5);
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it.each([0, null, 999.25])("сохраняет явную новую цену %s в строке", async (price) => {
    vi.mocked(api.fetchDealItems).mockResolvedValue([item]);
    vi.mocked(api.fetchSkus).mockResolvedValue([]);
    vi.mocked(api.updateDealItem).mockResolvedValue(true);
    render(<DealItems dealId="1" />);
    await screen.findByText(item.title);
    fireEvent.change(screen.getByLabelText(`Цена за единицу ${item.title}`), { target: { value: price == null ? "" : String(price) } });
    vi.mocked(api.fetchDealItems).mockResolvedValueOnce([{ ...item, unit_price: price }]);
    fireEvent.click(screen.getByRole("button", { name: `Сохранить позицию ${item.title}` }));
    await waitFor(() => expect(api.updateDealItem).toHaveBeenCalledWith(item.id, item.qty, price));
    await waitFor(() => expect(screen.getByRole("button", { name: `Сохранить позицию ${item.title}` })).toBeDisabled());
    expect(screen.getByLabelText(`Цена за единицу ${item.title}`)).toHaveValue(price);
  });

  it.each(["false", "rejection"])("редактирование при %s сохраняет черновик и подтверждённую цену", async (failure) => {
    vi.mocked(api.fetchDealItems).mockResolvedValue([item]);
    vi.mocked(api.fetchSkus).mockResolvedValue([]);
    const update = vi.mocked(api.updateDealItem);
    if (failure === "false") update.mockResolvedValueOnce(false);
    else update.mockRejectedValueOnce(new Error("network"));
    update.mockResolvedValueOnce(true);
    render(<DealItems dealId="1" />);
    await screen.findByText(item.title);
    const agreed = screen.getByText(/Согласованная цена:/).textContent;
    fireEvent.change(screen.getByLabelText(`Цена за единицу ${item.title}`), { target: { value: "0" } });
    fireEvent.change(screen.getByLabelText(`Количество ${item.title}`), { target: { value: "3" } });
    const save = screen.getByRole("button", { name: `Сохранить позицию ${item.title}` });
    fireEvent.click(save);
    expect(await screen.findByRole("alert")).toHaveTextContent("Не удалось сохранить позицию");
    expect(screen.getByLabelText(`Цена за единицу ${item.title}`)).toHaveValue(0);
    expect(screen.getByLabelText(`Количество ${item.title}`)).toHaveValue(3);
    expect(screen.getByText(/Согласованная цена:/).textContent).toBe(agreed);
    expect(save).toBeEnabled();
    expect(api.fetchDealItems).toHaveBeenCalledTimes(1);
    vi.mocked(api.fetchDealItems).mockResolvedValueOnce([{ ...item, qty: 3, unit_price: 0 }]);
    fireEvent.click(save);
    await waitFor(() => expect(save).toBeDisabled());
    expect(update).toHaveBeenNthCalledWith(2, item.id, 3, 0);
    expect(screen.queryByRole("alert")).toBeNull();
    await waitFor(() => expect(screen.getByText(/Согласованная цена:/).textContent).not.toBe(agreed));
  });
});
