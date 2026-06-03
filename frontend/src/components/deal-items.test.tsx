import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/api", () => ({
  fetchDealItems: vi.fn(),
  fetchSkus: vi.fn(),
  addDealItem: vi.fn(),
  updateDealItem: vi.fn(),
  deleteDealItem: vi.fn(),
}));

import { DealItems } from "@/components/deal-items";
import * as api from "@/lib/api";

const mock = (fn: unknown) => fn as ReturnType<typeof vi.fn>;
beforeEach(() => vi.clearAllMocks());

const item = { id: 5, sku_id: 1, code: "AKB-60", title: "Аккумулятор 60", unit: "шт", qty: 2, last_price: 1500, min_price: 1450 };

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
});
