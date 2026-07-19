import { fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { formatByn, formatNumber } from "@/lib/format";

// Частичный мок: только сетевая fetchOpenOrders — мок; чистые хелперы (orderTotals/
// statusLabel/daysToEta) остаются НАСТОЯЩИМИ, чтобы итоги и подписи считались по-честному.
vi.mock("@/lib/procurement-orders", async (importActual) => {
  const actual = await importActual<typeof import("@/lib/procurement-orders")>();
  return {
    ...actual,
    fetchOpenOrders: vi.fn(),
  };
});

import { ProcurementOpenOrdersTable } from "@/components/erp/procurement-open-orders-table";
import * as api from "@/lib/procurement-orders";
import type { OpenOrder } from "@/lib/procurement-orders";

const fetchOpenOrders = api.fetchOpenOrders as ReturnType<typeof vi.fn>;

// Intl.NumberFormat("ru-RU") группирует тысячи неразрывным пробелом (U+00A0); jest-dom
// нормализует текстовые узлы под обычный пробел — сравниваем после общей нормализации.
const norm = (s: string) => s.replace(/ /g, " ");

function order(over: Partial<OpenOrder> = {}): OpenOrder {
  return {
    id: 1,
    number: "PO-001",
    supplier: "ABC Ltd",
    status: "shipped",
    eta_date: null,
    freight_byn: 0,
    lines: [],
    ...over,
  };
}

const rows: OpenOrder[] = [
  order({
    id: 1,
    number: "PO-001",
    supplier: "ABC Ltd",
    status: "shipped",
    eta_date: "2026-07-22", // «сейчас» зафиксировано на 2026-07-19 → +3 дня, amber
    freight_byn: 150.5,
    lines: [
      { sku_code: "SKU1", qty: 10, goods_value_byn: 1000, weight: 1, volume: 1 },
      { sku_code: "SKU2", qty: 5, goods_value_byn: 500, weight: 1, volume: 1 },
    ],
  }),
  order({
    id: 2,
    number: "PO-002",
    supplier: "",
    status: "customs",
    eta_date: null,
    freight_byn: 0,
    lines: [],
  }),
];

beforeEach(() => {
  // shouldAdvanceTime — таймеры RTL (findBy/waitFor) продолжают реально тикать,
  // а Date.now() зафиксирован на 2026-07-19 для детерминированного ETA.
  vi.useFakeTimers({ shouldAdvanceTime: true });
  vi.setSystemTime(new Date("2026-07-19T00:00:00.000Z"));
  vi.clearAllMocks();
  // Эффект на маунте всегда зовёт fetchOpenOrders — по умолчанию отдаём те же строки,
  // чтобы не затирать переданный initial неожиданно (индивидуальные тесты переопределяют).
  fetchOpenOrders.mockResolvedValue(rows);
});

afterEach(() => {
  vi.useRealTimers();
});

describe("ProcurementOpenOrdersTable", () => {
  it("пустой список показывает заглушку «Открытых заказов нет»", () => {
    fetchOpenOrders.mockResolvedValue([]);
    render(<ProcurementOpenOrdersTable initial={[]} />);
    expect(
      screen.getByText("Открытых заказов нет — всё принято или ничего не в пути."),
    ).toBeInTheDocument();
  });

  it("KPI-плашки считают итоги по заказам: количество, позиции, товар и фрахт в BYN", () => {
    render(<ProcurementOpenOrdersTable initial={rows} />);
    // 2 заказа, 2 позиции (2 строки в первом + 0 во втором), товар 1500, фрахт 150.5
    expect(norm(screen.getByText("Открытых заказов").nextSibling!.textContent!)).toBe(
      formatNumber(2),
    );
    expect(norm(screen.getByText("Позиций в пути").nextSibling!.textContent!)).toBe(
      formatNumber(2),
    );
    expect(norm(screen.getByText("Товар в пути").nextSibling!.textContent!)).toBe(
      norm(formatByn(1500)),
    );
    expect(norm(screen.getByText("Фрахт в пути").nextSibling!.textContent!)).toBe(
      norm(formatByn(150.5)),
    );
  });

  it("рендерит строки: номер, поставщик (или «—»), человекочитаемый статус и сумму товара", () => {
    render(<ProcurementOpenOrdersTable initial={rows} />);
    expect(screen.getByText("PO-001")).toBeInTheDocument();
    expect(screen.getByText("ABC Ltd")).toBeInTheDocument();
    expect(screen.getByText("Отгружен")).toBeInTheDocument(); // statusLabel("shipped")
    expect(screen.getByText("Таможня")).toBeInTheDocument(); // statusLabel("customs")

    const row1 = screen.getByText("PO-001").closest("tr")!;
    const goodsCell = row1.querySelector("td:nth-child(6)")!;
    expect(norm(goodsCell.textContent!)).toBe(norm(formatNumber(1500))); // 1000+500

    const row2 = screen.getByText("PO-002").closest("tr")!;
    const supplierCell2 = row2.querySelector("td:nth-child(2)")!;
    expect(supplierCell2.textContent).toBe("—"); // пустой поставщик → «—»
  });

  it("нулевой фрахт показывает «—», а ненулевой — отформатированное число", () => {
    render(<ProcurementOpenOrdersTable initial={rows} />);
    const row1 = screen.getByText("PO-001").closest("tr")!;
    const freightCell1 = row1.querySelector("td:nth-child(7)")!;
    expect(norm(freightCell1.textContent!)).toBe(formatNumber(150.5));

    const row2 = screen.getByText("PO-002").closest("tr")!;
    const freightCell2 = row2.querySelector("td:nth-child(7)")!;
    expect(freightCell2.textContent).toBe("—");
    // и поставщик, и фрахт у второй строки — «—» (два прочерка в строке)
    expect(within(row2).getAllByText("—").length).toBeGreaterThanOrEqual(2);
  });

  it("ETA без даты — прочерк, наступающая через 3 дня — янтарным с подсказкой «через 3 дня»", () => {
    render(<ProcurementOpenOrdersTable initial={rows} />);
    const row1 = screen.getByText("PO-001").closest("tr")!;
    const etaCell1 = row1.querySelector("td:nth-child(4)")!;
    expect(etaCell1).toHaveTextContent("2026-07-22");
    expect(etaCell1).toHaveTextContent("через 3 дня");
    expect(etaCell1.querySelector("span")).toHaveClass("text-amber-600");

    const row2 = screen.getByText("PO-002").closest("tr")!;
    const etaCell2 = row2.querySelector("td:nth-child(4)")!;
    expect(etaCell2.textContent).toBe("—"); // ETA нет
  });

  it("просроченная ETA окрашена красным с подсказкой «просрочено на N дней»", () => {
    const late = [order({ id: 3, number: "PO-003", eta_date: "2026-07-17" })]; // -2 дня от «сейчас»
    fetchOpenOrders.mockResolvedValue(late);
    render(<ProcurementOpenOrdersTable initial={late} />);
    const row = screen.getByText("PO-003").closest("tr")!;
    const etaCell = row.querySelector("td:nth-child(4)")!;
    expect(etaCell).toHaveTextContent("просрочено на 2 дня");
    expect(etaCell.querySelector("span")).toHaveClass("text-red-600");
  });

  it("список позиций заказа показывает артикул и количество каждой строки", () => {
    render(<ProcurementOpenOrdersTable initial={rows} />);
    const row1 = screen.getByText("PO-001").closest("tr")!;
    expect(within(row1).getByText("SKU1")).toBeInTheDocument();
    expect(within(row1).getByText(`× ${formatNumber(10)}`, { exact: false })).toBeInTheDocument();
    expect(within(row1).getByText("SKU2")).toBeInTheDocument();
    expect(within(row1).getByText(`× ${formatNumber(5)}`, { exact: false })).toBeInTheDocument();

    const row2 = screen.getByText("PO-002").closest("tr")!;
    const positionsCell2 = row2.querySelector("td:nth-child(5)")!;
    // у второго заказа позиций нет → прочерк в колонке позиций
    expect(positionsCell2.textContent).toBe("—");
  });

  it("«Обновить» перечитывает заказы через fetchOpenOrders и обновляет таблицу", async () => {
    render(<ProcurementOpenOrdersTable initial={rows} />);
    expect(screen.queryByText("PO-999")).not.toBeInTheDocument();

    const fresh = [order({ id: 9, number: "PO-999", supplier: "Свежий" })];
    fetchOpenOrders.mockResolvedValueOnce(fresh);
    fireEvent.click(screen.getByRole("button", { name: /Обновить/ }));

    expect(await screen.findByText("PO-999")).toBeInTheDocument();
    expect(screen.queryByText("PO-001")).not.toBeInTheDocument();
  });
});
