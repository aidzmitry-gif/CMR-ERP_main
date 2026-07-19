import { fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { WmsStockView } from "@/components/erp/wms-stock-view";
import type { StockMirror } from "@/lib/wms-stock";
import type { StockThreshold } from "@/lib/wms-warehouse";

function mirror(over: Partial<StockMirror> = {}): StockMirror {
  return {
    rows: [],
    warehouses: [],
    total_available: 0,
    total_reserved: 0,
    total_free: 0,
    sku_count: 0,
    gateway: true,
    truncated: false,
    ...over,
  };
}

const rowA = {
  sku_code: "SKU-1",
  title: "Кабель ВВГ 3x2.5",
  unit: "м",
  warehouse: "Минск",
  qty_available: 100,
  qty_reserved: 20,
  qty_free: 80,
  qty_forecast: 0,
  updated_at: null,
};

const rowB = {
  sku_code: "SKU-2",
  title: "Розетка накладная",
  unit: "шт",
  warehouse: "Гомель",
  qty_available: 5,
  qty_reserved: 0,
  qty_free: 5,
  qty_forecast: 0,
  updated_at: null,
};

let fetchMock: ReturnType<typeof vi.fn>;

beforeEach(() => {
  fetchMock = vi.fn(() =>
    Promise.resolve({
      ok: true,
      json: async () =>
        mirror({ rows: [rowA], warehouses: ["Минск"], gateway: true }),
    }),
  );
  vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => vi.unstubAllGlobals());

describe("WmsStockView", () => {
  it("рендерит строки остатков с форматированными числами", () => {
    render(<WmsStockView initial={mirror({ rows: [rowA, rowB], warehouses: ["Минск", "Гомель"] })} thresholds={[]} />);

    expect(screen.getByText("SKU-1")).toBeInTheDocument();
    expect(screen.getByText("Кабель ВВГ 3x2.5")).toBeInTheDocument();
    expect(screen.getByText("100")).toBeInTheDocument();
    expect(screen.getByText("20")).toBeInTheDocument();
    expect(screen.getByText("80")).toBeInTheDocument();
  });

  it("пустые остатки при подключённом шлюзе показывают «Остатков по фильтру нет»", () => {
    render(<WmsStockView initial={mirror({ rows: [], gateway: true })} thresholds={[]} />);
    expect(screen.getByText("Остатков по фильтру нет")).toBeInTheDocument();
  });

  it("при gateway=false показывает предупреждение и «Нет данных об остатках»", () => {
    render(<WmsStockView initial={mirror({ rows: [], gateway: false })} thresholds={[]} />);
    expect(
      screen.getByText("Источник остатков (1С / integrations) не подключён — данные недоступны."),
    ).toBeInTheDocument();
    expect(screen.getByText("Нет данных об остатках")).toBeInTheDocument();
  });

  it("резерв 0 отображается как «—», ненулевой резерв — числом", () => {
    render(<WmsStockView initial={mirror({ rows: [rowA, rowB], warehouses: ["Минск", "Гомель"] })} thresholds={[]} />);
    const trA = screen.getByText("SKU-1").closest("tr") as HTMLElement;
    const trB = screen.getByText("SKU-2").closest("tr") as HTMLElement;
    const cellsA = within(trA).getAllByRole("cell");
    const cellsB = within(trB).getAllByRole("cell");
    expect(cellsA[4]).toHaveTextContent("20"); // rowA: qty_reserved=20
    expect(cellsB[4]).toHaveTextContent("—"); // rowB: qty_reserved=0 → прочерк
  });

  it("строка ниже порога подсвечивается и показывает порог в колонке «Порог»", () => {
    const thresholds: StockThreshold[] = [
      { sku_code: "SKU-1", warehouse: "Минск", min_qty: 100, active: true },
    ];
    render(
      <WmsStockView
        initial={mirror({ rows: [rowA], warehouses: ["Минск"] })}
        thresholds={thresholds}
      />,
    );
    const tr = screen.getByText("SKU-1").closest("tr") as HTMLElement;
    expect(tr.className).toMatch(/bg-red-50/);
    const cells = within(tr).getAllByRole("cell");
    expect(cells[6]).toHaveTextContent("100"); // колонка «Порог»
    expect(cells[6].className).toMatch(/text-red-600/);
  });

  it("неактивный порог (active=false) не учитывается — строка не подсвечивается, «Порог» = —", () => {
    const thresholds: StockThreshold[] = [
      { sku_code: "SKU-1", warehouse: "Минск", min_qty: 100, active: false },
    ];
    render(
      <WmsStockView
        initial={mirror({ rows: [rowA], warehouses: ["Минск"] })}
        thresholds={thresholds}
      />,
    );
    const tr = screen.getByText("SKU-1").closest("tr") as HTMLElement;
    expect(tr.className).not.toMatch(/bg-red-50/);
    expect(within(tr).getByText("—")).toBeInTheDocument();
  });

  it("клик по вкладке склада фильтрует строки по выбранному складу", () => {
    render(
      <WmsStockView
        initial={mirror({ rows: [rowA, rowB], warehouses: ["Минск", "Гомель"] })}
        thresholds={[]}
      />,
    );
    expect(screen.getByText("SKU-1")).toBeInTheDocument();
    expect(screen.getByText("SKU-2")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Гомель" }));

    expect(screen.queryByText("SKU-1")).not.toBeInTheDocument();
    expect(screen.getByText("SKU-2")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Все склады" }));
    expect(screen.getByText("SKU-1")).toBeInTheDocument();
    expect(screen.getByText("SKU-2")).toBeInTheDocument();
  });

  it("кнопка «Обновить» дергает fetchStockMirror (/api/wms/stock) и подменяет данные", async () => {
    fetchMock.mockImplementationOnce(() =>
      Promise.resolve({
        ok: true,
        json: async () => mirror({ rows: [rowB], warehouses: ["Гомель"], gateway: true }),
      }),
    );

    render(<WmsStockView initial={mirror({ rows: [rowA], warehouses: ["Минск"] })} thresholds={[]} />);
    expect(screen.getByText("SKU-1")).toBeInTheDocument();

    fireEvent.click(screen.getByText("Обновить"));

    expect(await screen.findByText("SKU-2")).toBeInTheDocument();
    expect(screen.queryByText("SKU-1")).not.toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledWith("/api/wms/stock", { cache: "no-store" });
  });

  it("truncated=true показывает подсказку «Показаны не все SKU»", () => {
    render(<WmsStockView initial={mirror({ rows: [rowA], warehouses: ["Минск"], truncated: true })} thresholds={[]} />);
    expect(screen.getByText(/Показаны не все SKU/)).toBeInTheDocument();
  });

  it("качественный свободный остаток (qty_free>0, без порога) окрашен зелёным, а не красным", () => {
    render(<WmsStockView initial={mirror({ rows: [rowA], warehouses: ["Минск"] })} thresholds={[]} />);
    const tr = screen.getByText("SKU-1").closest("tr") as HTMLElement;
    const freeCell = within(tr).getByText("80");
    expect(freeCell.className).toMatch(/text-green-600/);
  });
});
