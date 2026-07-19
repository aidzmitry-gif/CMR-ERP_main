import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

// Мокаем ТОЛЬКО сетевые функции домена (fetch/populate/complete/updateLine).
// Чистые хелперы (inventoryStatusLabel, varianceTone) и format.ts — реальные:
// компонент должен реально маппить статус в подпись и знак расхождения в тон.
vi.mock("@/lib/wms-inventory", async (importActual) => {
  const actual = await importActual<typeof import("@/lib/wms-inventory")>();
  return {
    ...actual,
    fetchInventoryDetail: vi.fn(),
    populateInventory: vi.fn(),
    completeInventory: vi.fn(),
    updateInventoryLine: vi.fn(),
  };
});

import { WmsInventoryDetail } from "@/components/erp/wms-inventory-detail";
import type { InventoryDetail, InventoryLine } from "@/lib/wms-inventory";
import * as wms from "@/lib/wms-inventory";

const mocked = wms as unknown as {
  fetchInventoryDetail: ReturnType<typeof vi.fn>;
  populateInventory: ReturnType<typeof vi.fn>;
  completeInventory: ReturnType<typeof vi.fn>;
  updateInventoryLine: ReturnType<typeof vi.fn>;
};

// Недостача: факт 8 < ожидалось 10 → variance -2, деньги -600 (short/red).
const shortLine: InventoryLine = {
  id: 101,
  sku_code: "6СТ-190",
  sku_title: "АКБ 190",
  unit: "шт",
  expected_qty: 10,
  counted_qty: 8,
  unit_cost: 300,
  variance: -2,
  variance_value: -600,
  note: "",
};
// Излишек: факт 7 > ожидалось 5 → variance +2, деньги +500 (over/amber).
const overLine: InventoryLine = {
  id: 102,
  sku_code: "ARM-12",
  sku_title: "Арматура 12",
  unit: "т",
  expected_qty: 5,
  counted_qty: 7,
  unit_cost: 250,
  variance: 2,
  variance_value: 500,
  note: "",
};

function makeDoc(over: Partial<InventoryDetail> = {}): InventoryDetail {
  return {
    id: 7,
    number: "ИНВ-0007",
    warehouse: "Основной склад",
    status: "open",
    note: "",
    created_at: null,
    completed_at: null,
    lines: [shortLine, overLine],
    summary: {
      lines: 2,
      counted: 2,
      shortages: 1,
      surpluses: 1,
      shortage_value: 640,
      surplus_value: 910,
      net_value: 270,
    },
    ...over,
  };
}

const emptyDoc = makeDoc({
  lines: [],
  summary: { lines: 0, counted: 0, shortages: 0, surpluses: 0, shortage_value: 0, surplus_value: 0, net_value: 0 },
});

const doneDoc = makeDoc({ status: "done", completed_at: "2026-07-18T10:00:00" });

function rowOf(title: string): HTMLTableRowElement {
  return screen.getByText(title).closest("tr") as HTMLTableRowElement;
}

beforeEach(() => vi.clearAllMocks());

