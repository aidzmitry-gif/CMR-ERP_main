import { fireEvent, render, screen, waitFor } from "@testing-library/react";
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
beforeEach(() => vi.clearAllMocks());

const item = { id: 5, sku_id: 1, code: "AKB-60", title: "Аккумулятор 60", unit: "шт", qty: 2, last_price: 1500, min_price: 1450 };

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
    await waitFor(() => expect(api.addDealItem).toHaveBeenCalledWith("1", 1, 1));
  });

  it("изменение количества и удаление позиции", async () => {
    mock(api.fetchDealItems).mockResolvedValue([item]);
    mock(api.fetchSkus).mockResolvedValue([]);
    mock(api.updateDealItem).mockResolvedValue(true);
    mock(api.deleteDealItem).mockResolvedValue(true);
    render(<DealItems dealId="1" />);
    expect(await screen.findByText("Аккумулятор 60")).toBeInTheDocument();

    fireEvent.change(screen.getByDisplayValue("2"), { target: { value: "7" } });
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
    fireEvent.change(screen.getByRole("spinbutton"), { target: { value: "4" } });
    fireEvent.click(screen.getByText("Добавить"));
    await waitFor(() => expect(api.addDealItem).toHaveBeenCalledWith("1", 2, 4));
  });

  it("показывает себес/маржу и метку источника из фасада (демо)", async () => {
    mock(api.fetchDealItems).mockResolvedValue([item]);
    mock(api.fetchSkus).mockResolvedValue([]);
    mock(margin.fetchDealMargin).mockResolvedValue(marginWith("demo"));
    render(<DealItems dealId="1" />);
    expect(await screen.findByText(/маржа 33%/)).toBeInTheDocument();
    expect(screen.getByText(/демо \(не 1С\)/)).toBeInTheDocument();
  });
});
