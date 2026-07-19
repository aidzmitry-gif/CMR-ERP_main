import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { StockMirror } from "@/lib/wms-stock";

import { WmsStockTable } from "./wms-stock-table";

const fetchStockMirror = vi.fn();

vi.mock("@/lib/wms-stock", async () => {
  const actual = await vi.importActual<typeof import("@/lib/wms-stock")>("@/lib/wms-stock");
  return {
    ...actual,
    fetchStockMirror: (...args: unknown[]) => fetchStockMirror(...args),
  };
});

function makeMirror(overrides: Partial<StockMirror> = {}): StockMirror {
  return {
    rows: [
      {
        sku_code: "SKU-001",
        title: "Аккумулятор 18650",
        unit: "шт",
        warehouse: "Минск",
        qty_available: 100,
        qty_reserved: 30,
        qty_free: 70,
        qty_forecast: 0,
        updated_at: null,
      },
      {
        sku_code: "SKU-002",
        title: "Зарядное устройство",
        unit: "шт",
        warehouse: "Гомель",
        qty_available: 5,
        qty_reserved: 5,
        qty_free: 0,
        qty_forecast: 20,
        updated_at: null,
      },
    ],
    warehouses: ["Минск", "Гомель"],
    total_available: 105,
    total_reserved: 35,
    total_free: 70,
    sku_count: 2,
    gateway: true,
    truncated: false,
    ...overrides,
  };
}

beforeEach(() => {
  fetchStockMirror.mockReset();
});

describe("WmsStockTable", () => {
  it("рендерит строки и KPI по начальным данным (SSR)", async () => {
    const initial = makeMirror();
    fetchStockMirror.mockResolvedValue(initial);

    render(<WmsStockTable initial={initial} />);

    expect(screen.getByText("SKU-001")).toBeInTheDocument();
    expect(screen.getByText("Аккумулятор 18650")).toBeInTheDocument();
    expect(screen.getByText("SKU-002")).toBeInTheDocument();

    // KPI: всего на складах = 105, в резерве = 35, свободно = 70, позиций = 2
    expect(screen.getByText("2")).toBeInTheDocument();
    expect(screen.getByText("105")).toBeInTheDocument();
    expect(screen.getByText("35")).toBeInTheDocument();
    expect(screen.getAllByText("70").length).toBeGreaterThan(0);

    await waitFor(() => expect(fetchStockMirror).toHaveBeenCalledTimes(1));
  });

  it("показывает предупреждение о недоступности шлюза, когда gateway=false", () => {
    const initial = makeMirror({ gateway: false, rows: [], warehouses: [], sku_count: 0 });
    fetchStockMirror.mockResolvedValue(initial);

    render(<WmsStockTable initial={initial} />);

    expect(
      screen.getByText("Источник остатков (1С / integrations) не подключён — данные недоступны."),
    ).toBeInTheDocument();
    expect(screen.getByText("Нет данных об остатках")).toBeInTheDocument();
  });

  it("при пустом фильтре и подключённом шлюзе показывает «нет остатков по фильтру»", () => {
    const initial = makeMirror({ rows: [] });
    fetchStockMirror.mockResolvedValue(initial);

    render(<WmsStockTable initial={initial} />);

    expect(screen.getByText("Остатков по фильтру нет")).toBeInTheDocument();
  });

  it("фильтрует строки по складу при клике на таб", async () => {
    const initial = makeMirror();
    fetchStockMirror.mockResolvedValue(initial);

    render(<WmsStockTable initial={initial} />);
    await waitFor(() => expect(fetchStockMirror).toHaveBeenCalledTimes(1));

    fireEvent.click(screen.getByRole("button", { name: "Гомель" }));

    expect(screen.queryByText("SKU-001")).not.toBeInTheDocument();
    expect(screen.getByText("SKU-002")).toBeInTheDocument();

    // вернуться ко всем складам
    fireEvent.click(screen.getByRole("button", { name: "Все склады" }));
    expect(screen.getByText("SKU-001")).toBeInTheDocument();
    expect(screen.getByText("SKU-002")).toBeInTheDocument();
  });

  it("фильтрует строки по поисковому запросу", async () => {
    const initial = makeMirror();
    fetchStockMirror.mockResolvedValue(initial);

    render(<WmsStockTable initial={initial} />);
    await waitFor(() => expect(fetchStockMirror).toHaveBeenCalledTimes(1));

    const input = screen.getByPlaceholderText("Поиск по коду или названию");
    fireEvent.change(input, { target: { value: "зарядное" } });

    expect(screen.queryByText("SKU-001")).not.toBeInTheDocument();
    expect(screen.getByText("SKU-002")).toBeInTheDocument();
  });

  it("по клику «Обновить» перезапрашивает данные и обновляет таблицу", async () => {
    const initial = makeMirror();
    fetchStockMirror.mockResolvedValue(initial);

    render(<WmsStockTable initial={initial} />);
    await waitFor(() => expect(fetchStockMirror).toHaveBeenCalledTimes(1));

    const updated = makeMirror({
      rows: [
        {
          sku_code: "SKU-003",
          title: "Новая позиция",
          unit: "шт",
          warehouse: "Минск",
          qty_available: 9,
          qty_reserved: 0,
          qty_free: 9,
          qty_forecast: 0,
          updated_at: null,
        },
      ],
      warehouses: ["Минск"],
      sku_count: 1,
    });
    fetchStockMirror.mockResolvedValue(updated);

    fireEvent.click(screen.getByRole("button", { name: /Обновить/ }));

    await waitFor(() => expect(fetchStockMirror).toHaveBeenCalledTimes(2));
    await waitFor(() => expect(screen.getByText("SKU-003")).toBeInTheDocument());
    expect(screen.queryByText("SKU-001")).not.toBeInTheDocument();
  });

  it("показывает прочерк для резерва/прогноза, когда они равны нулю, и подсвечивает нулевой остаток свободного", () => {
    const initial = makeMirror({
      rows: [
        {
          sku_code: "SKU-002",
          title: "Зарядное устройство",
          unit: "шт",
          warehouse: "Гомель",
          qty_available: 5,
          qty_reserved: 0,
          qty_free: 0,
          qty_forecast: 0,
          updated_at: null,
        },
      ],
      warehouses: ["Гомель"],
      sku_count: 1,
    });
    fetchStockMirror.mockResolvedValue(initial);

    render(<WmsStockTable initial={initial} />);

    const row = screen.getByText("SKU-002").closest("tr");
    expect(row).not.toBeNull();
    const cells = row!.querySelectorAll("td");
    // Резерв (индекс 4) и Ожидается (индекс 6) — прочерк при нуле
    expect(cells[4].textContent).toBe("—");
    expect(cells[6].textContent).toBe("—");
    // Свободно = 0 → класс text-faint (не зелёный)
    expect(cells[5].className).toContain("text-faint");
    expect(cells[5].className).not.toContain("text-green-600");
  });

  it("показывает подсказку об усечении выборки, когда truncated=true", () => {
    const initial = makeMirror({ truncated: true });
    fetchStockMirror.mockResolvedValue(initial);

    render(<WmsStockTable initial={initial} />);

    expect(
      screen.getByText("Показаны не все SKU (выборка ограничена) — уточните поиск."),
    ).toBeInTheDocument();
  });
});