describe("WmsInventoryDetail", () => {
  it("открытый документ: шапка, статус «Идёт пересчёт» и сводка недостач/излишков", () => {
    render(<WmsInventoryDetail initial={makeDoc()} />);
    expect(screen.getByRole("heading", { name: "ИНВ-0007" })).toBeInTheDocument();
    expect(screen.getByText(/Основной склад/)).toBeInTheDocument();
    // статус берётся из реального inventoryStatusLabel("open")
    expect(screen.getByText("Идёт пересчёт")).toBeInTheDocument();
    // деньги недостач/излишков (KPI-плитки) — по реальному formatByn
    expect(screen.getByText("640 BYN")).toBeInTheDocument();
    expect(screen.getByText("910 BYN")).toBeInTheDocument();
    // строки / посчитано
    expect(screen.getByText("2 / 2")).toBeInTheDocument();
  });

  it("тон строки следует знаку расхождения: недостача — красная, излишек — янтарный", () => {
    render(<WmsInventoryDetail initial={makeDoc()} />);
    // 6 колонок; [4]=Расхождение, [5]=В деньгах — тон общий для обеих
    const shortCells = rowOf("АКБ 190").querySelectorAll("td");
    const overCells = rowOf("Арматура 12").querySelectorAll("td");
    expect(shortCells[4].className).toMatch(/text-red-600/);
    expect(overCells[4].className).toMatch(/text-amber-600/);
    // излишек отрисован со знаком «+»
    expect(overCells[4].textContent).toContain("+2");
  });

  it("пустой документ: подсказка «Подтянуть из 1С» и скрытая кнопка «Провести»", () => {
    render(<WmsInventoryDetail initial={emptyDoc} />);
    expect(screen.getByText(/Строк нет/)).toBeInTheDocument();
    // «Провести» появляется только когда есть строки
    expect(screen.queryByRole("button", { name: /Провести/ })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Подтянуть из 1С/ })).toBeInTheDocument();
  });

  it("«Подтянуть из 1С» зовёт populateInventory и подставляет пришедшие строки", async () => {
    mocked.populateInventory.mockResolvedValue(makeDoc());
    render(<WmsInventoryDetail initial={emptyDoc} />);
    expect(screen.queryByText("АКБ 190")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /Подтянуть из 1С/ }));

    await waitFor(() => expect(mocked.populateInventory).toHaveBeenCalledWith(7));
    expect(await screen.findByText("АКБ 190")).toBeInTheDocument();
    expect(screen.getByText("Арматура 12")).toBeInTheDocument();
  });

  it("правка факта: ввод + blur шлёт counted_qty (запятая → точка) и перечитывает документ", async () => {
    mocked.updateInventoryLine.mockResolvedValue(true);
    mocked.fetchInventoryDetail.mockResolvedValue(makeDoc());
    render(<WmsInventoryDetail initial={makeDoc()} />);

    const input = within(rowOf("Арматура 12")).getByRole("textbox");
    fireEvent.change(input, { target: { value: "7,5" } });
    fireEvent.blur(input);

    await waitFor(() =>
      expect(mocked.updateInventoryLine).toHaveBeenCalledWith(102, { counted_qty: 7.5 }),
    );
    // после записи компонент перечитывает detail (refresh)
    expect(mocked.fetchInventoryDetail).toHaveBeenCalledWith(7);
  });

  it("пустой факт трактуется как null (сброс пересчёта строки)", async () => {
    mocked.updateInventoryLine.mockResolvedValue(true);
    mocked.fetchInventoryDetail.mockResolvedValue(makeDoc());
    render(<WmsInventoryDetail initial={makeDoc()} />);

    const input = within(rowOf("АКБ 190")).getByRole("textbox");
    fireEvent.change(input, { target: { value: "" } });
    fireEvent.blur(input);

    await waitFor(() =>
      expect(mocked.updateInventoryLine).toHaveBeenCalledWith(101, { counted_qty: null }),
    );
  });

  it("нечисловой ввод не отправляется на сервер (защита от порчи факта)", async () => {
    render(<WmsInventoryDetail initial={makeDoc()} />);

    const input = within(rowOf("АКБ 190")).getByRole("textbox");
    fireEvent.change(input, { target: { value: "abc" } });
    fireEvent.blur(input);

    // даём микротаскам отработать — вызова быть не должно
    await Promise.resolve();
    expect(mocked.updateInventoryLine).not.toHaveBeenCalled();
  });

  it("«Провести» зовёт completeInventory и после успеха перечитывает как проведённый", async () => {
    mocked.completeInventory.mockResolvedValue(true);
    mocked.fetchInventoryDetail.mockResolvedValue(doneDoc);
    render(<WmsInventoryDetail initial={makeDoc()} />);

    fireEvent.click(screen.getByRole("button", { name: /Провести/ }));

    await waitFor(() => expect(mocked.completeInventory).toHaveBeenCalledWith(7));
    // refresh подтянул проведённый документ → появился баннер и подпись статуса
    expect(await screen.findByText(/Инвентаризация проведена/)).toBeInTheDocument();
    expect(screen.getByText("Проведена")).toBeInTheDocument();
  });

  it("проведённый документ заблокирован: факт — текстом, без инпутов и кнопок действий", () => {
    render(<WmsInventoryDetail initial={doneDoc} />);
    expect(screen.getByText("Проведена")).toBeInTheDocument();
    expect(screen.getByText(/Инвентаризация проведена/)).toBeInTheDocument();
    // никакого редактирования: инпутов нет
    expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Провести/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Подтянуть из 1С/ })).not.toBeInTheDocument();
    // факт показан как значение
    expect(within(rowOf("АКБ 190")).getByText("8")).toBeInTheDocument();
  });
});
