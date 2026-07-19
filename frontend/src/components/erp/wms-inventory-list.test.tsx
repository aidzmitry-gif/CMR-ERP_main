import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const push = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push }),
}));

// Мокаем ТОЛЬКО createInventory (сеть). inventoryStatusLabel — реальный.
vi.mock("@/lib/wms-inventory", async (importActual) => {
  const actual = await importActual<typeof import("@/lib/wms-inventory")>();
  return {
    ...actual,
    createInventory: vi.fn(),
  };
});

import { WmsInventoryList } from "@/components/erp/wms-inventory-list";
import type { InventoryCount } from "@/lib/wms-inventory";
import * as wmsInventory from "@/lib/wms-inventory";

const mocked = wmsInventory as unknown as {
  createInventory: ReturnType<typeof vi.fn>;
};

function makeDoc(over: Partial<InventoryCount> = {}): InventoryCount {
  return {
    id: 7,
    number: "ИНВ-0007",
    warehouse: "Основной склад",
    status: "open",
    note: "",
    created_at: "2026-07-18T10:00:00",
    completed_at: null,
    ...over,
  };
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe("WmsInventoryList", () => {
  it("пустой список: подсказка «Инвентаризаций пока нет»", () => {
    render(<WmsInventoryList initial={[]} />);
    expect(screen.getByText("Инвентаризаций пока нет")).toBeInTheDocument();
  });

  it("список: рендерит номер, склад, статус (реальный label) и дату", () => {
    render(<WmsInventoryList initial={[makeDoc()]} />);
    expect(screen.getByRole("link", { name: "ИНВ-0007" })).toHaveAttribute(
      "href",
      "/erp/wms/inventory/7",
    );
    expect(screen.getByText("Основной склад")).toBeInTheDocument();
    // inventoryStatusLabel("open") реальный
    expect(screen.getByText("Идёт пересчёт")).toBeInTheDocument();
    expect(screen.getByText("18.07.2026")).toBeInTheDocument();
  });

  it("документ без номера получает подпись ИНВ-<id>", () => {
    render(<WmsInventoryList initial={[makeDoc({ number: "", id: 42 })]} />);
    expect(screen.getByRole("link", { name: "ИНВ-42" })).toHaveAttribute(
      "href",
      "/erp/wms/inventory/42",
    );
  });

  it("документ без даты создания показывает «—»", () => {
    render(<WmsInventoryList initial={[makeDoc({ created_at: null })]} />);
    expect(screen.getByText("—")).toBeInTheDocument();
  });

  it("статус done/canceled маппится в реальные подписи", () => {
    render(
      <WmsInventoryList
        initial={[
          makeDoc({ id: 1, status: "done" }),
          makeDoc({ id: 2, status: "canceled" }),
        ]}
      />,
    );
    expect(screen.getByText("Проведена")).toBeInTheDocument();
    expect(screen.getByText("Отменена")).toBeInTheDocument();
  });

  it("пустой ввод склада: клик по кнопке не зовёт createInventory, подсвечивает поле ошибкой", () => {
    render(<WmsInventoryList initial={[]} />);
    const input = screen.getByPlaceholderText(/Склад для инвентаризации/);
    fireEvent.click(screen.getByRole("button", { name: /Новая инвентаризация/ }));
    expect(mocked.createInventory).not.toHaveBeenCalled();
    expect(input.className).toMatch(/border-amber-500/);
  });

  it("заполненный склад: клик зовёт createInventory с обрезанным значением и переходит на страницу документа", async () => {
    mocked.createInventory.mockResolvedValue(makeDoc({ id: 55 }));
    render(<WmsInventoryList initial={[]} />);

    const input = screen.getByPlaceholderText(/Склад для инвентаризации/);
    fireEvent.change(input, { target: { value: "  Минск (центр.)  " } });
    fireEvent.click(screen.getByRole("button", { name: /Новая инвентаризация/ }));

    await waitFor(() => expect(mocked.createInventory).toHaveBeenCalledWith("Минск (центр.)"));
    expect(push).toHaveBeenCalledWith("/erp/wms/inventory/55");
  });

  it("если createInventory вернул null — редиректа не происходит", async () => {
    mocked.createInventory.mockResolvedValue(null);
    render(<WmsInventoryList initial={[]} />);

    fireEvent.change(screen.getByPlaceholderText(/Склад для инвентаризации/), {
      target: { value: "Гомель" },
    });
    fireEvent.click(screen.getByRole("button", { name: /Новая инвентаризация/ }));

    await waitFor(() => expect(mocked.createInventory).toHaveBeenCalledWith("Гомель"));
    expect(push).not.toHaveBeenCalled();
  });
});
